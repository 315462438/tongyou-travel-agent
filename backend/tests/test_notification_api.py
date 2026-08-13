"""Phase 84：好友与接力通知、去重、已读和用户隔离。"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import notification_api, social_api
from app.db.models import Base, TravelNotification, TravelUser


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _user(db: Session, name: str) -> TravelUser:
    user = TravelUser(username=name, password_hash="x", profile_public=True)
    db.add(user)
    db.commit()
    return user


def test_friend_request_and_accept_notify_the_correct_side(db):
    alice = _user(db, "alice")
    bob = _user(db, "bob")

    relationship = social_api.request_friend(bob.id, db, alice)
    bob_feed = notification_api.list_notifications(40, db, bob)
    assert bob_feed["unread"] == 1
    assert bob_feed["notifications"][0]["type"] == "friend_request"
    assert bob_feed["notifications"][0]["actor"]["username"] == "alice"
    assert notification_api.list_notifications(40, db, alice)["notifications"] == []

    social_api.respond_friend(
        relationship["id"], social_api.FriendResponse(accept=True), db, bob,
    )
    assert notification_api.list_notifications(40, db, bob)["notifications"] == []
    alice_feed = notification_api.list_notifications(40, db, alice)
    assert alice_feed["unread"] == 1
    assert alice_feed["notifications"][0]["type"] == "friend_accepted"
    assert alice_feed["notifications"][0]["actor"]["username"] == "bob"


def test_relay_reaction_switches_one_notification_and_toggle_removes_it(db):
    alice = _user(db, "alice")
    bob = _user(db, "bob")
    post = social_api.create_post(social_api.RelayCreate(
        destination="天堂寨", phase="returned", kind="route", content="瀑布群路线实测",
    ), db, alice)

    social_api.react_post(
        post["id"], social_api.ReactionRequest(reaction="useful"), db, bob,
    )
    first = notification_api.list_notifications(40, db, alice)
    assert first["unread"] == 1
    assert first["notifications"][0]["meta"]["reaction"] == "useful"
    first_id = first["notifications"][0]["id"]

    social_api.react_post(
        post["id"], social_api.ReactionRequest(reaction="verified"), db, bob,
    )
    switched = notification_api.list_notifications(40, db, alice)
    assert len(switched["notifications"]) == 1
    assert switched["notifications"][0]["id"] == first_id
    assert switched["notifications"][0]["meta"]["reaction"] == "verified"

    social_api.react_post(
        post["id"], social_api.ReactionRequest(reaction="verified"), db, bob,
    )
    assert notification_api.list_notifications(40, db, alice)["notifications"] == []


def test_read_endpoints_are_persistent_and_user_scoped(db):
    alice = _user(db, "alice")
    bob = _user(db, "bob")
    notification_api.upsert_notification(
        db, user_id=alice.id, actor_id=bob.id, type="friend_request",
        title="Bob 想加你为好友", body="", target_kind="friends", target_id=bob.id,
        dedupe_key=f"manual:{alice.id}:{bob.id}", meta={},
    )
    db.commit()
    row = db.query(TravelNotification).one()

    with pytest.raises(HTTPException) as exc:
        notification_api.read_notification(row.id, db, bob)
    assert exc.value.status_code == 404

    notification_api.read_notification(row.id, db, alice)
    assert notification_api.unread_count(db, alice)["unread"] == 0
    assert notification_api.list_notifications(40, db, alice)["notifications"][0]["read"] is True

    notification_api.upsert_notification(
        db, user_id=alice.id, actor_id=bob.id, type="relay_reaction",
        title="又一条", body="", target_kind="relay", target_id="post",
        dedupe_key=f"manual-2:{alice.id}:{bob.id}", meta={},
    )
    db.commit()
    assert notification_api.unread_count(db, alice)["unread"] == 1
    notification_api.read_all_notifications(db, alice)
    assert notification_api.unread_count(db, alice)["unread"] == 0
