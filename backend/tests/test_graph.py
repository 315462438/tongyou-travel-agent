"""LangGraph 攻略图（Phase 14）：路由与反思循环终止。全部离线（打桩节点内部）。"""

import asyncio

import pytest

from app.agent import nodes
from app.agent.graph import _compiled
from app.agent.nodes import route_after_collect, route_after_critique, route_after_parse
from app.config import settings
from app.schemas.chat_schema import Preference


# ---------- 条件边 ----------

def test_route_after_parse():
    assert route_after_parse({"route": "plan"}) == "plan"
    assert route_after_parse({"route": "chat"}) == "end"
    assert route_after_parse({"route": "clarify"}) == "end"


def test_route_after_collect():
    assert route_after_collect({"sources": [{"x": 1}]}) == "generate"
    assert route_after_collect({"sources": []}) == "apologize"


def test_route_after_critique():
    assert route_after_critique({"critique": {"ok": True}}) == "finalize"
    assert route_after_critique(
        {"critique": {"ok": False, "action": "research", "search_queries": ["成都 美食"]}}
    ) == "research"
    assert route_after_critique(
        {"critique": {"ok": False, "action": "rewrite", "issues": ["Day2 绕路"]}}
    ) == "rewrite"
    # research 但没给查询词 → 退化 rewrite
    assert route_after_critique({"critique": {"ok": False, "action": "research"}}) == "rewrite"


def test_long_guide_critique_sees_day_index_and_budget_tail(monkeypatch):
    """长攻略不能因截前 6000 字而误判后半程和预算缺失。"""
    captured = {}

    class FakeCrit:
        def model_dump(self):
            return {"ok": True, "action": "none", "issues": [], "search_queries": []}

    class FakeLLM:
        def parse(self, prompt, *args, **kwargs):
            captured["prompt"] = prompt
            return FakeCrit()

    monkeypatch.setattr(nodes, "get_llm", lambda: FakeLLM())
    monkeypatch.setattr(settings, "reflection_enabled", True)
    guide = "## Day 1\n出发\n" + ("中段内容" * 5000) + "\n## Day 18\n丽江返程\n## 预算估算\n合计 25306 元"
    result = nodes.critique_node({
        "user_text": "规划 18 天行程并给出预算",
        "guide": guide,
        "rounds": 0,
    })
    assert result["critique"]["ok"] is True
    assert "Day 18" in captured["prompt"]
    assert "已识别预算/费用内容：是" in captured["prompt"]
    assert "合计 25306 元" in captured["prompt"]


# ---------- 全图循环终止 ----------

class _Recorder:
    def __init__(self):
        self.gen_calls = 0
        self.finalized = False
        self.research_calls = 0


@pytest.fixture()
def wired(monkeypatch):
    """打桩节点内部：parse→plan，collect 给料，generate 记数，critique 恒判 rewrite。"""
    rec = _Recorder()
    pref = Preference(destination="成都", is_travel_request=True)

    monkeypatch.setattr(nodes.orch, "parse_request",
                        lambda cid, ut, uid: {"route": "plan", "pref": pref, "intent": "route", "hotel_needed": False})
    # 2026-08-13 快答先行节点：占位 + 快答都要打桩（快答内部会真实调 LLM/落库）
    monkeypatch.setattr(nodes.orch, "_add_streaming_message", lambda cid: "mid")
    monkeypatch.setattr(nodes.orch, "emit_guide_quick_take", lambda *a, **k: None)

    async def fake_collect(cid, p, intent, hotel, uid, user_text=""):
        return [{"title": "t", "url": "u", "summary": "s"}], False
    monkeypatch.setattr(nodes.orch, "collect_sources", fake_collect)

    def fake_gen(cid, ut, p, intent, sources, uid, msg_id=None, feedback=""):
        rec.gen_calls += 1
        return "攻略正文", "思考", msg_id or "mid", {"used": []}
    monkeypatch.setattr(nodes.orch, "generate_guide_streaming", fake_gen)

    async def fake_research(cid, p, queries, user_id=""):
        rec.research_calls += 1
        return [{"title": "extra", "url": "u2", "summary": "s2"}]
    monkeypatch.setattr(nodes.orch, "research_more", fake_research)

    def fake_finalize(*a, **k):
        rec.finalized = True
    monkeypatch.setattr(nodes.orch, "finalize_guide", fake_finalize)
    monkeypatch.setattr(nodes.orch, "_progress", lambda *a, **k: None)
    monkeypatch.setattr(nodes.orch, "_add_message", lambda *a, **k: None)

    # critique 恒判「不达标·rewrite」——测试循环会不会到上限就停
    class FakeCrit:
        def model_dump(self):
            return {"ok": False, "action": "rewrite", "issues": ["路线绕路"], "search_queries": []}

    class FakeLLM:
        def parse(self, *a, **k):
            return FakeCrit()
    monkeypatch.setattr(nodes, "get_llm", lambda: FakeLLM())
    return rec


