"""Phase 30 记忆升级 + 历史压缩单测（sqlite 内存库 + fake LLM，全离线）。

机制借鉴 Claude Code：findRelevantMemories（选择器）、memoryAge（新鲜度）、
分段压缩（近窗逐字 + 早期摘要）。设计见 task_plan-phase30-记忆升级与历史压缩.md。
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.memory import (
    EXTRACT_SYSTEM,
    _age_label,
    format_memories_block,
    select_relevant_memories,
)
from app.config import settings
from app.db.models import Base, TravelMemory

UTC_NOW = datetime.now(timezone.utc)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _mem(mid, content, mtype="preference", key=None, explicit=False, days_ago=0):
    return TravelMemory(
        id=mid, user_id="u1", type=mtype, key=key, content=content,
        explicit=explicit, weight=1.0,
        updated_at=UTC_NOW - timedelta(days=days_ago),
    )


# ---------- 新鲜度标注（B） ----------

def test_age_label_human_readable():
    assert _age_label(UTC_NOW) == "今天"
    assert _age_label(UTC_NOW - timedelta(days=1)) == "昨天"
    assert _age_label(UTC_NOW - timedelta(days=47)) == "47 天前"
    assert _age_label(None) == ""


def test_memories_block_carries_age():
    block = format_memories_block([_mem("m1", "用户爱吃辣", days_ago=3)])
    assert "用户爱吃辣（3 天前）" in block


def test_memories_block_carries_usage_discipline():
    """注入块必须自带「记忆里的日期/目的地/预算不代表本次行程」的纪律
    （2026-07-31：旅行足迹/预算偏好仍会带地名与金额，纪律是最后一道防线）。"""
    block = format_memories_block([_mem("m1", "用户去过成都、厦门", key="旅行足迹")])
    assert "记忆使用纪律" in block and "不要把它们当作本次行程" in block


# ---------- 记忆选择器（A） ----------

class _FakeLLM:
    """返回预设 id 列表的假选择器。"""

    def __init__(self, ids=None, fail=False):
        self.ids = ids or []
        self.fail = fail
        self.calls = 0

    def classify(self, prompt, schema, system=""):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        return schema(ids=self.ids)


def test_selector_picks_subset_keeps_explicit():
    mems = [
        _mem("e1", "用户忌口花生", explicit=True),
        _mem("p1", "用户爱吃辣"),
        _mem("p2", "用户喜欢博物馆"),
        _mem("p3", "用户habit坐高铁"),
    ]
    picked = select_relevant_memories(_FakeLLM(ids=["p2"]), mems, "厦门有什么博物馆")
    ids = {m.id for m in picked}
    assert ids == {"e1", "p2"}  # explicit 保底 + 选中的


def test_selector_failure_falls_back_to_all():
    mems = [_mem("p1", "A"), _mem("p2", "B")]
    picked = select_relevant_memories(_FakeLLM(fail=True), mems, "问题")
    assert len(picked) == 2  # 失败回退全量，选择器不能致损


def test_selector_empty_pick_is_legal():
    mems = [_mem("p1", "A"), _mem("p2", "B")]
    picked = select_relevant_memories(_FakeLLM(ids=[]), mems, "完全无关的问题")
    assert picked == []  # 宁缺毋滥：一条不选合法


# ---------- 提炼 prompt 升级（C） ----------

def test_extract_system_carries_new_disciplines():
    assert "绝对日期" in EXTRACT_SYSTEM
    assert "正面确认" in EXTRACT_SYSTEM
    assert "原因" in EXTRACT_SYSTEM


def test_plan_memory_ops_injects_today(monkeypatch):
    from app.agent.memory import plan_memory_ops

    captured = {}

    class _LLM:
        def classify(self, prompt, schema, system=""):
            captured["prompt"] = prompt
            from app.schemas.memory_schema import MemoryUpdatePlan

            return MemoryUpdatePlan(ops=[])

    plan_memory_ops(_LLM(), [], "下周五去成都", "好的")
    assert "今天是 20" in captured["prompt"]  # 含 ISO 日期，供换算绝对日期


# ---------- 历史压缩（D） ----------

def _add_msgs(db, cid, n_rounds):
    from app.db.models import TravelConversation, TravelMessage

    db.add(TravelConversation(id=cid, user_id="u1", title="厦门行程"))
    for i in range(n_rounds):
        db.add(TravelMessage(conversation_id=cid, role="user", content=f"用户消息{i}"))
        db.add(TravelMessage(conversation_id=cid, role="assistant", content=f"助手回复{i}"))
    db.commit()


def _patch_session(monkeypatch, db):
    from contextlib import contextmanager

    @contextmanager
    def fake_session():
        yield db

    monkeypatch.setattr("app.db.session.get_session", fake_session)
    monkeypatch.setattr("app.agent.orchestrator.get_session", fake_session)


def test_update_history_summary_folds_old_rounds(monkeypatch, db):
    from app.agent import orchestrator
    from app.db.models import TravelConversation

    _patch_session(monkeypatch, db)
    _add_msgs(db, "c1", n_rounds=8)  # 超过近窗 5 轮
    # Phase 91：压缩现在还要求**真的装不下**才折叠（否则遮蔽会把本来能全文注入的
    # 对话白白降级成摘要）。测试消息很短，把上限压低来触发。
    from app.config import settings

    monkeypatch.setattr(settings, "history_full_max_chars", 10)

    class _LLM:
        def classify(self, prompt, schema, system=""):
            assert "用户消息0" in prompt  # 折叠的是早期消息
            assert "用户消息7" not in prompt  # 近窗消息不进摘要
            return schema(summary="## 用户约束\n预算 5000\n## 已确认的决定\n住鼓浪屿")

    monkeypatch.setattr("app.llm.client.get_llm", lambda: _LLM())
    orchestrator.update_history_summary("c1")

    # Phase 91：摘要是**追加**进日志的一条 replace 消息，原文一条不删
    from app.db.models import TravelMessage

    summaries = db.query(TravelMessage).filter_by(conversation_id="c1", role="summary").all()
    assert len(summaries) == 1
    assert "预算 5000" in summaries[0].content
    assert summaries[0].surface_op == "replace"
    assert summaries[0].shadow_from_id and summaries[0].shadow_to_id
    # 被折叠的原始消息仍在表里（这正是与「就地覆盖」的本质区别）
    assert db.query(TravelMessage).filter_by(conversation_id="c1", role="user").count() == 8

    conv = db.get(TravelConversation, "c1")
    assert "预算 5000" in conv.history_summary  # 兼容字段仍写一份，老路径读它不炸


def test_update_history_summary_skips_short_conversation(monkeypatch, db):
    from app.agent import orchestrator
    from app.db.models import TravelConversation

    _patch_session(monkeypatch, db)
    _add_msgs(db, "c2", n_rounds=3)  # 近窗装得下

    monkeypatch.setattr("app.llm.client.get_llm",
                        lambda: (_ for _ in ()).throw(AssertionError("不应调用 LLM")))
    orchestrator.update_history_summary("c2")
    assert db.get(TravelConversation, "c2").history_summary is None


def test_history_text_prepends_summary(monkeypatch, db):
    from app.agent import orchestrator
    from app.db.models import TravelConversation

    _patch_session(monkeypatch, db)
    _add_msgs(db, "c3", n_rounds=2)
    db.get(TravelConversation, "c3").history_summary = "## 用户约束\n预算 5000"
    db.commit()

    text = orchestrator._history_text("c3")
    assert "【早前对话要点（已折叠）】" in text
    assert "预算 5000" in text
    assert "用户消息1" in text  # 近窗原文仍在
    assert text.index("预算 5000") < text.index("用户消息1")  # 摘要在前


# ---------- Phase 45：记忆机制三项优化 ----------

def test_load_memories_orders_by_hit_count(db):
    """访问频率纳入排序：同 explicit 档内，高频命中的排前（且剪枝时优先保留）。"""
    from app.agent.memory import load_memories
    from app.db.models import _now

    old = TravelMemory(id="m_old", user_id="u1", type="preference", content="高频但久未更新",
                       weight=1.0, hit_count=30, updated_at=_now() - timedelta(days=40))
    fresh = TravelMemory(id="m_fresh", user_id="u1", type="preference", content="新但没被用过",
                         weight=1.0, hit_count=0)
    db.add_all([old, fresh])
    db.commit()
    ordered = [m.id for m in load_memories(db, "u1")]
    assert ordered.index("m_old") < ordered.index("m_fresh")  # 高频靠前


def test_load_memories_explicit_still_beats_hits(db):
    """explicit 仍是首要键：明确记忆压过高频推断记忆。"""
    from app.agent.memory import load_memories

    explicit_new = TravelMemory(id="e1", user_id="u1", type="preference", content="用户亲口说",
                                explicit=True, weight=2.0, hit_count=0)
    inferred_hot = TravelMemory(id="i1", user_id="u1", type="preference", content="推断但高频",
                                explicit=False, weight=1.0, hit_count=99)
    db.add_all([explicit_new, inferred_hot])
    db.commit()
    ordered = [m.id for m in load_memories(db, "u1")]
    assert ordered == ["e1", "i1"]


def test_gather_bumps_hit_count(monkeypatch, db):
    """注入的记忆访问频率 +1（Phase 45）。"""
    from app.agent import memory as mem
    from contextlib import contextmanager

    @contextmanager
    def fake_session():
        yield db

    monkeypatch.setattr("app.db.session.get_session", fake_session)
    monkeypatch.setattr(settings, "memory_select_threshold", 999)  # 不走选择器，全量注入
    db.add(TravelMemory(id="h1", user_id="u1", type="preference", content="爱吃辣", hit_count=0))
    db.add(TravelMemory(id="h2", user_id="u1", type="fact", content="常驻成都", hit_count=5))
    db.commit()

    mem.gather_context("c1", "", "u1", user_text="随便问问")
    assert db.get(TravelMemory, "h1").hit_count == 1
    assert db.get(TravelMemory, "h2").hit_count == 6


def test_procedural_and_footprint_canonical_keys():
    """程序记忆 + 旅行足迹 归槽映射正确。"""
    from app.agent.memory import CANONICAL_KEYS, MEMORY_TYPES

    assert "procedural" in MEMORY_TYPES
    assert CANONICAL_KEYS["规划习惯"] == "procedural"
    assert CANONICAL_KEYS["旅行足迹"] == "fact"


def test_apply_ops_procedural_slot(db):
    """规划习惯类输入落到 key=规划习惯 type=procedural。"""
    from app.agent.memory import apply_ops, load_memories
    from app.schemas.memory_schema import MemoryOp, MemoryUpdatePlan

    apply_ops(db, MemoryUpdatePlan(ops=[
        MemoryOp(op="add", key="规划习惯", content="用户习惯先定酒店再排景点、偏好自由行", explicit=True),
    ]), "u1")
    rows = load_memories(db, "u1")
    assert len(rows) == 1
    assert rows[0].key == "规划习惯" and rows[0].type == "procedural"


def test_extract_and_consolidate_prompts_carry_new_disciplines():
    from app.agent.memory import CONSOLIDATE_SYSTEM, EXTRACT_SYSTEM

    assert "规划习惯" in EXTRACT_SYSTEM and "程序记忆" in EXTRACT_SYSTEM
    assert "旅行足迹" in EXTRACT_SYSTEM
    assert "旅行足迹" in CONSOLIDATE_SYSTEM  # 累积槽，合并不丢城市
