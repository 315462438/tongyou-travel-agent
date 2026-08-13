"""Phase 27b Docker 沙箱 backend 单测：execute() 的安全参数、超时杀容器、文件操作隔离范围。

全部 mock `subprocess.run`（不需要真实 docker），验证的是我们自己写的适配层行为。
"""

import subprocess

import pytest

from app.tools.docker_sandbox import DockerSandboxBackend


class FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_execute_success(monkeypatch, tmp_path):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return FakeCompletedProcess(stdout="hello\n", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    backend = DockerSandboxBackend(str(tmp_path))
    resp = backend.execute("echo hello")

    assert resp.output == "hello\n"
    assert resp.exit_code == 0
    assert captured["kwargs"]["timeout"] > 0


def test_execute_hardens_container(monkeypatch, tmp_path):
    """核心安全参数必须都在：无网络、只读根文件系统、非 root、丢弃全部 capability、
    限进程数、内存/CPU 封顶，且把 workdir 挂进去。
    """
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return FakeCompletedProcess()

    monkeypatch.setattr(subprocess, "run", fake_run)
    backend = DockerSandboxBackend(str(tmp_path))
    backend.execute("true")

    argv = captured["argv"]
    assert "--rm" in argv
    assert "none" in argv  # --network none
    assert "--read-only" in argv
    assert "ALL" in argv  # --cap-drop ALL
    assert "nobody" in argv  # --user nobody
    assert "no-new-privileges" in argv
    assert f"{tmp_path}:/workspace:rw" in argv


def test_execute_nonzero_exit_does_not_raise(monkeypatch, tmp_path):
    def fake_run(argv, **kwargs):
        return FakeCompletedProcess(stdout="", stderr="boom", returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    backend = DockerSandboxBackend(str(tmp_path))
    resp = backend.execute("false")

    assert resp.exit_code == 1
    assert "boom" in resp.output


def test_execute_timeout_kills_container(monkeypatch, tmp_path):
    """docker run 客户端进程被杀不等于容器被杀——超时必须显式 docker kill，否则孤儿容器
    会在后台继续跑（踩坑）。
    """
    killed = []

    def fake_run(argv, **kwargs):
        if argv[:2] == ["docker", "kill"]:
            killed.append(argv[2])
            return FakeCompletedProcess()
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout", 0))

    monkeypatch.setattr(subprocess, "run", fake_run)
    backend = DockerSandboxBackend(str(tmp_path))
    resp = backend.execute("sleep 999", timeout=5)

    assert resp.exit_code == 124
    assert "超时" in resp.output
    assert len(killed) == 1  # 确认真的调用了 docker kill 对应的容器名


def test_execute_docker_not_installed(monkeypatch, tmp_path):
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("docker not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    backend = DockerSandboxBackend(str(tmp_path))
    resp = backend.execute("echo hi")

    assert resp.exit_code == 127
    assert "docker" in resp.output


def test_file_ops_confined_to_root_dir(tmp_path):
    """virtual_mode=True：文件操作必须被限定在传入的临时目录内，不能逃逸到真实主机文件系统
    （FilesystemBackend 默认 virtual_mode=False 会让绝对路径绕过 root_dir 的坑，见踩坑记录）。
    """
    backend = DockerSandboxBackend(str(tmp_path))
    backend.write("/note.txt", "hello")
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "hello"

    result = backend.read("/note.txt")
    assert result.file_data["content"] == "hello"

    # virtual_mode=True: 路径逃逸直接拒绝（FilesystemBackend 自己的安全检查），
    # 不是静默返回空——这正是我们要的效果，确认没有踩上 virtual_mode 默认值的坑。
    with pytest.raises(ValueError, match="traversal"):
        backend.ls("/../../../etc")


# ---------- /workspace 挂载点别名（Phase 27d，修死循环踩坑） ----------
# 文件工具的虚拟根 `/` 和 execute() 容器里的 `/workspace` 是同一目录；不做别名时
# write_file("/workspace/x") 落在 host root/workspace/x（容器 /workspace/workspace/x），
# execute 找不到、glob 又说存在，agent 死循环烧光步数。见对应踩坑文档。

def test_workspace_prefix_aliases_to_root(tmp_path):
    backend = DockerSandboxBackend(str(tmp_path))
    backend.write("/workspace/slides/gen.py", "print('hi')")

    # host 上落在根下，不产生多余的 workspace/ 一层 —— 容器里就是 /workspace/slides/gen.py
    assert (tmp_path / "slides" / "gen.py").read_text(encoding="utf-8") == "print('hi')"
    assert not (tmp_path / "workspace").exists()

    # 两种写法读到同一个文件
    assert backend.read("/workspace/slides/gen.py").file_data["content"] == "print('hi')"
    assert backend.read("/slides/gen.py").file_data["content"] == "print('hi')"


def test_workspace_bare_path_is_root(tmp_path):
    backend = DockerSandboxBackend(str(tmp_path))
    backend.write("/note.txt", "x")
    res = backend.ls("/workspace")
    assert res.error is None
    assert "/note.txt" in {e["path"] for e in res.entries}


def test_workspace_strips_only_one_prefix_level(tmp_path):
    """真实存在名为 workspace 的子目录时不受影响：/workspace/workspace/x → host root/workspace/x。"""
    backend = DockerSandboxBackend(str(tmp_path))
    backend.write("/workspace/workspace/a.txt", "nested")
    assert (tmp_path / "workspace" / "a.txt").read_text(encoding="utf-8") == "nested"


def test_workspace_like_names_not_aliased(tmp_path):
    """只别名整段 /workspace，前缀相似的目录名（/workspace2）不受影响。"""
    backend = DockerSandboxBackend(str(tmp_path))
    backend.write("/workspace2/b.txt", "keep")
    assert (tmp_path / "workspace2" / "b.txt").read_text(encoding="utf-8") == "keep"


def test_workspace_alias_still_blocks_traversal(tmp_path):
    backend = DockerSandboxBackend(str(tmp_path))
    with pytest.raises(ValueError, match="traversal"):
        backend.ls("/workspace/../../etc")


# ---------- _build_backend / run_deep_research 装配（Phase 27b/27c） ----------

def test_build_backend_none_when_server_disabled(monkeypatch):
    from app.agent.deep_research import _build_backend
    from app.config import settings

    monkeypatch.setattr(settings, "docker_sandbox_enabled", False)
    backend, tmp_dir, seed_paths = _build_backend("u1", True)
    assert backend is None
    assert tmp_dir is None
    assert seed_paths == set()


def test_build_backend_none_when_per_message_toggle_off(monkeypatch):
    """服务器开着，但这一轮用户没打开「沙箱执行」开关——不生效（Phase 27c）。"""
    from app.agent.deep_research import _build_backend
    from app.config import settings

    monkeypatch.setattr(settings, "docker_sandbox_enabled", True)
    backend, tmp_dir, seed_paths = _build_backend("u1", False)
    assert backend is None
    assert tmp_dir is None


def test_build_backend_writes_skill_files_when_both_enabled(monkeypatch):
    """不再用 CompositeBackend 包一层共享 StateBackend——那样会导致 glob/ls 聚合时
    对路径二次拼前缀，产生 /main/main/xxx/SKILL.md 这种错乱路径（实测踩到，见踩坑文档）。
    改成技能直接物理写进沙箱自己的临时目录，backend 本身就是纯 DockerSandboxBackend。
    """
    import os

    from app.agent.deep_research import _build_backend
    from app.config import settings
    from app.tools.docker_sandbox import DockerSandboxBackend

    monkeypatch.setattr(settings, "docker_sandbox_enabled", True)
    backend, tmp_dir, seed_paths = _build_backend("u1", True)
    try:
        assert isinstance(backend, DockerSandboxBackend)
        assert tmp_dir is not None and os.path.isdir(tmp_dir)
        assert oct(os.stat(tmp_dir).st_mode)[-3:] == "777"
        # 技能被物理写进去了，且没有二次拼前缀（不是 /main/main/...）
        assert os.path.isfile(os.path.join(tmp_dir, "main", "trip-comparison", "SKILL.md"))
        assert os.path.isfile(os.path.join(tmp_dir, "researcher", "amap-data-lookup", "SKILL.md"))
        assert not os.path.isdir(os.path.join(tmp_dir, "main", "main"))
        assert "main/trip-comparison/SKILL.md" in seed_paths
    finally:
        import shutil

        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def test_build_backend_includes_user_skill(monkeypatch):
    from app.agent.deep_research import _build_backend
    from app.agent import skills_loader
    from app.config import settings

    monkeypatch.setattr(settings, "docker_sandbox_enabled", True)
    monkeypatch.setattr(
        skills_loader, "_load_user_skill_files",
        lambda user_id: {"/user/my-habit/SKILL.md": "---\nname: my-habit\ndescription: d\n---\nbody"},
    )
    backend, tmp_dir, seed_paths = _build_backend("u1", True)
    try:
        with open(f"{tmp_dir}/user/my-habit/SKILL.md", encoding="utf-8") as f:
            assert "my-habit" in f.read()
    finally:
        import shutil

        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def test_run_deep_research_cleans_up_sandbox_tempdir(monkeypatch):
    """轮末必须删掉临时目录，不能在磁盘上累积。"""
    import os

    from app.agent import deep_research
    from app.config import settings

    monkeypatch.setattr(settings, "docker_sandbox_enabled", True)
    monkeypatch.setattr(settings, "deep_research_timeout_s", 5)
    monkeypatch.setattr(settings, "deep_research_stream", False)  # 本例测临时目录清理，走非流式

    created_tmp_dirs = []
    real_build_backend = deep_research._build_backend

    def spy_build_backend(user_id, sandbox_enabled):
        backend, tmp_dir, seed_paths = real_build_backend(user_id, sandbox_enabled)
        created_tmp_dirs.append(tmp_dir)
        return backend, tmp_dir, seed_paths

    monkeypatch.setattr(deep_research, "_build_backend", spy_build_backend)
    monkeypatch.setattr(deep_research, "_build_agent", lambda *a, **kw: "fake-agent")

    class _AI:
        type = "ai"
        content = "最终报告"

    async def fake_invoke_with_cancel(cid, agent, user_text, user_id, skill_files=None, turn_messages=None, stream_msg_id=None, stream_state=None):
        return {"messages": [_AI()]}

    monkeypatch.setattr(deep_research, "_invoke_with_cancel", fake_invoke_with_cancel)

    class FakeBrowserSession:
        def __init__(self, cid, user_id):
            pass

        async def close(self):
            pass

    monkeypatch.setattr("app.agent.research_tools.BrowserSession", FakeBrowserSession)
    monkeypatch.setattr("app.agent.orchestrator._add_message", lambda *a, **kw: None)
    monkeypatch.setattr("app.agent.orchestrator._progress", lambda *a, **kw: None)
    monkeypatch.setattr("app.agent.orchestrator.clear_plain_progress", lambda *a, **kw: None)

    import asyncio

    asyncio.run(deep_research.run_deep_research("c1", "对比一下厦门和青岛", "u1", sandbox_enabled=True))

    assert len(created_tmp_dirs) == 1
    assert created_tmp_dirs[0] is not None
    assert not os.path.exists(created_tmp_dirs[0])  # 清理干净了


# ---------- _collect_sandbox_artifacts：产物 diff / 存储 / 懒清理（Phase 27c） ----------

def test_collect_sandbox_artifacts_skips_seed_files(tmp_path, monkeypatch):
    from app.agent.deep_research import _collect_sandbox_artifacts
    from app.config import settings

    monkeypatch.setattr(settings, "sandbox_artifacts_dir", str(tmp_path / "artifacts"))
    sandbox = tmp_path / "sandbox"
    (sandbox / "main" / "trip-comparison").mkdir(parents=True)
    (sandbox / "main" / "trip-comparison" / "SKILL.md").write_text("skill content")
    (sandbox / "output.pptx").write_bytes(b"fake pptx bytes")

    artifacts = _collect_sandbox_artifacts(str(sandbox), {"main/trip-comparison/SKILL.md"})

    assert len(artifacts) == 1
    assert artifacts[0]["name"] == "output.pptx"
    assert artifacts[0]["size"] == len(b"fake pptx bytes")
    assert artifacts[0]["url"].startswith("/sandbox-artifacts/")


def test_collect_sandbox_artifacts_empty_when_nothing_new(tmp_path, monkeypatch):
    from app.agent.deep_research import _collect_sandbox_artifacts
    from app.config import settings

    monkeypatch.setattr(settings, "sandbox_artifacts_dir", str(tmp_path / "artifacts"))
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "SKILL.md").write_text("x")

    assert _collect_sandbox_artifacts(str(sandbox), {"SKILL.md"}) == []


def test_collect_sandbox_artifacts_caps_file_count(tmp_path, monkeypatch):
    import app.agent.deep_research as deep_research
    from app.agent.deep_research import _collect_sandbox_artifacts
    from app.config import settings

    monkeypatch.setattr(settings, "sandbox_artifacts_dir", str(tmp_path / "artifacts"))
    monkeypatch.setattr(deep_research, "_ARTIFACT_MAX_FILES", 2)
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    for i in range(5):
        (sandbox / f"file{i}.txt").write_text("x")

    artifacts = _collect_sandbox_artifacts(str(sandbox), set())
    assert len(artifacts) == 2


def test_cleanup_expired_artifacts_removes_old_dirs(tmp_path, monkeypatch):
    import os
    import time

    from app.agent.deep_research import _cleanup_expired_artifacts
    from app.config import settings

    root = tmp_path / "artifacts"
    old_dir = root / "old-batch"
    old_dir.mkdir(parents=True)
    (old_dir / "f.txt").write_text("x")
    monkeypatch.setattr(settings, "sandbox_artifacts_dir", str(root))
    monkeypatch.setattr(settings, "sandbox_artifacts_ttl_min", 30)

    old_time = time.time() - 31 * 60
    os.utime(old_dir, (old_time, old_time))

    _cleanup_expired_artifacts()
    assert not old_dir.exists()


def test_cleanup_expired_artifacts_keeps_recent_dirs(tmp_path, monkeypatch):
    from app.agent.deep_research import _cleanup_expired_artifacts
    from app.config import settings

    root = tmp_path / "artifacts"
    recent_dir = root / "recent-batch"
    recent_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "sandbox_artifacts_dir", str(root))
    monkeypatch.setattr(settings, "sandbox_artifacts_ttl_min", 30)

    _cleanup_expired_artifacts()
    assert recent_dir.exists()


# ---------- run_conversation_turn → run_deep_research：sandbox_enabled 穿透（Phase 27c） ----------

def test_run_conversation_turn_threads_sandbox_enabled(monkeypatch):
    from app.agent import orchestrator

    # run_conversation_turn 内部是 `from app.agent.deep_research import resolve_route,
    # run_deep_research`（函数体里现取），必须 patch 源头模块的属性，patch
    # orchestrator 模块本身的同名属性不会生效。
    monkeypatch.setattr("app.agent.deep_research.resolve_route", lambda text, llm, deep_reasoning: ("research", False))
    monkeypatch.setattr(orchestrator, "_mark_inflight", lambda *a, **kw: None)

    captured = {}

    async def fake_run_deep_research(cid, user_text, user_id, sandbox_enabled=False):
        captured["sandbox_enabled"] = sandbox_enabled

    monkeypatch.setattr("app.agent.deep_research.run_deep_research", fake_run_deep_research)
    monkeypatch.setattr("app.llm.client.get_llm", lambda: object())

    orchestrator.run_conversation_turn("c1", "对比一下厦门和青岛", "u1", sandbox_enabled=True)
    assert captured["sandbox_enabled"] is True

    orchestrator.run_conversation_turn("c1", "对比一下厦门和青岛", "u1", sandbox_enabled=False)
    assert captured["sandbox_enabled"] is False
