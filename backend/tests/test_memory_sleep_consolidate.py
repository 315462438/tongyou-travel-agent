"""Phase 57 睡眠整合门控单测（sqlite 内存库，离线）。

测门控 `_should_sleep_consolidate`（距上次够久 + 新记忆够多 + 总量够）与 `maybe_consolidate_async`
触发后台整合（mock 线程/LLM，不真跑）。
"""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent import memory as mem
from app.config import settings
from app.db.models import Base, TravelMemory, TravelUser, _now


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed(db, n, *, updated=None, consolidated_at="unset"):
    u = TravelUser(id="u1", username="u", password_hash="x")
    if consolidated_at != "unset":
        u.memory_consolidated_at = consolidated_at
    db.add(u)
    for i in range(n):
        m = TravelMemory(user_id="u1", type="preference", key=f"k{i}", content=f"c{i}")
        if updated is not None:
            m.updated_at = updated
        db.add(m)
    db.commit()
    return u


def test_gate_true_when_enough_new_and_never_consolidated(db, monkeypatch):
    monkeypatch.setattr(settings, "memory_consolidate_min_total", 8)
    monkeypatch.setattr(settings, "memory_consolidate_min_new", 5)
    _seed(db, 10, consolidated_at=None)  # 从未整过，10 条新记忆
    assert mem._should_sleep_consolidate(db, "u1") is True


def test_gate_false_when_too_few_total(db, monkeypatch):
    monkeypatch.setattr(settings, "memory_consolidate_min_total", 8)
    _seed(db, 3, consolidated_at=None)  # 总量 3 < 8
    assert mem._should_sleep_consolidate(db, "u1") is False


def test_gate_false_when_recently_consolidated(db, monkeypatch):
    monkeypatch.setattr(settings, "memory_consolidate_min_hours", 6)
    monkeypatch.setattr(settings, "memory_consolidate_min_total", 8)
    monkeypatch.setattr(settings, "memory_consolidate_min_new", 1)
    recent = _now().replace(tzinfo=None) - timedelta(hours=1)  # 1 小时前刚整过
    _seed(db, 10, consolidated_at=recent)
    assert mem._should_sleep_consolidate(db, "u1") is False


def test_gate_false_when_no_new_since_last(db, monkeypatch):
    monkeypatch.setattr(settings, "memory_consolidate_min_hours", 6)
    monkeypatch.setattr(settings, "memory_consolidate_min_total", 8)
    monkeypatch.setattr(settings, "memory_consolidate_min_new", 5)
    long_ago = _now().replace(tzinfo=None) - timedelta(hours=48)
    # 记忆的 updated_at 都早于上次整合时间 → 无新记忆
    _seed(db, 10, updated=long_ago - timedelta(hours=1), consolidated_at=long_ago)
    assert mem._should_sleep_consolidate(db, "u1") is False


def test_gate_true_when_new_since_last_and_old_enough(db, monkeypatch):
    monkeypatch.setattr(settings, "memory_consolidate_min_hours", 6)
    monkeypatch.setattr(settings, "memory_consolidate_min_total", 8)
    monkeypatch.setattr(settings, "memory_consolidate_min_new", 5)
    long_ago = _now().replace(tzinfo=None) - timedelta(hours=48)
    # 上次整合 48h 前，记忆 updated_at 是「现在」→ 都算新 → 满足
    _seed(db, 10, updated=_now().replace(tzinfo=None), consolidated_at=long_ago)
    assert mem._should_sleep_consolidate(db, "u1") is True


def test_maybe_consolidate_async_spawns_when_gate_met(db, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def fake_session():
        yield db

    monkeypatch.setattr("app.db.session.get_session", fake_session)
    monkeypatch.setattr(mem, "_should_sleep_consolidate", lambda db, uid: True)
    spawned = {}

    class _FakeThread:
        def __init__(self, target=None, args=(), daemon=None):
            spawned["target"], spawned["args"] = target, args

        def start(self):
            spawned["started"] = True

    monkeypatch.setattr(mem.threading, "Thread", _FakeThread)
    assert mem.maybe_consolidate_async("u1") is True
    assert spawned.get("started") and spawned["args"] == ("u1",)
    # 同一用户已在整合中 → 不重复触发
    assert mem.maybe_consolidate_async("u1") is False
    mem._consolidating.discard("u1")  # 清理


def test_maybe_consolidate_disabled(monkeypatch):
    monkeypatch.setattr(settings, "memory_sleep_consolidate_enabled", False)
    assert mem.maybe_consolidate_async("u1") is False
