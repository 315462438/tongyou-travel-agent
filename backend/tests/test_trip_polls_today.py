"""同行人投票 + 出行当天首页（2026-11-10）。复用协作模块的 sqlite 夹具。"""
import pytest

from tests.test_trip_modules import client, trip  # noqa: F401 — pytest fixtures


def _poll(c, trip, **kw):
    return c.post(f"/api/trips/{trip}/polls", json={"question": "住哪家", "options": ["A 酒店", "B 民宿"], **kw})


def test_poll_vote_change_and_tally(client, trip):
    c, current = client
    poll = _poll(c, trip).json()
    assert [o["text"] for o in poll["options"]] == ["A 酒店", "B 民宿"] and poll["members"] == 2
    pid = poll["id"]
    c.post(f"/api/trips/{trip}/polls/{pid}/vote", json={"option": 0})
    current["id"] = "ub"
    r = c.post(f"/api/trips/{trip}/polls/{pid}/vote", json={"option": 0}).json()
    assert r["options"][0]["votes"] == 2 and r["my_vote"] == 0
    r = c.post(f"/api/trips/{trip}/polls/{pid}/vote", json={"option": 1}).json()   # 改票：不是多投一票
    assert [o["votes"] for o in r["options"]] == [1, 1] and r["total"] == 2
    assert r["options"][1]["voters"] == ["bob"]


def test_poll_validation(client, trip):
    c, _ = client
    assert c.post(f"/api/trips/{trip}/polls", json={"question": "去哪", "options": ["A", "A"]}).status_code == 400
    assert c.post(f"/api/trips/{trip}/polls", json={"question": " ", "options": ["A", "B"]}).status_code == 400
    assert c.post(f"/api/trips/{trip}/polls", json={"question": "q", "options": list("ABCDE")}).status_code == 400
    pid = _poll(c, trip).json()["id"]
    assert c.post(f"/api/trips/{trip}/polls/{pid}/vote", json={"option": 5}).status_code == 400


def test_poll_members_only_and_close_rights(client, trip):
    c, current = client
    pid = _poll(c, trip).json()["id"]
    current["id"] = "uc"   # 不在行程里
    assert c.get(f"/api/trips/{trip}/polls").status_code == 404
    assert c.post(f"/api/trips/{trip}/polls/{pid}/vote", json={"option": 0}).status_code == 404
    current["id"] = "ub"
    pid2 = _poll(c, trip).json()["id"]                                   # bob 发起的
    assert c.post(f"/api/trips/{trip}/polls/{pid}/close").status_code == 403    # 不是发起人也不是 owner
    current["id"] = "ua"
    assert c.post(f"/api/trips/{trip}/polls/{pid2}/close").json()["closed"] is True   # owner 可以结束别人的
    assert c.post(f"/api/trips/{trip}/polls/{pid2}/vote", json={"option": 0}).status_code == 400
    assert c.delete(f"/api/trips/{trip}/polls/{pid}").json() == {"ok": True}
    assert [p["id"] for p in c.get(f"/api/trips/{trip}/polls").json()] == [pid2]


def test_poll_notifies_other_members_once(client, trip):
    from sqlalchemy import select
    from app.api.deps import get_current_user  # noqa: F401
    from app.db.models import TravelNotification
    from app.db.session import get_db

    c, _ = client
    _poll(c, trip)
    db = next(c.app.dependency_overrides[get_db]())
    rows = db.execute(select(TravelNotification).where(TravelNotification.type == "trip_poll")).scalars().all()
    assert [r.user_id for r in rows] == ["ub"]      # 不通知发起人自己


def test_today_returns_current_day_stops(client, trip):
    c, _ = client
    c.patch(f"/api/trips/{trip}", json={"start_date": "2026-11-09"})
    c.post(f"/api/trips/{trip}/stops", json={"day": 1, "name": "第一天的点", "location": "114.3,34.8"})
    c.post(f"/api/trips/{trip}/stops", json={"day": 2, "name": "清明上河园", "location": "114.33,34.81"})
    r = c.get("/api/trips/today", params={"date": "2026-11-10"}).json()["trip"]
    assert r["id"] == trip and r["day"] == 2 and r["days"] == 2
    assert [s["name"] for s in r["stops"]] == ["清明上河园"] and r["stops"][0]["nav"]["amap"]


