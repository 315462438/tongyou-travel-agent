"""Phase 76：区域型提问给候选，不再反问。

背景（08-04 真实数据）：8 个提问的新用户里 3 个首问是「合肥周边」「皖南」
「合肥周边溯溪」这种区域型表达——最自然的问法，却被打回去要求先自己选城市。
"""

import json
from types import SimpleNamespace

import pytest

from app.agent import orchestrator as orch


class _FakeLLM:
    """按需返回候选；record 记录被要求的 schema，便于断言走的是快模型。"""

    def __init__(self, candidates=None, raise_it=False):
        self._candidates = candidates or []
        self._raise = raise_it
        self.models = []

    def parse(self, _prompt, schema, model=None, system=None):
        self.models.append(model)
        if self._raise:
            raise RuntimeError("boom")
        return schema(candidates=[
            orch._DestCandidate(**c) if isinstance(c, dict) else c
            for c in self._candidates
        ])


def test_suggests_real_candidates():
    llm = _FakeLLM([
        {"name": "池州", "reason": "牯牛降果冻水，自驾2小时", "tag": "山水清凉"},
        {"name": "宣城", "reason": "敬亭山桃花潭，人少好逛", "tag": "诗意古镇"},
        {"name": "天堂寨", "reason": "大别山避暑，夏天凉快", "tag": "避暑"},
    ])
    out = orch._suggest_destinations(llm, "", "皖南的2日游，风景好")
    assert [c["name"] for c in out] == ["池州", "宣城", "天堂寨"]
    assert out[0]["reason"] and out[0]["tag"]


def test_uses_fast_classifier_model():
    """候选必须秒级返回——产品决策是「只列候选、等用户选」，慢了就没意义。"""
    from app.config import settings

    llm = _FakeLLM([{"name": "池州", "reason": "r", "tag": "t"}])
    orch._suggest_destinations(llm, "", "皖南")
    assert llm.models == [settings.model_classifier]


def test_placeholder_candidates_are_dropped():
    """候选会被原样当成下一轮目的地送进搜索链路，占位词必须挡在这里。

    真实踩坑：「热门目的地」拿去必应搜出一堆游戏官网。
    """
    llm = _FakeLLM([
        {"name": "热门目的地", "reason": "x", "tag": ""},
        {"name": "周边", "reason": "x", "tag": ""},
        {"name": "池州", "reason": "ok", "tag": ""},
    ])
    assert [c["name"] for c in orch._suggest_destinations(llm, "", "皖南")] == ["池州"]


def test_duplicate_candidates_removed():
    llm = _FakeLLM([
        {"name": "池州", "reason": "a", "tag": ""},
        {"name": "池州", "reason": "b", "tag": ""},
    ])
    assert len(orch._suggest_destinations(llm, "", "皖南")) == 1


def test_capped_at_three():
    llm = _FakeLLM([{"name": f"城市{i}", "reason": "r", "tag": ""} for i in range(8)])
    assert len(orch._suggest_destinations(llm, "", "皖南")) == 3


def test_llm_failure_returns_empty_so_caller_falls_back():
    """候选是增强，失败必须回落到原来的文字反问，不能把整轮打挂。"""
    assert orch._suggest_destinations(_FakeLLM(raise_it=True), "", "皖南") == []


def test_empty_candidates_when_model_returns_nothing():
    assert orch._suggest_destinations(_FakeLLM([]), "", "皖南") == []


# ---------- 熔断：候选卡也要计入追问轮数 ----------

def _rows(*metas_and_contents):
    return [SimpleNamespace(content=c, meta_json=json.dumps(m) if m else None)
            for m, c in metas_and_contents]


def test_candidate_message_counts_as_a_clarify_round(monkeypatch):
    """否则连续给候选永远不触发强制代选，就是换了张皮的无限追问。"""
    rows = _rows(
        ({"candidates": [{"name": "池州"}]}, "帮你圈了几个合适的方向，点一个我就开始排行程："),
        ({"candidates": [{"name": "宣城"}]}, "帮你圈了几个合适的方向，点一个我就开始排行程："),
    )
    monkeypatch.setattr(orch, "get_session", lambda: _FakeSession(rows))
    assert orch._recent_clarify_rounds("cid") == 2


def test_normal_guide_stops_the_count(monkeypatch):
    rows = _rows(
        ({"candidates": [{"name": "池州"}]}, "帮你圈了几个方向："),
        (None, "# 池州两日游\n正文很长" + "内容" * 100),
        ({"candidates": [{"name": "x"}]}, "更早的候选，不该被数到"),
    )
    monkeypatch.setattr(orch, "get_session", lambda: _FakeSession(rows))
    assert orch._recent_clarify_rounds("cid") == 1


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, _stmt):
        rows = self._rows

        class R:
            def scalars(self):
                return self

            def all(self):
                return rows
        return R()
