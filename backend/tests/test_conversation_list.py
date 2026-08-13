"""会话列表按最后活跃时间排序/分组（用户反馈：老会话今天还在用却分到「前 7 天」）"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.chat_api import list_conversations
from app.db.models import Base, TravelConversation, TravelMessage, TravelUser


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _now(days_ago=0.0):
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_ago)


_U = TravelUser(id="u1", username="u1", password_hash="x")


def test_last_message_time_wins(db):
    # 老会话（3 天前创建）今天有新消息 → updated_at 应反映今天
    old = TravelConversation(id="old", user_id="u1", title="老会话", updated_at=_now(3))
    fresh = TravelConversation(id="fresh", user_id="u1", title="新会话但没动静", updated_at=_now(1))
    other = TravelConversation(id="other", user_id="u2", title="别人的", updated_at=_now(0))
    db.add_all([old, fresh, other])
    db.add(TravelMessage(conversation_id="old", role="user", content="x", created_at=_now(0)))
    db.commit()

    out = list_conversations(db, _U)
    assert [c["id"] for c in out] == ["old", "fresh"]  # 只含本人、今天活跃的排最前
    today = _now(0).date().isoformat()
    assert out[0]["updated_at"].startswith(today)


def test_conversation_without_messages_falls_back(db):
    db.add(TravelConversation(id="empty", user_id="u1", title="空会话", updated_at=_now(2)))
    db.commit()
    out = list_conversations(db, _U)
    assert out[0]["id"] == "empty" and out[0]["updated_at"]
