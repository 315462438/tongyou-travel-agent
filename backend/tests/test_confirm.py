"""登录来源确认交互（Phase 7）单测。sqlite 内存库，全部离线。"""

import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent import confirm as confirm_mod
from app.agent.confirm import find_confirm_reply, wait_confirm
from app.api.chat_api import _is_running
from app.db.models import Base, TravelMessage


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _reply(db, cid, confirm_id, choice):
    db.add(TravelMessage(
        conversation_id=cid, role="action", content="",
        meta_json=json.dumps({"confirm_reply": {"confirm_id": confirm_id, "choice": choice}}),
    ))
    db.commit()


def test_find_confirm_reply(db):
    assert find_confirm_reply(db, "c1", "cf1") is None
    _reply(db, "c1", "cf1", "login")
    assert find_confirm_reply(db, "c1", "cf1") == "login"
    assert find_confirm_reply(db, "c1", "other") is None  # 不同 confirm_id 不串
    assert find_confirm_reply(db, "c2", "cf1") is None  # 不同会话不串


def test_wait_confirm_returns_choice(db, monkeypatch):
    """轮询期间用户点击 → 返回选择。"""
    _reply(db, "c1", "cf1", "skip")

    class FakeCtx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            pass

    monkeypatch.setattr("app.db.session.get_session", lambda: FakeCtx())

    async def no_sleep(_):
        pass

    monkeypatch.setattr(confirm_mod.asyncio, "sleep", no_sleep)
    assert asyncio.run(wait_confirm("c1", "cf1", timeout_s=10, poll_s=1)) == "skip"


def test_wait_confirm_timeout_defaults_to_skip(db, monkeypatch):
    class FakeCtx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            pass

    monkeypatch.setattr("app.db.session.get_session", lambda: FakeCtx())

    async def no_sleep(_):
        pass

    monkeypatch.setattr(confirm_mod.asyncio, "sleep", no_sleep)
    assert asyncio.run(wait_confirm("c1", "cf-none", timeout_s=6, poll_s=2)) == "skip"


def test_action_message_counts_as_running():
    """用户刚点完按钮（最后一条是 action）：后台仍在处理，running 必须为 true。"""
    from datetime import datetime, timezone

    msg = TravelMessage(
        conversation_id="c", role="action", content="",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    assert _is_running([msg]) is True
