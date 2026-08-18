"""群聊消息进通知中心（Phase 97）单测。sqlite 全离线。

关切：群聊消息此前只在行程板内部有未读徽标，人不进那个页面就永远不知道有人说话。
现在同事务写进 Phase 84 的通知中心，主页铃铛可见。
"""

from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, TravelNotification, TravelTripChatMessage, TravelUser


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)

    @contextmanager
    def fake_session():
        db = maker()
        try:
            yield db
        finally:
            db.close()

    import app.api.notification_api as notif_api
    import app.api.trip_api as api

    monkeypatch.setattr(api, "get_session", fake_session)

    async def fake_geocode(names, city, **kwargs):
        return {n: "116.10,39.90" for n in names}

    monkeypatch.setattr("app.agent.trip_planner.geocode_names", fake_geocode)

    app = FastAPI()
    app.include_router(api.router)
    app.include_router(notif_api.router)

    from app.api.deps import get_current_user
    from app.db.session import get_db

    with maker() as db:
        db.add_all([
            TravelUser(id="ua", username="alice", password_hash="x", display_name="爱丽丝"),
            TravelUser(id="ub", username="bob", password_hash="x"),
            TravelUser(id="uc", username="carol", password_hash="x"),
            TravelUser(id="ud", username="dave", password_hash="x"),
        ])
        db.commit()

    current = {"id": "ua"}

    def fake_user():
        with maker() as db:
            return db.get(TravelUser, current["id"])

    def fake_db():
        db = maker()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_db] = fake_db
    return TestClient(app), current, maker


def _trip_with_members(c, current, *, accept=("ub", "uc"), invite=("ub", "uc")):
    """alice 建行程并邀请，指定的人接受邀请。返回 trip_id。"""
    current["id"] = "ua"
    trip_id = c.post("/api/trips", json={
        "title": "吉隆坡8天", "destination": "吉隆坡", "days": 8,
    }).json()["id"]
    name = {"ub": "bob", "uc": "carol", "ud": "dave"}
    for uid in invite:
        c.post(f"/api/trips/{trip_id}/invite", json={"username": name[uid]})
    for uid in accept:
        current["id"] = uid
        c.post(f"/api/trips/{trip_id}/invites/respond", json={"accept": True})
    current["id"] = "ua"
    return trip_id


def _notifs(maker, user_id: str) -> list[TravelNotification]:
    with maker() as db:
        return list(db.execute(select(TravelNotification).where(
            TravelNotification.user_id == user_id,
        )).scalars().all())


# ---------- 核心：谁收到、收到几条 ----------

def test_message_notifies_other_members_but_not_the_sender(client):
    c, current, maker = client
    trip_id = _trip_with_members(c, current)

    assert c.post(f"/api/trips/{trip_id}/chat", json={"content": "左边这个已花费7220是怎么定义的"}).status_code == 200

    for uid in ("ub", "uc"):
        rows = _notifs(maker, uid)
        assert len(rows) == 1, f"{uid} 应收到 1 条通知"
        assert rows[0].type == "trip_chat"
        assert rows[0].target_kind == "trip" and rows[0].target_id == trip_id
        assert "爱丽丝" in rows[0].title and "吉隆坡8天" in rows[0].title
        assert "已花费7220" in rows[0].body
        assert rows[0].read_at is None
    assert _notifs(maker, "ua") == [], "发送者不该给自己发通知"


def test_burst_of_messages_collapses_into_one_notification(client):
    """一个行程刷 20 条消息不能把铃铛冲爆——每人只有一条通知在刷新。"""
    c, current, maker = client
    trip_id = _trip_with_members(c, current)

    for i in range(3):
        c.post(f"/api/trips/{trip_id}/chat", json={"content": f"第{i}条"})

    rows = _notifs(maker, "ub")
    assert len(rows) == 1
    import json
    assert json.loads(rows[0].meta_json)["count"] == 3
    assert "第2条" in rows[0].body  # 展示最新一条


def test_count_resets_after_read(client):
    """读过之后再来消息，是新一轮未读（count 从 1 重新数）。"""
    import json

    c, current, maker = client
    trip_id = _trip_with_members(c, current)
    c.post(f"/api/trips/{trip_id}/chat", json={"content": "a"})
    c.post(f"/api/trips/{trip_id}/chat", json={"content": "b"})

    current["id"] = "ub"
    assert c.post(f"/api/trips/{trip_id}/chat/read").status_code == 200
    assert _notifs(maker, "ub")[0].read_at is not None

    current["id"] = "ua"
    c.post(f"/api/trips/{trip_id}/chat", json={"content": "c"})
    row = _notifs(maker, "ub")[0]
    assert row.read_at is None, "新消息要让通知回到未读"
    assert json.loads(row.meta_json)["count"] == 1