def test_loop_terminates_at_cap(wired, monkeypatch):
    """critique 一直不满意 → 循环到 graph_max_guide_rounds 次后强制终稿。"""
    monkeypatch.setattr(settings, "reflection_enabled", True)
    monkeypatch.setattr(settings, "graph_max_guide_rounds", 2)
    asyncio.run(_compiled().ainvoke({"cid": "c", "user_text": "帮我规划成都"}))
    # 初次 + 2 轮重写 = 3 次生成；最终 finalize 一次
    assert wired.gen_calls == 3
    assert wired.finalized is True


def test_reflection_disabled_single_pass(wired, monkeypatch):
    """关闭反思 → 只生成一次直接终稿。"""
    monkeypatch.setattr(settings, "reflection_enabled", False)
    asyncio.run(_compiled().ainvoke({"cid": "c", "user_text": "帮我规划成都"}))
    assert wired.gen_calls == 1 and wired.finalized is True


def test_research_branch(wired, monkeypatch):
    """action=research 时走补搜再生成。"""
    monkeypatch.setattr(settings, "reflection_enabled", True)
    monkeypatch.setattr(settings, "graph_max_guide_rounds", 1)

    class FakeCrit:
        def model_dump(self):
            return {"ok": False, "action": "research", "issues": [], "search_queries": ["成都 小众景点"]}

    class FakeLLM:
        def parse(self, *a, **k):
            return FakeCrit()
    monkeypatch.setattr(nodes, "get_llm", lambda: FakeLLM())
    asyncio.run(_compiled().ainvoke({"cid": "c", "user_text": "帮我规划成都"}))
    assert wired.research_calls == 1
    assert wired.gen_calls == 2  # 初次 + 补搜后 1 次


# ---------- 快答先行（2026-08-13） ----------

def test_quick_take_node_placeholder_before_preliminary(monkeypatch):
    """顺序不变式：流式占位必须先于快答建立（否则 _is_running 误判完成）。"""
    calls = []

    def fake_add_streaming(cid):
        calls.append("placeholder")
        return "mid-1"

    def fake_emit(cid, ut, pref, uid):
        calls.append("quick_take")

    monkeypatch.setattr(nodes.orch, "_add_streaming_message", fake_add_streaming)
    monkeypatch.setattr(nodes.orch, "emit_guide_quick_take", fake_emit)
    out = nodes.quick_take_node({
        "cid": "c", "user_text": "规划成都", "pref": object(), "user_id": "u",
    })
    assert calls == ["placeholder", "quick_take"]
    assert out["msg_id"] == "mid-1"  # generate 节点据此复用同一条占位


def test_quick_take_failure_keeps_placeholder(monkeypatch):
    """快答失败（LLM 挂/被关）也不能影响主流程：占位仍在，节点正常返回 msg_id。"""
    def fake_add_streaming(cid):
        return "mid-2"

    def fake_emit(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(nodes.orch, "_add_streaming_message", fake_add_streaming)
    monkeypatch.setattr(nodes.orch, "emit_guide_quick_take", fake_emit)
    out = nodes.quick_take_node({"cid": "c", "user_text": "x", "pref": object(), "user_id": "u"})
    assert out["msg_id"] == "mid-2"


def test_apologize_finalizes_placeholder_instead_of_new_message(monkeypatch):
    """collect 无料走 apologize：快答先行的占位必须就地终稿，否则 streaming 残留。"""
    finalized = {}

    class FakePref:
        destination = "成都"

    monkeypatch.setattr(nodes.orch, "_finalize_streaming_message",
                        lambda mid, content, reasoning, meta: finalized.update(mid=mid, content=content))
    added = []
    monkeypatch.setattr(nodes.orch, "_add_message", lambda cid, role, content: added.append(content))
    nodes.apologize_node({"cid": "c", "pref": FakePref(), "msg_id": "mid-3"})
    assert finalized.get("mid") == "mid-3"
    assert "成都" in finalized.get("content", "")
    assert added == []  # 不再新增一条普通 assistant
