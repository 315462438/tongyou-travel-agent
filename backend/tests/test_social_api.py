"""Phase 81：接力站、好友状态机与个人主页。全部离线 SQLite。"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import social_api
from app.db.models import Base, TravelRelayPost, TravelUpload, TravelUser


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _user(db: Session, name: str, public: bool = True) -> TravelUser:
    row = TravelUser(username=name, password_hash="x", profile_public=public)
    db.add(row)
    db.commit()
    return row


def test_profile_update_only_binds_own_upload_and_never_exposes_password(db):
    alice = _user(db, "alice")
    bob = _user(db, "bob")
    own = TravelUpload(user_id=alice.id, mime="image/png", size=12)
    other = TravelUpload(user_id=bob.id, mime="image/png", size=12)
    db.add_all([own, other])
    db.commit()

    out = social_api.update_profile(social_api.ProfileUpdate(
        display_name=" Alice 的旅行簿 ", bio="喜欢山野", home_city="武汉",
        travel_styles=["户外徒步", "户外徒步", "摄影打卡"], profile_public=True,
        avatar_upload_id=own.id,
    ), db, alice)
    assert out["display_name"] == "Alice 的旅行簿"
    assert out["travel_styles"] == ["户外徒步", "摄影打卡"]
    assert out["avatar_url"].endswith(own.id)
    assert "password_hash" not in out
    assert "is_admin" not in out

    with pytest.raises(HTTPException) as exc:
        social_api.update_profile(social_api.ProfileUpdate(
            display_name="Alice", avatar_upload_id=other.id,
        ), db, alice)
    assert exc.value.status_code == 400


def test_friend_request_accept_remove_and_duplicate_guards(db):
    alice = _user(db, "alice")
    bob = _user(db, "bob")

    created = social_api.request_friend(bob.id, db, alice)
    assert created["status"] == "pending"
    with pytest.raises(HTTPException) as duplicate:
        social_api.request_friend(bob.id, db, alice)
    assert duplicate.value.status_code == 409
    with pytest.raises(HTTPException):
        social_api.request_friend(alice.id, db, alice)

    received = social_api.list_friends(db, bob)
    assert received["received"][0]["username"] == "alice"
    accepted = social_api.respond_friend(created["id"], social_api.FriendResponse(accept=True), db, bob)
    assert accepted["status"] == "accepted"
    assert social_api.my_profile(db, alice)["stats"]["friends"] == 1
    assert social_api.my_profile(db, bob)["stats"]["friends"] == 1

    social_api.remove_friend(created["id"], db, alice)
    assert social_api.list_friends(db, alice)["friends"] == []


def test_requester_cannot_accept_own_friend_request(db):
    alice = _user(db, "alice")
    bob = _user(db, "bob")
    created = social_api.request_friend(bob.id, db, alice)
    with pytest.raises(HTTPException) as exc:
        social_api.respond_friend(created["id"], social_api.FriendResponse(accept=True), db, alice)
    assert exc.value.status_code == 409


def test_private_profile_is_not_searchable_but_friend_can_open_it(db):
    alice = _user(db, "alice")
    bob = _user(db, "bob", public=False)
    social_api.create_post(social_api.RelayCreate(
        destination="武汉", phase="returned", kind="route", content="东湖骑行路线复盘",
    ), db, bob)
    assert social_api.search_users("bob", db, alice)["users"] == []
    hidden_station = social_api.station("武汉", "", db, alice)
    assert hidden_station["posts"] == []
    assert hidden_station["phase_counts"]["returned"] == 0
    with pytest.raises(HTTPException) as exc:
        social_api.public_profile(bob.id, db, alice)
    assert exc.value.status_code == 404

    bob.profile_public = True
    db.commit()
    request = social_api.request_friend(bob.id, db, alice)
    social_api.respond_friend(request["id"], social_api.FriendResponse(accept=True), db, bob)
    bob.profile_public = False
    db.commit()
    profile = social_api.public_profile(bob.id, db, alice)
    assert profile["username"] == "bob"
    assert profile["recent_relay"][0]["destination"] == "武汉"


def test_relay_post_condition_expires_and_reaction_is_single_choice(db):
    alice = _user(db, "alice")
    bob = _user(db, "bob")
    post = social_api.create_post(social_api.RelayCreate(
        destination="天堂寨", phase="on_trip", kind="condition",
        content="白马大峡谷刚下过雨，栈道比较滑。",
    ), db, alice)
    assert post["expires_at"] is not None
    assert post["expired"] is False
    assert social_api.station("天堂寨", "", db, bob)["phase_counts"]["on_trip"] == 1

    verified = social_api.react_post(post["id"], social_api.ReactionRequest(reaction="verified"), db, bob)
    assert verified["reactions"]["verified"] == 1
    changed = social_api.react_post(post["id"], social_api.ReactionRequest(reaction="useful"), db, bob)
    assert changed["reactions"]["verified"] == 0
    assert changed["reactions"]["useful"] == 1
    removed = social_api.react_post(post["id"], social_api.ReactionRequest(reaction="useful"), db, bob)
    assert removed["reactions"]["useful"] == 0

    with pytest.raises(HTTPException):
        social_api.react_post(post["id"], social_api.ReactionRequest(reaction="verified"), db, alice)


def test_only_author_can_delete_relay_post(db):
    alice = _user(db, "alice")
    bob = _user(db, "bob")
    post = social_api.create_post(social_api.RelayCreate(
        destination="杭州", phase="returned", kind="route", content="西湖半日路线复盘",
    ), db, alice)
    with pytest.raises(HTTPException) as exc:
        social_api.delete_post(post["id"], db, bob)
    assert exc.value.status_code == 404
    social_api.delete_post(post["id"], db, alice)
    assert db.get(TravelRelayPost, post["id"]) is None


def test_relay_enums_are_rejected(db):
    alice = _user(db, "alice")
    with pytest.raises(HTTPException):
        social_api.create_post(social_api.RelayCreate(
            destination="武汉", phase="live_location", kind="condition", content="x" * 10,
        ), db, alice)
    with pytest.raises(HTTPException):
        social_api.create_post(social_api.RelayCreate(
            destination="武汉", phase="planning", kind="private_message", content="x" * 10,
        ), db, alice)
