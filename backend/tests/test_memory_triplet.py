"""记忆 triplet 归槽机制（Phase 17）单测。

sqlite 内存库 + fake LLM，全部离线。验证四条策略：
相同 key 覆盖 / 相似合并（同 key）/ 时间更新优先 / 用户明确表达优先，以及 consolidate 清理。
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.memory import apply_ops, consolidate_memories, load_memories
from app.config import settings
from app.db.models import Base, TravelMemory
from app.schemas.memory_schema import (
    MemoryConsolidation,
    MemoryOp,
    MemoryTriplet,
    MemoryUpdatePlan,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _plan(*ops):
    return MemoryUpdatePlan(ops=list(ops))


# ---------- 相同 key 直接覆盖 ----------

def test_same_key_overwrites_not_appends(db):
    apply_ops(db, _plan(MemoryOp(op="add", key="口味偏好", content="用户爱吃辣")), "u1")
    apply_ops(db, _plan(MemoryOp(op="add", key="口味偏好", content="用户爱吃海鲜和辣")), "u1")
    rows = load_memories(db, "u1")
    assert len(rows) == 1  # 没有堆成两条
    assert rows[0].content == "用户爱吃海鲜和辣"  # 时间更新优先：新内容胜出
    assert rows[0].key == "口味偏好"


def test_footprint_single_slot(db):
    """旅行足迹单槽：多次覆盖只保留最新一条（当前行程槽已于 2026-07-31 退役，
    行程信息里只有「去过哪些城市」值得长期保留）。"""
    for content in ("用户去过开封", "用户去过开封、宁波", "用户去过开封、宁波、厦门"):
        apply_ops(db, _plan(MemoryOp(op="update", key="旅行足迹", content=content)), "u1")
    rows = load_memories(db, "u1")
    trips = [r for r in rows if r.key == "旅行足迹"]
    assert len(trips) == 1
    assert trips[0].content == "用户去过开封、宁波、厦门"
    assert trips[0].type == "fact"  # key 决定 type


def test_distinct_keys_coexist(db):
    apply_ops(db, _plan(
        MemoryOp(op="add", key="口味偏好", content="用户爱吃海鲜"),
        MemoryOp(op="add", key="节奏偏好", content="用户喜欢轻松"),
        MemoryOp(op="add", key="常驻城市", content="用户常驻上海"),
    ), "u1")
    assert len(load_memories(db, "u1")) == 3  # 不同 key 各自共存


# ---------- 用户明确表达优先（explicit 粘性 + 权重） ----------

def test_explicit_is_sticky_and_weighted(db):
    apply_ops(db, _plan(MemoryOp(op="add", key="口味偏好", content="用户爱吃辣", explicit=True)), "u1")
    row = load_memories(db, "u1")[0]
    assert row.explicit is True and row.weight == 2.0
    # 后续推断内容覆盖，但 explicit 粘性不降级
    apply_ops(db, _plan(MemoryOp(op="add", key="口味偏好", content="用户口味清淡", explicit=False)), "u1")
    row = load_memories(db, "u1")[0]
    assert row.explicit is True and row.weight == 2.0


def test_explicit_ranks_first(db):
    apply_ops(db, _plan(
        MemoryOp(op="add", key="节奏偏好", content="用户偏好紧凑", explicit=False),
        MemoryOp(op="add", key="口味偏好", content="用户爱吃辣", explicit=True),
    ), "u1")
    rows = load_memories(db, "u1")  # 按 weight desc 排
    assert rows[0].content == "用户爱吃辣"  # explicit 权重高排最前


# ---------- 隔离 / 剪枝 ----------

def test_key_isolated_per_user(db):
    apply_ops(db, _plan(MemoryOp(op="add", key="口味偏好", content="u1 爱吃辣")), "u1")
    apply_ops(db, _plan(MemoryOp(op="add", key="口味偏好", content="u2 爱吃甜")), "u2")
    assert len(load_memories(db, "u1")) == 1 and len(load_memories(db, "u2")) == 1
    assert load_memories(db, "u1")[0].content == "u1 爱吃辣"


def test_prune_caps_rows(db, monkeypatch):
    monkeypatch.setattr(settings, "memory_max_rows", 3)
    ops = [MemoryOp(op="add", key=f"k{i}", content=f"记忆{i}") for i in range(6)]
    apply_ops(db, _plan(*ops), "u1")
    assert len(load_memories(db, "u1")) == 3  # 超限剪枝


# ---------- consolidate 清理存量 ----------

def test_consolidate_dedups_and_replaces(db):
    # 造脏数据：多条重复/近义 + 一堆瞬时行程
    for c in ["用户喜欢海鲜", "用户喜欢美食", "用户喜欢历史文化"]:
        db.add(TravelMemory(user_id="u1", type="preference", content=c))
    for d in ["开封", "宁波", "厦门", "昆明"]:
        db.add(TravelMemory(user_id="u1", type="preference", content=f"用户计划前往{d}旅行"))
    db.commit()
    assert len(load_memories(db, "u1")) == 7

    class FakeLLM:
        def classify(self, prompt, schema, system=""):
            return MemoryConsolidation(memories=[
                MemoryTriplet(key="口味偏好", type="preference", content="用户喜欢海鲜、美食"),
                MemoryTriplet(key="兴趣偏好", type="preference", content="用户喜欢历史文化"),
                MemoryTriplet(key="旅行足迹", type="fact", content="用户去过厦门"),
                MemoryTriplet(key="口味偏好", content="重复key应被丢弃"),  # 同 key 只留第一条
            ])

    result = consolidate_memories(db, "u1", FakeLLM())
    assert result == {"before": 7, "after": 3}
    rows = load_memories(db, "u1")
    keys = sorted(r.key for r in rows)
    assert keys == sorted(["口味偏好", "兴趣偏好", "旅行足迹"])  # 去重且无重复 key


def test_consolidate_empty_result_keeps_memories(db):
    db.add(TravelMemory(user_id="u1", type="preference", content="用户爱吃辣"))
    db.commit()

    class FakeLLM:
        def classify(self, prompt, schema, system=""):
            return MemoryConsolidation(memories=[])

    result = consolidate_memories(db, "u1", FakeLLM())
    assert result == {"before": 1, "after": 1}  # 空结果不清空
    assert len(load_memories(db, "u1")) == 1
