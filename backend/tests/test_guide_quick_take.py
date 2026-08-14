"""guide 快答先行 + 停止收尾（2026-08-13 感知提速）。全部离线打桩。"""

import json

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
    assert calls["max_tokens"] == 1000  # 2026-08-13：400 会被思考链吃光导致 content 空
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