def test_pending_invitee_gets_no_notification(client):
    """待接受邀请的人看不到行程内容，也不该收到群聊通知。"""
    c, current, maker = client
    trip_id = _trip_with_members(c, current, accept=("ub",), invite=("ub", "uc"))

    c.post(f"/api/trips/{trip_id}/chat", json={"content": "hi"})

    assert len(_notifs(maker, "ub")) == 1
    assert _notifs(maker, "uc") == [], "pending 成员不该收到"
    assert _notifs(maker, "ud") == [], "非成员不该收到"


# ---------- 已读只影响自己 ----------

def test_mark_read_only_affects_the_caller(client):
    c, current, maker = client
    trip_id = _trip_with_members(c, current)
    c.post(f"/api/trips/{trip_id}/chat", json={"content": "hi"})

    current["id"] = "ub"
    c.post(f"/api/trips/{trip_id}/chat/read")

    assert _notifs(maker, "ub")[0].read_at is not None
    assert _notifs(maker, "uc")[0].read_at is None, "carol 的未读不该被 bob 清掉"


def test_mark_read_requires_membership(client):
    c, current, _ = client
    trip_id = _trip_with_members(c, current)
    current["id"] = "ud"  # 非成员
    assert c.post(f"/api/trips/{trip_id}/chat/read").status_code == 404


# ---------- 撤销语义 ----------

def test_deleting_the_trip_revokes_notifications(client):
    """行程没了，指向它的通知也要撤销，否则点开会跳到一个 404 的行程。"""
    c, current, maker = client
    trip_id = _trip_with_members(c, current)
    c.post(f"/api/trips/{trip_id}/chat", json={"content": "hi"})
    assert _notifs(maker, "ub")

    current["id"] = "ua"
    assert c.delete(f"/api/trips/{trip_id}").status_code == 200
    assert _notifs(maker, "ub") == []
    assert _notifs(maker, "uc") == []


def test_deleting_one_message_does_not_revoke_the_notification(client):
    """**有意决策**：删掉一条消息不撤销通知。

    「有人说过话」这件事仍然成立；撤销要判断被删的是不是最新一条、要不要回退 count，
    复杂度换不来价值。（与 Phase 84「取消反馈时撤销」不同：那里事件本身被取消了。）
    """
    c, current, maker = client
    trip_id = _trip_with_members(c, current)
    msg_id = c.post(f"/api/trips/{trip_id}/chat", json={"content": "hi"}).json()["id"]

    assert c.delete(f"/api/trips/{trip_id}/chat/{msg_id}").status_code == 200
    assert len(_notifs(maker, "ub")) == 1


# ---------- 同事务 ----------

def test_notification_failure_rolls_back_the_message(client, monkeypatch):
    """通知与消息必须同事务：写通知炸了，消息也不能落库。

    见 docs/pitfalls/事件通知必须与业务同事务且按事件去重.md ——
    一半成功一半失败比两者都失败更难查。
    """
    c, current, maker = client
    trip_id = _trip_with_members(c, current)

    import app.api.notification_api as notif_api

    def boom(*args, **kwargs):
        raise RuntimeError("通知写入失败")

    monkeypatch.setattr(notif_api, "upsert_notification", boom)

    with pytest.raises(RuntimeError):
        c.post(f"/api/trips/{trip_id}/chat", json={"content": "不该落库"})

    with maker() as db:
        rows = db.execute(select(TravelTripChatMessage).where(
            TravelTripChatMessage.trip_id == trip_id,
        )).scalars().all()
    assert rows == [], "通知失败时消息不该留下"


# ---------- 铃铛未读 ----------

def test_bell_unread_counts_trip_chat(client):
    """主页铃铛的未读数要把群聊算进去——这正是本次改动的目的。"""
    c, current, _ = client
    trip_id = _trip_with_members(c, current)
    c.post(f"/api/trips/{trip_id}/chat", json={"content": "hi"})

    current["id"] = "ub"
    assert c.get("/api/notifications/unread-count").json()["unread"] == 1

    listed = c.get("/api/notifications").json()
    assert listed["unread"] == 1
    item = listed["notifications"][0]
    assert item["type"] == "trip_chat"
    assert item["target_kind"] == "trip" and item["target_id"] == trip_id
    assert item["meta"]["trip_id"] == trip_id

    c.post(f"/api/trips/{trip_id}/chat/read")
    assert c.get("/api/notifications/unread-count").json()["unread"] == 0


def test_empty_message_writes_nothing(client):
    c, current, maker = client
    trip_id = _trip_with_members(c, current)
    assert c.post(f"/api/trips/{trip_id}/chat", json={"content": "   "}).status_code == 400
    assert _notifs(maker, "ub") == []
