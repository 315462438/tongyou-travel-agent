"""悬挂会话修复（部署重启杀死后台任务导致会话卡死）的单测。"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.chat_api import _is_running
from app.config import settings
from app.db.maintenance import INTERRUPTED_TEXT, repair_interrupted_conversations
from app.db.models import Base, TravelConversation, TravelMessage


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _msg(role, minutes_ago=0.0):
    ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes_ago)
    return TravelMessage(conversation_id="c", role=role, content="x", created_at=ts)


# ---------- running 判定 ----------

def test_running_fresh_progress():
    assert _is_running([_msg("user"), _msg("progress")]) is True


def test_not_running_after_assistant():
    assert _is_running([_msg("user"), _msg("assistant")]) is False
    assert _is_running([]) is False


def test_stale_progress_not_running():
    """后台任务被杀死：最后一条 progress 超过 turn_stale_min 分钟 → 不再视为运行中。"""
    stale = settings.turn_stale_min + 1
    assert _is_running([_msg("user", stale), _msg("progress", stale)]) is False


# ---------- 启动修复 ----------

def _seed(db, cid, roles):
    conv = TravelConversation(id=cid, title=cid)
    db.add(conv)
    for i, role in enumerate(roles):
        db.add(TravelMessage(
            conversation_id=cid, role=role, content="x",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(minutes=5) + timedelta(seconds=i),
        ))
    db.commit()


def test_repair_appends_interruption_message(db):
    _seed(db, "stuck", ["user", "progress", "progress"])
    _seed(db, "done", ["user", "progress", "assistant"])
    _seed(db, "empty", [])

    assert repair_interrupted_conversations(db) == 1

    from sqlalchemy import select
    last = db.execute(
        select(TravelMessage).where(TravelMessage.conversation_id == "stuck")
        .order_by(TravelMessage.created_at.desc()).limit(1)
    ).scalar_one()
    assert last.role == "assistant" and last.content == INTERRUPTED_TEXT
    # 已完成会话不动
    done_msgs = db.execute(
        select(TravelMessage).where(TravelMessage.conversation_id == "done")
    ).scalars().all()
    assert len(done_msgs) == 3
    # 幂等：再跑一次没有新修复
    assert repair_interrupted_conversations(db) == 0


def test_running_while_streaming():
    """流式生成中的 assistant 消息（meta.streaming）仍视为运行中。"""
    import json as _json
    m = _msg("assistant")
    m.meta_json = _json.dumps({"streaming": True})
    assert _is_running([m]) is True
    m.meta_json = None
    assert _is_running([m]) is False


def test_repair_finalizes_streaming_message(db):
    """被重启打断的流式消息：就地终稿（保留已生成内容 + 中断说明）。"""
    import json as _json
    _seed(db, "s", ["user"])
    db.add(TravelMessage(
        conversation_id="s", role="assistant", content="已生成的一半内容",
        meta_json=_json.dumps({"streaming": True}),
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    ))
    db.commit()
    assert repair_interrupted_conversations(db) == 1
    from sqlalchemy import select
    last = db.execute(
        select(TravelMessage).where(TravelMessage.conversation_id == "s")
        .order_by(TravelMessage.created_at.desc()).limit(1)
    ).scalar_one()
    assert last.meta_json is None
    assert "已生成的一半内容" in last.content and INTERRUPTED_TEXT in last.content
    assert repair_interrupted_conversations(db) == 0  # 幂等


def test_finalized_guide_with_trailing_progress_not_running():
    """反思循环 bug 回归：终稿 assistant 之后还有「正在自检」progress，
    不能因「最后一条是 progress」就一直显示运行中。"""
    import json as _json
    msgs = [_msg("user"), _msg("progress"), _msg("assistant"), _msg("progress")]
    msgs[2].meta_json = _json.dumps({"sources": [{"x": 1}]})  # 终稿 meta（非流式）
    assert _is_running(msgs) is False


def test_fresh_user_message_is_running():
    """刚发消息、后台任务刚起（user 后面还没任何回应）→ 运行中。"""
    assert _is_running([_msg("user")]) is True


def test_streaming_then_no_finalize_still_running():
    """生成中（流式 assistant，后面跟着自检 progress，尚未终稿）→ 运行中。"""
    import json as _json
    msgs = [_msg("user"), _msg("assistant"), _msg("progress")]
    msgs[1].meta_json = _json.dumps({"streaming": True})
    assert _is_running(msgs) is True


def test_poster_streaming_after_finalized_guide_is_running():
    """海报占位（流式 assistant）出现在已终稿攻略之后 → 仍算运行中（前端要接住海报）。"""
    import json as _json
    msgs = [_msg("user"), _msg("assistant"), _msg("assistant"), _msg("progress")]
    msgs[1].meta_json = _json.dumps({"sources": [{"x": 1}]})  # 终稿攻略
    msgs[2].meta_json = _json.dumps({"streaming": True})       # 海报流式占位
    assert _is_running(msgs) is True


def test_poster_finalized_is_done():
    """海报终稿（带 poster meta）后 → 完成。"""
    import json as _json
    msgs = [_msg("user"), _msg("assistant"), _msg("assistant")]
    msgs[1].meta_json = _json.dumps({"sources": [{"x": 1}]})
    msgs[2].meta_json = _json.dumps({"poster": {"title": "x"}})
    assert _is_running(msgs) is False


def test_clear_plain_progress(db):
    """终稿后清理本轮纯叙述 progress，保留 handoff/confirm（带 meta）与最终 assistant。"""
    import json as _json
    from app.agent.orchestrator import clear_plain_progress
    from app.db.session import get_session
    # 用真实 get_session 打桩为该测试 db
    import app.db.session as sess
    _seed(db, "c1", [])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add_all([
        TravelMessage(conversation_id="c1", role="user", content="去成都", created_at=now),
        TravelMessage(conversation_id="c1", role="progress", content="正在搜索", created_at=now + timedelta(seconds=1)),
        TravelMessage(conversation_id="c1", role="progress", content="需登录", meta_json=_json.dumps({"handoff": {"site": "x"}}), created_at=now + timedelta(seconds=2)),
        TravelMessage(conversation_id="c1", role="assistant", content="攻略", meta_json=_json.dumps({"sources": []}), created_at=now + timedelta(seconds=3)),
    ])
    db.commit()

    class Ctx:
        def __enter__(self): return db
        def __exit__(self, *a): pass
    import unittest.mock as mock
    with mock.patch.object(sess, "get_session", lambda: Ctx()):
        # orchestrator 里 from app.db.session import get_session 是模块级引用，需 patch 到位
        import app.agent.orchestrator as orch
        with mock.patch.object(orch, "get_session", lambda: Ctx()):
            clear_plain_progress("c1")
    from sqlalchemy import select
    rows = db.execute(select(TravelMessage).where(TravelMessage.conversation_id == "c1")).scalars().all()
    contents = [(m.role, m.content) for m in rows]
    assert ("progress", "正在搜索") not in contents  # 纯叙述被删
    assert ("progress", "需登录") in contents          # handoff 卡片保留
    assert ("assistant", "攻略") in contents


def test_repair_finds_streaming_placeholder_that_is_not_last(db):
    """2026-08-14 线上卡死：重复提交起两个并发轮，一个正常出稿、另一个留下流式占位，
    之后又落了 progress 和报错消息——最后一条不是流式的。

    旧实现只看最后一条，那条占位就永远挂着，`_is_running` 一直判运行中，
    输入框和停止按钮全锁死（用户只能靠手工改库解开）。
    """
    import json

    from sqlalchemy import select

    conv = TravelConversation(id="orphan", title="orphan")
    db.add(conv)
    base = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
    rows = [
        ("user", "问", None, 0),
        ("assistant", "正常出稿的攻略", None, 1),
        ("assistant", "", json.dumps({"streaming": True}), 2),   # ← 卡住的占位
        ("progress", "正在生成…", None, 3),
        ("assistant", "抱歉，处理过程中出错了", None, 4),        # 最后一条不是流式
    ]
    for role, content, meta, i in rows:
        db.add(TravelMessage(conversation_id="orphan", role=role, content=content,
                             meta_json=meta, created_at=base + timedelta(seconds=i)))
    db.commit()

    assert repair_interrupted_conversations(db) == 1

    stuck = db.execute(
        select(TravelMessage).where(TravelMessage.conversation_id == "orphan")
        .order_by(TravelMessage.created_at)
    ).scalars().all()[2]
    assert stuck.meta_json is None            # 不再是流式 → 前端解锁
    assert INTERRUPTED_TEXT in stuck.content
    # 不该因为「最后一条是 assistant」而再追加一条中断说明
    assert len(db.execute(
        select(TravelMessage).where(TravelMessage.conversation_id == "orphan")
    ).scalars().all()) == 5
    assert repair_interrupted_conversations(db) == 0  # 幂等


# ---------- 2026-08-14：续跑与用户重发冲突 ----------

def test_user_sent_after_detects_resend(db, monkeypatch):
    """用户 turn 之后又发了新 user 消息 → 判定为已重发（续跑应放弃）。"""
    from datetime import datetime, timedelta, timezone

    from app.db.maintenance import _user_sent_after

    monkeypatch.setattr("app.db.session.get_session", lambda: db)
    t0 = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(TravelConversation(id="c", title="c"))
    db.add(TravelMessage(conversation_id="c", role="user", content="a", created_at=t0))
    db.add(TravelMessage(conversation_id="c", role="user", content="b", created_at=t0 + timedelta(seconds=10)))
    db.commit()
    assert _user_sent_after("c", t0 + timedelta(seconds=5)) is True   # 重发了
    assert _user_sent_after("c", t0 + timedelta(seconds=20)) is False  # 之后没再发
    assert _user_sent_after("c", None) is False


def test_user_sent_after_ignores_progress(db, monkeypatch):
    """只有 user 消息才算重发——续跑自己的 progress 不算。"""
    from datetime import datetime, timedelta, timezone

    from app.db.maintenance import _user_sent_after

    monkeypatch.setattr("app.db.session.get_session", lambda: db)
    t0 = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(TravelConversation(id="c", title="c"))
    db.add(TravelMessage(conversation_id="c", role="user", content="a", created_at=t0))
    db.add(TravelMessage(conversation_id="c", role="progress", content="p", created_at=t0 + timedelta(seconds=10)))
    db.commit()
    assert _user_sent_after("c", t0 + timedelta(seconds=5)) is False