@pytest.mark.parametrize("today,expect", [
    ("2026-11-06", {"starts_in": 3}),   # 3 天后出发：给倒计时
    ("2026-11-11", None),               # 已结束
    ("2026-10-20", None),               # 太早
])
def test_today_upcoming_and_none(client, trip, today, expect):
    c, _ = client
    c.patch(f"/api/trips/{trip}", json={"start_date": "2026-11-09"})
    r = c.get("/api/trips/today", params={"date": today}).json()["trip"]
    if expect is None:
        assert r is None
    else:
        assert r["starts_in"] == expect["starts_in"] and "stops" not in r


def test_today_ignores_trips_without_dates_and_other_users(client, trip):
    c, current = client
    assert c.get("/api/trips/today", params={"date": "2026-11-10"}).json() == {"trip": None}
    c.patch(f"/api/trips/{trip}", json={"start_date": "2026-11-10"})
    current["id"] = "uc"
    assert c.get("/api/trips/today", params={"date": "2026-11-10"}).json() == {"trip": None}


def test_create_trip_with_start_date_shows_on_today(client):
    c, _ = client
    tid = c.post("/api/trips", json={"title": "杭州", "days": 2, "start_date": "2026-11-10"}).json()["id"]
    assert c.get("/api/trips/today", params={"date": "2026-11-10"}).json()["trip"]["id"] == tid
    bad = c.post("/api/trips", json={"title": "乱填", "start_date": "明天"})      # 格式不对：照常建，只是没日期
    assert bad.status_code == 200 and c.get(f"/api/trips/{bad.json()['id']}").json()["start_date"] == ""



def test_poll_belongs_to_a_day_or_the_whole_trip(client, trip):
    c, _ = client
    assert _poll(c, trip, day=2).json()["day"] == 2
    assert _poll(c, trip).json()["day"] is None                 # 不填 = 整趟行程
    assert _poll(c, trip, day=9).json()["day"] is None          # 行程只有 2 天：越界不报错，归到整趟
    assert sorted(p["day"] or 0 for p in c.get(f"/api/trips/{trip}/polls").json()) == [0, 0, 2]


def test_day_poll_notification_names_the_day(client, trip):
    from sqlalchemy import select
    from app.db.models import TravelNotification
    from app.db.session import get_db

    c, _ = client
    _poll(c, trip, day=2)
    db = next(c.app.dependency_overrides[get_db]())
    row = db.execute(select(TravelNotification).where(TravelNotification.type == "trip_poll")).scalars().one()
    assert row.body.startswith("第 2 天：")


@pytest.mark.parametrize("day", [None, 2])
def test_poll_notification_api_preserves_destination_and_read_state(client, trip, day):
    from app.api.notification_api import router
    c, current = client
    c.app.include_router(router)
    poll = _poll(c, trip, day=day).json()
    assert c.get("/api/notifications").json()["notifications"] == []
    current["id"] = "ub"
    notice, = c.get("/api/notifications").json()["notifications"]
    assert notice["type"] == "trip_poll" and notice["target_kind"] == "trip"
    assert notice["target_id"] == trip
    assert notice["meta"]["trip_id"] == trip and notice["meta"]["poll_id"] == poll["id"]
    assert notice["meta"]["day"] == day
    assert c.post(f"/api/notifications/{notice['id']}/read").status_code == 200
    read, = c.get("/api/notifications").json()["notifications"]
    assert read["read"] is True and read["meta"] == notice["meta"]
    current["id"] = "uc"
    assert c.get("/api/notifications").json()["notifications"] == []
    assert c.get(f"/api/trips/{trip}/polls").status_code == 404
