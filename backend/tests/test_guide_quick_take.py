"""guide 快答先行 + 停止收尾（2026-08-13 感知提速）。全部离线打桩。"""

import json
import threading

import pytest

from app.agent import orchestrator as orch
from app.config import settings


# ---------- emit_guide_quick_take ----------

class _FakePref:
    destination = "成都"
    days = 3
    budget = 2000
    pace = "轻松"
    interests = ["美食", "古镇"]
    special_requirements = []


def _wire_quick_take(monkeypatch, reply="初步思路：3 天成都，Day1 市区，Day2 都江堰，Day3 熊猫基地", reasoning=""):
    calls = {"added": [], "progress": [], "max_tokens": None}

    class FakeLLM:
        def generate_with_reasoning(self, prompt, **kwargs):
            calls["prompt"] = prompt
            calls["max_tokens"] = kwargs.get("max_tokens")
            return reply, reasoning

    monkeypatch.setattr(orch, "get_llm", lambda: FakeLLM())
    monkeypatch.setattr(orch, "gather_context", lambda *a, **k: {"block": "记忆块\n"})
    monkeypatch.setattr(orch, "_add_message",
                        lambda cid, role, content, meta=None: calls["added"].append((content, meta)))
    monkeypatch.setattr(orch, "_progress", lambda cid, text, meta=None: calls["progress"].append(text))
    import app.agent.cancel as cancel
    monkeypatch.setattr(cancel, "is_cancelled", lambda cid: False)
    return calls


def test_quick_take_disabled_skips_everything(monkeypatch):
    monkeypatch.setattr(settings, "guide_quick_take", False)
    calls = {"n": 0}
    monkeypatch.setattr(orch, "get_llm", lambda: (_ for _ in ()).throw(AssertionError("不应调 LLM")))
    orch.emit_guide_quick_take("c", "规划成都", _FakePref(), "u")
    assert calls["n"] == 0


def test_quick_take_writes_preliminary_message(monkeypatch):
    calls = _wire_quick_take(monkeypatch)
    orch.emit_guide_quick_take("c", "规划成都", _FakePref(), "u")
    assert len(calls["added"]) == 1
    content, meta = calls["added"][0]
    assert content.startswith("初步思路")
    assert meta == {"preliminary": True}  # 前端据此渲染橙色徽章；_is_running 排除终稿判定
    assert "成都" in calls["prompt"] and "3" in calls["prompt"] and "2000" in calls["prompt"]
    # 2026-08-13：400 会被思考链吃光导致 content 空。2026-08-21 再提到 1600——线上实测
    # 1000 仍被吃满（三次里两次 out=0 / reason=1000），只能靠兜底把内部独白给用户看。
    assert calls["max_tokens"] >= 1600
    assert calls["progress"]  # 播一条「已给出初步思路」


def test_quick_take_empty_content_falls_back_to_reasoning(monkeypatch):
    """DeepSeek 思考模式偶发 content 为空：用思考链前 200 字兜底，不能白跑。"""
    calls = _wire_quick_take(
        monkeypatch, reply="", reasoning="用户要松弛的成都三日游，建议 Day1 市区古街、Day2 都江堰、Day3 熊猫基地，预算 2000 内。"
    )
    orch.emit_guide_quick_take("c", "规划成都", _FakePref(), "u")
    assert len(calls["added"]) == 1
    content, meta = calls["added"][0]
    assert content.startswith("用户要松弛")  # reasoning 兜底
    assert meta == {"preliminary": True}


def test_quick_take_both_empty_skips(monkeypatch):
    calls = _wire_quick_take(monkeypatch, reply="", reasoning="")
    orch.emit_guide_quick_take("c", "规划成都", _FakePref(), "u")
    assert calls["added"] == []


def test_quick_take_failure_is_silent(monkeypatch):
    calls = _wire_quick_take(monkeypatch)

    class Boom:
        def generate_with_reasoning(self, *a, **k):
            raise RuntimeError("llm down")

    monkeypatch.setattr(orch, "get_llm", lambda: Boom())
    orch.emit_guide_quick_take("c", "规划成都", _FakePref(), "u")  # 不抛、不落消息
    assert calls["added"] == []


