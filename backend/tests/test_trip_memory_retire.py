"""退役「当前行程」记忆槽 + 确定性最近规划提示（2026-07-31）。

计划：docs/task_plans/退役当前行程记忆槽-2026-07-31.md
背景：trip_state 是时点事实伪装成长期偏好，把旧行程的日期/预算泄漏进新行程
（线上真实 bug）。跨会话指代消解改由 recent_plan_hint 确定性提供。全部离线。
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.memory import (
    CANONICAL_KEYS,
    MEMORY_TYPES,
    RECENT_PLAN_HINT_DAYS,
    format_memories_block,
    recent_plan_hint,
)
from app.db.models import Base, TravelConversation, TravelMemory, TravelMessage


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _plan_msg(db, cid, user_id, dest, days_ago=0, with_sources=True, title="旧对话"):
    """建一个「已出过攻略」的会话。2026-07-31 起 hint 读 travel_conversation.destination
    （finalize_guide 落盘），with_sources=False 表示这个会话从没出过攻略（列为空）。"""
    ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_ago)
    db.add(TravelConversation(
        id=cid, user_id=user_id, title=title,
        destination=dest if with_sources else None,
        guide_message_id=f"m-{cid}" if with_sources else None,
        created_at=ts, updated_at=ts,
    ))
    meta = {"preference": {"destination": dest}}
    if with_sources:
        meta["sources"] = [{"title": "小红书｜攻略", "url": "https://x"}]
    db.add(TravelMessage(
        id=f"m-{cid}", conversation_id=cid, role="assistant", content="攻略正文" * 40,
        meta_json=json.dumps(meta), created_at=ts,
    ))
    db.commit()


# ---------- 槽已退役 ----------

def test_trip_state_slot_removed():
    assert "当前行程" not in CANONICAL_KEYS
    assert "trip_state" not in CANONICAL_KEYS.values()
    assert "trip_state" not in MEMORY_TYPES


def test_residual_trip_state_rows_are_hard_filtered(db, monkeypatch):
    """存量行/模型偶发新造的 trip_state 都不得进入注入块。"""
    from app.agent import memory as mem

    db.add(TravelMemory(user_id="u1", type="trip_state", key="当前行程",
                        content="2026年国庆去成都4天3晚，预算5000"))
    db.add(TravelMemory(user_id="u1", type="preference", key="口味偏好", content="用户爱吃辣"))
    db.commit()

    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("app.db.session.get_session", lambda: _Ctx())
    ctx = mem.gather_context("c-new", "武汉", "u1", user_text="合肥到武汉沿途有什么古镇")
    # 用记忆内容里独有的串断言（纪律文案本身举了「国庆去成都」的例子，不能用「国庆」判）
    assert "4天3晚" not in ctx["block"] and "预算5000" not in ctx["block"]
    assert "爱吃辣" in ctx["block"]
    assert all(u["type"] != "trip_state" for u in ctx["used"])


def test_memories_block_has_no_trip_label():
    class _M:
        id = "m1"
        type = "fact"
        key = "旅行足迹"
        content = "去过成都、厦门"
        updated_at = None

    block = format_memories_block([_M()])
    assert "记忆使用纪律" in block  # 纪律仍在（旅行足迹会带地名）
    assert "⚠️" not in block       # 过期警告随槽一起退役


# ---------- 确定性最近规划提示 ----------

def test_recent_plan_hint_from_other_conversation(db):
    _plan_msg(db, "c-old", "u1", "成都", days_ago=2)
    hint = recent_plan_hint(db, "u1", exclude_cid="c-now")
    assert "成都" in hint
    # 必须是待确认指代，不是事实断言
    assert "没有指明目的地" in hint
    assert "不代表本次的日期、预算或人数" in hint


def test_recent_plan_hint_excludes_current_conversation(db):
    _plan_msg(db, "c-now", "u1", "成都", days_ago=0)
    assert recent_plan_hint(db, "u1", exclude_cid="c-now") == ""


def test_recent_plan_hint_expires(db):
    _plan_msg(db, "c-old", "u1", "成都", days_ago=RECENT_PLAN_HINT_DAYS + 3)
    assert recent_plan_hint(db, "u1", exclude_cid="c-now") == ""


def test_recent_plan_hint_ignores_conversations_without_guide(db):
    _plan_msg(db, "c-chat", "u1", "成都", days_ago=1, with_sources=False)
    assert recent_plan_hint(db, "u1", exclude_cid="c-now") == ""


def test_recent_plan_hint_is_per_user(db):
    _plan_msg(db, "c-other", "u2", "成都", days_ago=1)
    assert recent_plan_hint(db, "u1", exclude_cid="c-now") == ""


def test_recent_plan_hint_empty_when_nothing(db):
    assert recent_plan_hint(db, "u1", exclude_cid="c-now") == ""


def test_recent_plan_hint_picks_newest(db):
    _plan_msg(db, "c-a", "u1", "成都", days_ago=5)
    _plan_msg(db, "c-b", "u1", "武汉", days_ago=1)
    hint = recent_plan_hint(db, "u1", exclude_cid="c-now")
    assert "武汉" in hint and "成都" not in hint
