"""Phase 28 深度研究工具硬配额单测：prompt 纪律会在长上下文里漂移（线上一轮搜 5 次、
读 18 个来源烧光 600s 超时作废），工具层必须强制封顶。全离线。"""

import asyncio

import pytest

from app.agent import research_tools
from app.config import settings


class FakeSession:
    """记录调用次数的假浏览器会话。"""

    def __init__(self):
        self.calls = []

    async def call(self, method, *args, **kwargs):
        self.calls.append(method)
        if method == "search_web":
            return [{"title": "t", "url": "http://example.com"}]

        class _Page:
            status = "ok"
            reason = None
            text = "page text"

        return _Page()


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setattr("app.agent.orchestrator._progress", lambda *a, **kw: None)
    session = FakeSession()
    main_tools, sub_tools = research_tools.build_tools("c1", "u1", session, sources=[])
    by_name = {t.__name__: t for t in main_tools + sub_tools}
    return session, by_name


def test_web_search_quota_enforced(tools, monkeypatch):
    monkeypatch.setattr(settings, "deep_research_max_searches", 3)
    session, by_name = tools

    async def run():
        for _ in range(3):
            out = await by_name["web_search"]("商丘 攻略")
            assert "example.com" in out
        return await by_name["web_search"]("第四次")

    over = asyncio.run(run())
    assert "配额已用完" in over
    assert session.calls.count("search_web") == 3  # 第 4 次没有触发真实搜索


def test_open_page_quota_enforced(tools, monkeypatch):
    monkeypatch.setattr(settings, "deep_research_max_open_pages", 2)
    session, by_name = tools

    async def run():
        for _ in range(2):
            assert "page text" in await by_name["open_page"]("http://example.com")
        return await by_name["open_page"]("http://example.com/3")

    over = asyncio.run(run())
    assert "配额已用完" in over
    assert session.calls.count("open_page") == 2


def test_fetch_url_quota_enforced(tools, monkeypatch):
    """超限的 fetch_url 直接返回引导文案，不发起任何 HTTP 请求。"""
    monkeypatch.setattr(settings, "deep_research_max_fetches", 0)

    def boom(*a, **kw):
        raise AssertionError("不应发起 HTTP 请求")

    monkeypatch.setattr(research_tools.httpx, "AsyncClient", boom)
    _session, by_name = tools

    over = asyncio.run(by_name["fetch_url"]("http://example.com"))
    assert "配额已用完" in over


def test_quota_shared_across_tools_of_one_turn(tools, monkeypatch):
    """主 agent 与 subagent 共用同一批闭包——配额是全轮共享的一份计数。"""
    monkeypatch.setattr(settings, "deep_research_max_searches", 1)
    session, by_name = tools

    async def run():
        await by_name["web_search"]("q1")
        return await by_name["web_search"]("q2")

    assert "配额已用完" in asyncio.run(run())
    assert session.calls.count("search_web") == 1


def test_new_turn_resets_quota(monkeypatch):
    """配额按轮计：新一轮 build_tools 重新记账。"""
    monkeypatch.setattr("app.agent.orchestrator._progress", lambda *a, **kw: None)
    monkeypatch.setattr(settings, "deep_research_max_searches", 1)

    async def run_turn():
        session = FakeSession()
        main_tools, _ = research_tools.build_tools("c1", "u1", session, sources=[])
        ws = {t.__name__: t for t in main_tools}["web_search"]
        return await ws("q")

    assert "example.com" in asyncio.run(run_turn())
    assert "example.com" in asyncio.run(run_turn())  # 第二轮不受第一轮计数影响


def test_open_page_counts_as_source(monkeypatch):
    """浏览器读成功的页面必须计入 sources（此前只有 fetch_url/高德计入，来源卡少列）。"""
    monkeypatch.setattr("app.agent.orchestrator._progress", lambda *a, **kw: None)
    monkeypatch.setattr(settings, "deep_research_max_open_pages", 3)

    class RichPageSession(FakeSession):
        async def call(self, method, *args, **kwargs):
            self.calls.append(method)

            class _Page:
                status = "ok"
                reason = None
                text = "商丘古城正文" * 30  # 超过 120 字符的有效正文

            return _Page()

    sources: list = []
    main_tools, _ = research_tools.build_tools("c1", "u1", RichPageSession(), sources=sources)
    op = {t.__name__: t for t in main_tools}["open_page"]

    asyncio.run(op("https://zhuanlan.zhihu.com/p/123"))
    assert sources == [{"title": "zhuanlan.zhihu.com", "url": "https://zhuanlan.zhihu.com/p/123"}]


def test_invoke_heartbeat_progress(monkeypatch):
    """长时间无工具活动时按间隔写心跳 progress（Phase 28：不再像卡死）。"""
    from app.agent import deep_research

    monkeypatch.setattr(deep_research, "HEARTBEAT_EVERY_S", 2)
    monkeypatch.setattr("app.observability.langchain_handler", lambda: None)
    monkeypatch.setattr("app.agent.skills_loader._load_user_skill_files", lambda user_id: {})
    beats = []
    monkeypatch.setattr("app.agent.orchestrator._progress", lambda cid, text, meta=None: beats.append(text))

    class SlowAgent:
        async def ainvoke(self, payload, config=None):
            await asyncio.sleep(3.2)  # 撑过一次心跳间隔（2s）
            return {"messages": []}

    asyncio.run(asyncio.wait_for(
        deep_research._invoke_with_cancel("c1", SlowAgent(), "问题", "u1", skill_files={}), timeout=15,
    ))
    assert beats, "应至少写过一次心跳 progress"
    assert "研究进行中" in beats[0]


def test_prompts_carry_time_and_one_shot_discipline():
    """prompt 纪律双保险仍在：时间纪律进 RESEARCH_SYSTEM，一次成稿纪律进 SANDBOX_NOTE。"""
    from app.agent.deep_research import RESEARCH_SYSTEM, SANDBOX_NOTE

    assert "时间纪律" in RESEARCH_SYSTEM
    assert "硬配额" in RESEARCH_SYSTEM
    assert "一次成稿" in SANDBOX_NOTE
    assert "禁止" in SANDBOX_NOTE