def test_quick_take_respects_cancel(monkeypatch):
    calls = _wire_quick_take(monkeypatch)
    import app.agent.cancel as cancel
    monkeypatch.setattr(cancel, "is_cancelled", lambda cid: True)
    orch.emit_guide_quick_take("c", "规划成都", _FakePref(), "u")
    assert calls["added"] == []  # 停止后不再往会话里塞消息


# ---------- _ensure_stopped_message（占位空白期停止） ----------

class _FakeLast:
    def __init__(self, role, meta_json=None, content="", reasoning=None):
        self.id = "m1"
        self.role = role
        self.meta_json = meta_json
        self.content = content
        self.reasoning = reasoning


class _FakeResult:
    def __init__(self, last):
        self._last = last

    def scalar_one_or_none(self):
        return self._last


class _FakeSession:
    def __init__(self, last):
        self._last = last

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        return _FakeResult(self._last)


def _wire_stop(monkeypatch, last):
    calls = {"finalized": [], "added": [], "cleared": 0}
    monkeypatch.setattr(orch, "get_session", lambda: _FakeSession(last))
    monkeypatch.setattr(
        orch, "_finalize_streaming_message",
        lambda mid, content, reasoning, meta: calls["finalized"].append((mid, content)),
    )
    monkeypatch.setattr(orch, "_add_message",
                        lambda cid, role, content: calls["added"].append(content))
    monkeypatch.setattr(orch, "clear_plain_progress", lambda cid: calls.__setitem__("cleared", 1))
    return calls


def test_stop_empty_placeholder_finalizes_in_place(monkeypatch):
    """快答先行后、collect 阶段被停止：空占位就地终稿「已停止本轮」，streaming 不残留。"""
    last = _FakeLast("assistant", json.dumps({"streaming": True}), content="")
    calls = _wire_stop(monkeypatch, last)
    orch._ensure_stopped_message("c")
    assert calls["finalized"] == [("m1", "已停止本轮。")]
    assert calls["added"] == []
    assert calls["cleared"] == 1


def test_stop_partial_streaming_finalizes_content(monkeypatch):
    last = _FakeLast("assistant", json.dumps({"streaming": True}), content="已生成一半的内容")
    calls = _wire_stop(monkeypatch, last)
    orch._ensure_stopped_message("c")
    assert calls["finalized"] == [("m1", "已生成一半的内容")]  # 就地保留，不补「已停止」
    assert calls["added"] == []


def test_stop_after_finalize_is_noop(monkeypatch):
    last = _FakeLast("assistant", json.dumps({"sources": []}), content="完整攻略")
    calls = _wire_stop(monkeypatch, last)
    orch._ensure_stopped_message("c")
    assert calls["finalized"] == []
    assert calls["added"] == []


def test_stop_no_last_adds_message(monkeypatch):
    calls = _wire_stop(monkeypatch, None)
    orch._ensure_stopped_message("c")
    assert calls["finalized"] == []
    assert calls["added"] == ["已停止本轮。"]


def test_stop_empty_placeholder_with_custom_text(monkeypatch):
    """2026-08-13 泛化：异常失败路径用自定义文案终稿残留占位（否则前端永远判运行中）。"""
    last = _FakeLast("assistant", json.dumps({"streaming": True}), content="")
    calls = _wire_stop(monkeypatch, last)
    orch._ensure_stopped_message("c", "抱歉，处理过程中出错了，请重试。")
    assert calls["finalized"] == [("m1", "抱歉，处理过程中出错了，请重试。")]
    assert calls["added"] == []


def test_stop_no_last_with_custom_text(monkeypatch):
    calls = _wire_stop(monkeypatch, None)
    orch._ensure_stopped_message("c", "抱歉，处理过程中出错了，请重试。")
    assert calls["finalized"] == []
    assert calls["added"] == ["抱歉，处理过程中出错了，请重试。"]


