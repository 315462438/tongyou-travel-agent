"""深度研究模式（Phase 21）单测：路由判定、SSRF 防护、正文抽取、答案提取。全离线。"""

import pytest

from app.agent.deep_research import _dedupe, _extract_answer, decide_route
from app.agent.research_tools import _html_to_text, _is_private_host
from app.config import settings


class FakeLLM:
    def __init__(self, kind):
        self.kind = kind
        self.called = False

    def classify(self, prompt, schema, system=None):
        self.called = True
        return schema(kind=self.kind)


# ---------- 三路路由判定（Phase 22） ----------

def test_route_research_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "deep_research_enabled", True)
    assert decide_route("厦门和青岛对比一下哪个适合亲子", FakeLLM("research")) == "research"


def test_route_research_disabled_downgrades_to_guide(monkeypatch):
    monkeypatch.setattr(settings, "deep_research_enabled", False)
    assert decide_route("厦门 vs 青岛哪个更适合", FakeLLM("research")) == "research"  # Phase 44：纯分类，门控上移


def test_route_direct_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "direct_answer_enabled", True)
    assert decide_route("鼓浪屿要提前订票吗", FakeLLM("direct")) == "direct"


def test_route_direct_disabled_downgrades_to_guide(monkeypatch):
    monkeypatch.setattr(settings, "direct_answer_enabled", False)
    assert decide_route("鼓浪屿要提前订票吗", FakeLLM("direct")) == "direct"  # Phase 44：纯分类


def test_route_guide_default(monkeypatch):
    monkeypatch.setattr(settings, "direct_answer_enabled", True)
    assert decide_route("帮我规划成都3天路线", FakeLLM("guide")) == "guide"
    assert decide_route("帮我做个攻略", FakeLLM("怪答案")) == "guide"  # 未知 kind → guide
    assert decide_route("", FakeLLM("direct")) == "guide"  # 空消息


def test_route_classify_failure_falls_back_to_guide():
    class Boom:
        def classify(self, *a, **k):
            raise RuntimeError("llm down")

    assert decide_route("对比一下东京和大阪", Boom()) == "guide"


# ---------- fetch_url SSRF 防护 ----------

@pytest.mark.parametrize("host,expected", [
    ("localhost", True),
    ("127.0.0.1", True),
    ("::1", True),
    ("10.0.0.8", True),
    ("192.168.1.1", True),
    ("172.16.0.1", True),
    ("8.8.8.8", False),  # 公网 IP 放行
    ("www.example.com", False),  # 域名放行
])
def test_private_host_guard(host, expected):
    assert _is_private_host(host) is expected


# ---------- 正文抽取 ----------

def test_html_to_text_strips_noise():
    html = "<html><head><style>.a{color:red}</style><script>alert(1)</script></head>" \
           "<body><h1>东京签证</h1><p>需要 <b>护照</b> 与照片。</p></body></html>"
    text = _html_to_text(html)
    assert "东京签证" in text and "护照" in text
    assert "alert" not in text and "color" not in text


def test_html_to_text_limit():
    assert len(_html_to_text("<p>" + "字" * 9000 + "</p>", limit=100)) == 100


# ---------- 答案提取 / 来源去重 ----------

class _Msg:
    def __init__(self, type_, content):
        self.type = type_
        self.content = content


def test_extract_answer_last_ai():
    result = {"messages": [
        _Msg("human", "问题"),
        _Msg("ai", "中间思考"),
        _Msg("tool", "工具结果"),
        _Msg("ai", "最终报告"),
    ]}
    assert _extract_answer(result) == "最终报告"


def test_extract_answer_content_blocks():
    result = {"messages": [_Msg("ai", [{"type": "text", "text": "分段"}, {"type": "text", "text": "内容"}])]}
    assert _extract_answer(result) == "分段内容"


def test_extract_answer_empty():
    assert _extract_answer({"messages": []}) == ""
    assert _extract_answer(None) == ""


def test_dedupe_sources():
    src = [{"title": "a", "url": "u1"}, {"title": "b", "url": "u1"}, {"title": "c", "url": "u2"}]
    out = _dedupe(src)
    assert [s["url"] for s in out] == ["u1", "u2"]


# ---------- BrowserSession actor（MCP 同 task 进出，线上踩坑回归） ----------

import asyncio

from app.agent.research_tools import BrowserSession


def test_browser_session_startup_failure_propagates(monkeypatch):
    """acquire 排队超时等启动失败：调用方拿到异常而不是挂死，槽位不泄漏。"""

    class BoomMCP:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            raise RuntimeError("排队等待浏览器超时")

        async def __aexit__(self, *a):
            pass

    import app.agent.research_tools as rt

    async def scenario():
        s = BrowserSession("c1", "u1")
        monkeypatch.setattr("app.tools.mcp_client.ChromeMCP", BoomMCP)
        with pytest.raises(RuntimeError, match="排队"):
            await asyncio.wait_for(s.call("search_web", "x"), timeout=5)
        await s.close()  # 幂等，不抛

    asyncio.run(scenario())


