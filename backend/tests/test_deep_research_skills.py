"""Phase 26/27 技能库单测：SKILL.md 解析、种子加载、主/子 agent skills 装配。全离线。"""

import asyncio

import pytest

from app.agent import skills_loader
from app.agent.deep_research import _build_agent

MAIN_SKILLS = {"trip-comparison", "budget-estimation", "visa-policy-research"}
RESEARCHER_SKILLS = {"amap-data-lookup", "web-source-triage"}


# ---------- SKILL.md frontmatter 用 deepagents 自带解析器验证 ----------

def test_main_skills_parse_with_deepagents():
    from deepagents.backends.filesystem import FilesystemBackend
    from deepagents.middleware.skills import _list_skills

    backend = FilesystemBackend(root_dir=skills_loader.SKILLS_ROOT, virtual_mode=True)
    skills = _list_skills(backend, "/main/")
    names = {s["name"] for s in skills}
    assert names == MAIN_SKILLS
    for s in skills:
        assert s["description"]


def test_researcher_skills_parse_with_deepagents():
    from deepagents.backends.filesystem import FilesystemBackend
    from deepagents.middleware.skills import _list_skills

    backend = FilesystemBackend(root_dir=skills_loader.SKILLS_ROOT, virtual_mode=True)
    skills = _list_skills(backend, "/researcher/")
    names = {s["name"] for s in skills}
    assert names == RESEARCHER_SKILLS
    for s in skills:
        assert s["description"]


# ---------- skills_loader：磁盘 -> StateBackend files 种子 ----------

def test_load_skill_files_virtual_paths():
    skills_loader._scan_builtin_skill_files.cache_clear()
    files = skills_loader.load_skill_files()

    assert len(files) == len(MAIN_SKILLS) + len(RESEARCHER_SKILLS)
    for vpath, file_data in files.items():
        assert vpath.startswith("/main/") or vpath.startswith("/researcher/")
        assert vpath.endswith("SKILL.md")
        assert "content" in file_data and "name:" in file_data["content"]


def test_load_skill_files_matches_disk_content():
    skills_loader._scan_builtin_skill_files.cache_clear()
    files = skills_loader.load_skill_files()
    on_disk = (skills_loader.SKILLS_ROOT / "main" / "trip-comparison" / "SKILL.md").read_text(encoding="utf-8")
    assert files["/main/trip-comparison/SKILL.md"]["content"] == on_disk


def test_load_skill_files_missing_dir(monkeypatch, tmp_path):
    skills_loader._scan_builtin_skill_files.cache_clear()
    monkeypatch.setattr(skills_loader, "SKILLS_ROOT", tmp_path / "does-not-exist")
    try:
        assert skills_loader.load_skill_files() == {}
    finally:
        skills_loader._scan_builtin_skill_files.cache_clear()  # 别让空结果污染后续用例的缓存


def test_load_skill_files_merges_user_skills(monkeypatch):
    """传 user_id 时并入该用户私有技能（Phase 27），命名空间 /user/ 与内置技能不冲突。"""
    skills_loader._scan_builtin_skill_files.cache_clear()
    monkeypatch.setattr(
        skills_loader, "_load_user_skill_files",
        lambda user_id: {"/user/my-habit/SKILL.md": "---\nname: my-habit\ndescription: d\n---\nbody"},
    )
    files = skills_loader.load_skill_files(user_id="u1")
    assert "/user/my-habit/SKILL.md" in files
    assert len(files) == len(MAIN_SKILLS) + len(RESEARCHER_SKILLS) + 1


def test_load_skill_files_no_user_id_skips_user_query(monkeypatch):
    called = []
    monkeypatch.setattr(skills_loader, "_load_user_skill_files", lambda user_id: called.append(user_id) or {})
    skills_loader.load_skill_files()
    assert called == []


# ---------- _build_agent：主/子 agent 都挂上各自的 skills 路径 ----------

