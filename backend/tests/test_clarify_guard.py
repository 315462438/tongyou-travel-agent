"""Phase 68：追问熔断 + 授权代选。

真实现场：用户连续 4 轮被问同一个问题，即使明说「你安排一个比较热门的」仍被追问。
根因是「空目的地即反问」是唯一出口且无熔断。这里锁死回归。全部离线，不打 LLM。
"""

import json

import pytest

from app.agent import orchestrator as orch


# ---------- 追问句式判定 ----------

@pytest.mark.parametrize("text,expected", [
    ("您更倾向去六安、安庆还是九江呢？", True),
    ("想去哪里呢?", True),
    ("", False),
    ("好的，这就为你规划。", False),          # 非问句
    ("这是一份完整攻略" + "详细内容" * 20 + "？", False),  # 超 60 字，是正文不是追问
])
def test_is_clarify_text(text, expected):
    assert orch._is_clarify_text(text) is expected


# ---------- 连续追问计数 ----------

class _FakeMsg:
    def __init__(self, content, role="assistant", meta=None):
        self.content = content
        self.role = role
        self.meta_json = json.dumps(meta) if meta else None


def _patch_msgs(monkeypatch, msgs):
    """伪造 _recent_clarify_rounds 的 DB 查询结果（按时间倒序）。"""
    class _Scalars:
        def __init__(self, rows): self._rows = rows
        def all(self): return self._rows

    class _Res:
        def __init__(self, rows): self._rows = rows
        def scalars(self): return _Scalars(self._rows)

    class _DB:
        def execute(self, *a, **kw): return _Res(msgs)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(orch, "get_session", lambda: _DB())


def test_counts_consecutive_clarifies(monkeypatch):
    _patch_msgs(monkeypatch, [
        _FakeMsg("您是想去六安、安庆还是九江呢？"),
        _FakeMsg("您更倾向哪个方向呢？"),
        _FakeMsg("这是为你规划的完整攻略，包含每日行程……"),  # 正文，计数到此为止
        _FakeMsg("还有别的问题吗？"),
    ])
    assert orch._recent_clarify_rounds("cid") == 2


def test_zero_when_last_is_normal_reply(monkeypatch):
    _patch_msgs(monkeypatch, [_FakeMsg("这是完整攻略，Day1 ……")])
    assert orch._recent_clarify_rounds("cid") == 0


def test_placeholder_and_panel_messages_are_skipped(monkeypatch):
    """流式占位/海报/预算面板不算一轮对话，不能打断连续追问的计数。"""
    _patch_msgs(monkeypatch, [
        _FakeMsg("", meta={"streaming": True}),
        _FakeMsg("您想去哪个城市呢？"),
        _FakeMsg("预算明细", meta={"budget": {"total": 1}}),
        _FakeMsg("要去哪儿呀？"),
    ])
    assert orch._recent_clarify_rounds("cid") == 2


def test_count_failure_returns_zero(monkeypatch):
    """查库异常时返回 0 —— 宁可不熔断，也不要误熔断成乱代选。"""
    def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(orch, "get_session", _boom)
    assert orch._recent_clarify_rounds("cid") == 0


# ---------- 代选 ----------

class _FakeLLM:
    def __init__(self, dest="", raise_=False):
        self.dest = dest
        self.raise_ = raise_
        self.called = 0

    def parse(self, text, schema, **kw):
        self.called += 1
        if self.raise_:
            raise RuntimeError("llm down")
        return schema(destination=self.dest)


def test_decide_destination_returns_pick():
    assert orch._decide_destination(_FakeLLM("六安"), "历史", "你定") == "六安"


def test_decide_destination_rejects_placeholder():
    """代选也不许返回占位词，否则又会拿去搜出垃圾（Phase 59.2 那个坑）。"""
    assert orch._decide_destination(_FakeLLM("热门目的地"), "历史", "你定") == ""


def test_decide_destination_survives_llm_failure():
    assert orch._decide_destination(_FakeLLM(raise_=True), "历史", "你定") == ""


# ---------- 归一 ----------

def test_normalize_destination_placeholders():
    for p in ("热门目的地", "附近", "周边", "待定", "  "):
        assert orch._normalize_destination(p) == ""
    assert orch._normalize_destination("  六安 ") == "六安"