def test_browser_session_single_task_lifecycle(monkeypatch):
    """请求从不同 task 提交，MCP 进入/退出都发生在 worker 自己 task 里。"""
    events = []

    class FakeMCP:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            events.append(("enter", asyncio.current_task().get_name()))
            return self

        async def __aexit__(self, *a):
            events.append(("exit", asyncio.current_task().get_name()))

    class FakeBrowser:
        def __init__(self, chrome=None):
            pass

        async def search_web(self, q, top_n=5):
            events.append(("call", asyncio.current_task().get_name()))
            return [{"title": q, "url": "http://e.com"}]

    monkeypatch.setattr("app.tools.mcp_client.ChromeMCP", FakeMCP)
    monkeypatch.setattr("app.tools.browser_tool.BrowserTool", FakeBrowser)

    async def scenario():
        s = BrowserSession("c1", "u1")

        async def from_other_task():
            return await s.call("search_web", "厦门")

        r1 = await asyncio.create_task(from_other_task(), name="tool-a")
        r2 = await asyncio.create_task(from_other_task(), name="tool-b")
        await s.close()
        assert r1[0]["title"] == "厦门" and r2[0]["title"] == "厦门"

    asyncio.run(scenario())
    # enter/call/exit 全部在同一个 worker task 里
    tasks = {t for _, t in events}
    assert len(tasks) == 1, f"MCP 生命周期跨了多个 task: {events}"
    assert [e for e, _ in events] == ["enter", "call", "call", "exit"]


# ---------- resolve_route（Phase 23 深度推理开关） ----------

from app.agent.deep_research import resolve_route


def test_resolve_toggle_on_routes_by_kind(monkeypatch):
    """Phase 44：开关开 = 慢思考，但仍分类——闲聊秒回、规划走 guide、开放题走 research。"""
    monkeypatch.setattr(settings, "deep_research_enabled", True)
    assert resolve_route("谢谢", FakeLLM("direct"), deep_reasoning=True) == ("direct", False)
    assert resolve_route("规划成都3天", FakeLLM("guide"), deep_reasoning=True) == ("guide", False)
    assert resolve_route("厦门vs青岛", FakeLLM("research"), deep_reasoning=True) == ("research", False)


def test_resolve_toggle_on_but_server_disabled(monkeypatch):
    monkeypatch.setattr(settings, "deep_research_enabled", False)
    route, suggest = resolve_route("对比一下", FakeLLM("research"), deep_reasoning=True)
    assert route == "guide" and suggest is False  # research 未启用退 guide（仍是慢思考）


def test_resolve_toggle_off_is_fast_thinking(monkeypatch):
    """Phase 54：普通规划始终走 guide；只有开放研究题在开关关闭时降级并提示。"""
    monkeypatch.setattr(settings, "deep_research_enabled", True)
    monkeypatch.setattr(settings, "direct_answer_enabled", True)
    assert resolve_route("厦门vs青岛哪个划算", FakeLLM("research")) == ("direct", True)
    assert resolve_route("规划成都3天", FakeLLM("guide")) == ("guide", False)
    assert resolve_route("鼓浪屿要订票吗", FakeLLM("direct")) == ("direct", False)
    monkeypatch.setattr(settings, "direct_answer_enabled", False)
    route, suggest = resolve_route("厦门vs青岛哪个划算", FakeLLM("research"), deep_reasoning=False)
    assert route == "guide" and suggest is True  # direct 被禁：退回 guide 兜底


def test_resolve_toggle_off_chitchat_no_hint(monkeypatch):
    monkeypatch.setattr(settings, "direct_answer_enabled", True)
    assert resolve_route("鼓浪屿要订票吗", FakeLLM("direct")) == ("direct", False)


def test_explicit_itinerary_overrides_classifier_direct(monkeypatch):
    """真实回归：完整路线/酒店/预算需求不能因分类模型抖动进入快速回答。"""
    monkeypatch.setattr(settings, "direct_answer_enabled", True)
    text = "规划武汉到拉萨15天的轻松行程，包括路线、酒店和预算安排"
    assert resolve_route(text, FakeLLM("direct")) == ("guide", False)


def test_subagent_tracker_survives_langchain_callback_manager():
    """2026-08-14 线上崩：langchain-core ≥1.4 的回调管理器对每个 handler 无条件读
    ignore_chain/raise_error 等属性，SubagentTracker（鸭子类型不继承基类）缺属性 →
    AttributeError 冒泡炸掉 agent.astream，深度研究每次必败。钉住真实管理器触发不抛。"""
    from langchain_core.callbacks import CallbackManager

    from app.agent.subagent_trace import SubagentTracker

    tracker = SubagentTracker("cid")
    manager = CallbackManager(handlers=[tracker])
    manager.on_chain_start(serialized={}, inputs={}, run_id=None)
    manager.on_llm_start(serialized={}, prompts=[], run_id=None)
    manager.on_tool_start(serialized={"name": "task"}, input_str="", run_id=None)
    # 属性契约：与 BaseCallbackHandler 默认一致（False = 不忽略任何事件、回调异常不传播）
    for attr in ("raise_error", "ignore_chain", "ignore_agent", "ignore_llm",
                 "ignore_tool", "ignore_chat_model", "ignore_retriever",
                 "ignore_parser", "ignore_custom"):
        assert getattr(tracker, attr) is False


def test_subagent_tracker_has_all_callback_methods():
    """2026-08-14 追加：langchain 管理器直接调用 handler 所有事件方法（不做存在性检查），
    缺方法即刷「Error in ... callback」日志。补齐后全部存在且可调用。"""
    from app.agent.subagent_trace import SubagentTracker

    t = SubagentTracker("cid")
    for name in (
        "on_chain_start", "on_chain_end", "on_chain_error", "on_chain_stream",
        "on_llm_start", "on_llm_new_token", "on_llm_end", "on_llm_error",
        "on_chat_model_start", "on_chat_model_stream", "on_chat_model_end",
        "on_chat_model_error",
        "on_tool_start", "on_tool_end", "on_tool_error",
        "on_retriever_start", "on_retriever_end", "on_retriever_error",
        "on_agent_action", "on_agent_finish", "on_custom_event", "on_text",
    ):
        assert callable(getattr(t, name)), f"missing callback {name}"
