"""Phase 29 上下文与预算治理单测：留存换引用 / read_source 翻页 / 预算 nudge /
ContextEditingMiddleware 装配。全离线。机制借鉴 Claude Code（microcompaction、
toolResultStorage、tokenBudget），实现见 task_plan-phase29-上下文与预算治理.md。
"""

import asyncio

import pytest

from app.agent import research_tools
from app.config import settings


class FakeSession:
    async def call(self, method, *args, **kwargs):
        raise AssertionError("本测试不应触达浏览器")


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setattr("app.agent.orchestrator._progress", lambda *a, **kw: None)
    main_tools, sub_tools = research_tools.build_tools("c1", "u1", FakeSession(), sources=[])
    return {t.__name__: t for t in main_tools + sub_tools}


class _FakeResp:
    status_code = 200

    def __init__(self, text):
        self.text = text


def _fake_httpx(monkeypatch, body: str):
    class _FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, timeout=None):
            return _FakeResp(body)

    monkeypatch.setattr(research_tools.httpx, "AsyncClient", _FakeClient)


# ---------- 留存换引用（A） ----------

def test_fetch_long_page_returns_preview_with_read_source_hint(tools, monkeypatch):
    _fake_httpx(monkeypatch, "<p>" + "商丘古城内容段落。" * 800 + "</p>")

    out = asyncio.run(tools["fetch_url"]("https://example.com/a"))

    assert "[来源 s1" in out
    assert "read_source(\"s1\"" in out
    # 返回的是预览而不是全文
    assert len(out) < settings.deep_research_source_preview_chars + 400


def test_fetch_short_page_returned_verbatim(tools, monkeypatch):
    _fake_httpx(monkeypatch, "<p>" + "短内容。" * 60 + "</p>")

    out = asyncio.run(tools["fetch_url"]("https://example.com/b"))
    assert "[来源" not in out and "read_source" not in out


def test_read_source_pages_through(tools, monkeypatch):
    _fake_httpx(monkeypatch, "<p>" + "商丘古城内容段落。" * 800 + "</p>")
    asyncio.run(tools["fetch_url"]("https://example.com/a"))

    chunk_n = settings.deep_research_read_source_chunk
    page1 = asyncio.run(tools["read_source"]("s1"))
    assert f"第 0-{chunk_n} 字" in page1
    assert f"offset={chunk_n}" in page1  # 带下一页提示

    page2 = asyncio.run(tools["read_source"]("s1", offset=chunk_n))
    assert f"第 {chunk_n}-" in page2

    beyond = asyncio.run(tools["read_source"]("s1", offset=10 ** 7))
    assert "超出末尾" in beyond


def test_read_source_unknown_id_lists_available(tools, monkeypatch):
    _fake_httpx(monkeypatch, "<p>" + "内容。" * 2000 + "</p>")
    asyncio.run(tools["fetch_url"]("https://example.com/a"))

    out = asyncio.run(tools["read_source"]("s99"))
    assert "没有编号为 s99" in out and "s1" in out


def test_read_source_available_to_both_agents(monkeypatch):
    monkeypatch.setattr("app.agent.orchestrator._progress", lambda *a, **kw: None)
    main_tools, sub_tools = research_tools.build_tools("c1", "u1", FakeSession(), sources=[])
    assert "read_source" in {t.__name__ for t in main_tools}
    assert "read_source" in {t.__name__ for t in sub_tools}


# ---------- 预算 nudge（C） ----------

def _rewind_clock(monkeypatch, frac: float):
    """让 _now() 假装已经过去 frac × 预算 的时间。"""
    base = research_tools.time.monotonic()
    elapsed = settings.deep_research_timeout_s * frac
    ticks = iter([base, base + elapsed] + [base + elapsed] * 50)
    monkeypatch.setattr(research_tools, "_now", lambda: next(ticks))


def test_no_budget_note_early(tools, monkeypatch):
    _fake_httpx(monkeypatch, "<p>" + "内容。" * 200 + "</p>")
    out = asyncio.run(tools["fetch_url"]("https://example.com/a"))
    assert "⏳" not in out


def test_budget_note_after_60_percent(monkeypatch):
    monkeypatch.setattr("app.agent.orchestrator._progress", lambda *a, **kw: None)
    _rewind_clock(monkeypatch, 0.65)
    main_tools, sub_tools = research_tools.build_tools("c1", "u1", FakeSession(), sources=[])
    by_name = {t.__name__: t for t in main_tools + sub_tools}
    _fake_httpx(monkeypatch, "<p>" + "内容。" * 200 + "</p>")

    out = asyncio.run(by_name["fetch_url"]("https://example.com/a"))
    assert "⏳ 已用" in out
    assert "❗" not in out  # 60-80% 只报用量，不下强收敛令


def test_urgent_note_after_80_percent(monkeypatch):
    monkeypatch.setattr("app.agent.orchestrator._progress", lambda *a, **kw: None)
    _rewind_clock(monkeypatch, 0.9)
    main_tools, sub_tools = research_tools.build_tools("c1", "u1", FakeSession(), sources=[])
    by_name = {t.__name__: t for t in main_tools + sub_tools}
    _fake_httpx(monkeypatch, "<p>" + "内容。" * 200 + "</p>")

    out = asyncio.run(by_name["fetch_url"]("https://example.com/a"))
    assert "❗预算即将耗尽" in out


# ---------- ContextEditingMiddleware 装配（B）+ 子任务纪律（D） ----------

def test_build_agent_wires_context_trim_middleware(monkeypatch):
    from app.agent.deep_research import _build_agent

    captured = {}
    monkeypatch.setattr("deepagents.create_deep_agent", lambda **kw: captured.update(kw) or "fake-agent")
    monkeypatch.setattr("langchain_deepseek.ChatDeepSeek",
                        lambda **kw: type("M", (), {"_llm_type": "deepseek-chat"})())

    _build_agent("c1", "u1", session=object(), sources=[])

    from langchain.agents.middleware import ContextEditingMiddleware

    assert any(isinstance(m, ContextEditingMiddleware) for m in captured["middleware"])
    by_name = {s["name"]: s for s in captured["subagents"]}
    assert any(isinstance(m, ContextEditingMiddleware) for m in by_name["general-purpose"]["middleware"])
    assert "middleware" not in by_name["api-researcher"]  # 短上下文子任务不清理


def test_trim_middleware_uses_settings(monkeypatch):
    from app.agent.deep_research import _context_trim_middleware

    monkeypatch.setattr(settings, "deep_research_context_trim_tokens", 12345)
    monkeypatch.setattr(settings, "deep_research_context_keep_tools", 7)
    mw = _context_trim_middleware()
    edit = mw.edits[0]
    assert edit.trigger == 12345
    assert edit.keep == 7
    assert "read_source" in edit.placeholder  # 占位符必须可行动


def test_prompt_carries_subagent_discipline():
    from app.agent.deep_research import RESEARCH_SYSTEM

    assert "子任务纪律" in RESEARCH_SYSTEM
    assert "根据你的发现" in RESEARCH_SYSTEM  # 明确点名禁止的甩锅句式


def test_prompt_carries_note_taking_discipline():
    """清理只保 AI message 不保 ToolMessage——模型必须被教会「读完先记要点」，
    否则被清的来源里未转述的事实就真忘了（用户提出的真空档）。"""
    from app.agent.deep_research import RESEARCH_SYSTEM

    assert "记笔记纪律" in RESEARCH_SYSTEM
    assert "记下要点" in RESEARCH_SYSTEM