# ---------- 思考纪律与预算（2026-08-21） ----------

def test_quick_take_prompt_carries_thinking_discipline():
    """线上三次里两次 out=0 / reason=1000——思考链吃满预算，正文为空。

    治法是 Phase 11 在 ITINERARY 上验证过的那条：在 system 里写思考纪律。
    这条断言防的是后人重构 prompt 时把它删掉——删了不会报错，只会悄悄退化成内部独白。
    """
    assert "思考" in orch.GUIDE_QUICK_TAKE_SYSTEM
    assert "两三行" in orch.GUIDE_QUICK_TAKE_SYSTEM


# ---------- 不阻塞采集（2026-08-21） ----------

def test_quick_take_node_does_not_wait_for_the_llm(monkeypatch):
    """核心：快答与采集没有数据依赖，不该串起来白等 10 秒。

    让假 LLM 阻塞 2 秒，节点必须立刻返回——否则 collect 就被挡住了。
    """
    import time

    from app.agent import nodes

    started = threading.Event()

    def _slow(cid, user_text, pref, user_id):
        started.set()
        time.sleep(2)

    monkeypatch.setattr(settings, "guide_quick_take", True)
    monkeypatch.setattr(orch, "_add_streaming_message", lambda cid: "msg-1")
    monkeypatch.setattr(orch, "emit_guide_quick_take", _slow)

    t0 = time.monotonic()
    out = nodes.quick_take_node({"cid": "c", "user_text": "规划成都", "pref": _FakePref(), "user_id": "u"})
    elapsed = time.monotonic() - t0

    assert elapsed < 0.5, f"节点等了 {elapsed:.1f}s，快答又把采集挡住了"
    assert out == {"msg_id": "msg-1"}
    assert started.wait(timeout=3), "后台快答根本没起来"


def test_placeholder_is_still_created_synchronously(monkeypatch):
    """顺序不变式没有松动：占位必须在节点返回前就落库。

    占位晚于快答消息的话，_is_running 会判本轮完成、前端停止轮询、完整版永远收不到
    （Phase 71 那个坑）。所以并行化只能挪走 LLM 调用，不能挪走占位。
    """
    from app.agent import nodes

    order = []
    monkeypatch.setattr(settings, "guide_quick_take", True)
    monkeypatch.setattr(orch, "_add_streaming_message",
                        lambda cid: (order.append("placeholder"), "msg-1")[1])
    monkeypatch.setattr(orch, "emit_guide_quick_take",
                        lambda *a, **k: order.append("quick_take"))

    nodes.quick_take_node({"cid": "c", "user_text": "x", "pref": _FakePref(), "user_id": "u"})
    assert order[0] == "placeholder", "占位必须先于快答"


def test_quick_take_thread_failure_does_not_break_the_node(monkeypatch):
    """后台快答炸了，节点照常返回 msg_id——占位已在，整轮不受影响。"""
    from app.agent import nodes

    monkeypatch.setattr(settings, "guide_quick_take", True)
    monkeypatch.setattr(orch, "_add_streaming_message", lambda cid: "msg-1")

    def _boom(*a, **k):
        raise RuntimeError("快答挂了")

    monkeypatch.setattr(orch, "emit_guide_quick_take", _boom)
    out = nodes.quick_take_node({"cid": "c", "user_text": "x", "pref": _FakePref(), "user_id": "u"})
    assert out == {"msg_id": "msg-1"}


def test_quick_take_node_skips_thread_when_disabled(monkeypatch):
    """关掉开关时连线程都不起。"""
    from app.agent import nodes

    monkeypatch.setattr(settings, "guide_quick_take", False)
    monkeypatch.setattr(orch, "_add_streaming_message", lambda cid: "msg-1")
    monkeypatch.setattr(orch, "emit_guide_quick_take",
                        lambda *a, **k: pytest.fail("关闭时不该跑快答"))

    assert nodes.quick_take_node(
        {"cid": "c", "user_text": "x", "pref": _FakePref(), "user_id": "u"}
    ) == {"msg_id": "msg-1"}