def test_build_agent_wires_skills(monkeypatch):
    captured = {}

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return "fake-agent"

    class FakeChatDeepSeek:
        _llm_type = "deepseek-chat"  # SummarizationMiddleware（Phase 33）构造时读取

        def __init__(self, **kw):
            pass

    monkeypatch.setattr("deepagents.create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr("langchain_deepseek.ChatDeepSeek", FakeChatDeepSeek)

    agent = _build_agent("c1", "u1", session=object(), sources=[], user_skills=True)

    assert agent == "fake-agent"
    assert captured["skills"] == ["/main/", "/user/"]
    subagents = captured["subagents"]
    assert len(subagents) == 2
    by_name = {s["name"]: s for s in subagents}
    assert by_name["api-researcher"]["skills"] == ["/researcher/"]
    # 显式覆盖 deepagents 自动挂的 general-purpose：同名会替换掉默认版本（不会重复出现两个），
    # 拿到主 agent 同款工具/技能，但用我们自己写的、带资源纪律的 prompt（否则它会绕开
    # "浏览器只在主 agent 谨慎用"这条约束——见 GENERAL_PURPOSE_PROMPT 注释）
    assert by_name["general-purpose"]["skills"] == ["/main/", "/user/"]
    assert by_name["general-purpose"]["tools"] == captured["tools"]
    assert "浏览器" in by_name["general-purpose"]["system_prompt"]


def test_build_agent_omits_user_skills_when_none(monkeypatch):
    """用户没上传过技能：skills 不含 /user/，消除 deepagents 每轮
    "Cannot load skills from '/user/': path_not_found" 告警（Phase 27d，线上刷屏）。
    """
    captured = {}
    monkeypatch.setattr("deepagents.create_deep_agent", lambda **kw: captured.update(kw) or "fake-agent")
    monkeypatch.setattr("langchain_deepseek.ChatDeepSeek",
                    lambda **kw: type("M", (), {"_llm_type": "deepseek-chat"})())

    _build_agent("c1", "u1", session=object(), sources=[], user_skills=False)

    assert captured["skills"] == ["/main/"]
    by_name = {s["name"]: s for s in captured["subagents"]}
    assert by_name["general-purpose"]["skills"] == ["/main/"]
    assert by_name["api-researcher"]["skills"] == ["/researcher/"]  # 内置，不受影响


def test_build_agent_sandbox_note_only_when_backend(monkeypatch):
    """沙箱开启（backend 非 None）时，主 agent 与 general-purpose 的 prompt 追加
    /workspace 路径映射说明（Phase 27d 死循环踩坑的双保险）；未开启时不追加。
    """
    captured = {}
    monkeypatch.setattr("deepagents.create_deep_agent", lambda **kw: captured.update(kw) or "fake-agent")
    monkeypatch.setattr("langchain_deepseek.ChatDeepSeek",
                    lambda **kw: type("M", (), {"_llm_type": "deepseek-chat"})())

    _build_agent("c1", "u1", session=object(), sources=[], backend=None)
    assert "/workspace" not in captured["system_prompt"]

    _build_agent("c1", "u1", session=object(), sources=[], backend=object())
    by_name = {s["name"]: s for s in captured["subagents"]}
    assert "/workspace" in captured["system_prompt"]
    assert "同一个目录" in captured["system_prompt"]
    assert "/workspace" in by_name["general-purpose"]["system_prompt"]
    assert "/workspace" not in by_name["api-researcher"]["system_prompt"]  # 纯 API 子代理不需要


# ---------- _invoke_with_cancel：agent.ainvoke 的 payload 带上技能种子 ----------

def test_invoke_with_cancel_seeds_skill_files(monkeypatch):
    """agent.ainvoke 只要没有真实 I/O 就会在 _invoke_with_cancel 的第一次
    `await asyncio.sleep(1)` 后被判定为 done——这里接受这 1s 真实等待，
    不去 monkeypatch 全局 asyncio.sleep（会连累 asyncio 自身的调度/超时机制）。
    """
    from app.agent.deep_research import _invoke_with_cancel

    monkeypatch.setattr("app.observability.langchain_handler", lambda: None)
    monkeypatch.setattr("app.agent.skills_loader._load_user_skill_files", lambda user_id: {})

    captured = {}

    class FakeAgent:
        async def ainvoke(self, payload, config=None):
            captured.update(payload)
            return {"messages": []}

    result = asyncio.run(asyncio.wait_for(
        _invoke_with_cancel("c1", FakeAgent(), "厦门和青岛哪个更适合亲子", "u1"), timeout=10,
    ))

    assert result == {"messages": []}
    assert "files" in captured
    assert "/main/trip-comparison/SKILL.md" in captured["files"]
    assert "/researcher/amap-data-lookup/SKILL.md" in captured["files"]


# ---------- _extract_skills_used：从 read_file 工具调用提炼本轮读过的技能 ----------

def test_extract_skills_used_from_tool_calls():
    from app.agent.deep_research import _extract_skills_used

    class _AI:
        def __init__(self, tool_calls):
            self.tool_calls = tool_calls

    result = {"messages": [
        _AI([{"name": "read_file", "args": {"file_path": "/main/trip-comparison/SKILL.md"}}]),
        _AI([{"name": "write_todos", "args": {}}]),
        _AI([{"name": "read_file", "args": {"file_path": "/user/my-habit/SKILL.md"}}]),
        _AI([{"name": "read_file", "args": {"file_path": "/main/trip-comparison/SKILL.md"}}]),  # 去重
    ]}
    assert _extract_skills_used(result) == ["trip-comparison", "my-habit"]


def test_extract_skills_used_empty_when_no_tool_calls():
    from app.agent.deep_research import _extract_skills_used

    assert _extract_skills_used({"messages": []}) == []
    assert _extract_skills_used(None) == []
