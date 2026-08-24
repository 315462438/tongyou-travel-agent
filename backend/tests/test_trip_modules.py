"""协同行程协作模块（Phase 87）：美食 / 行李 / 避坑。

sqlite 内存库 + TestClient，全离线。重点验证成员隔离、三态并发不互相覆盖、
以及代勾留痕（谁替谁勾的）。
"""

from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, TravelUser


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

    import app.api.trip_api as api
    import app.api.trip_modules_api as mod

    monkeypatch.setattr(api, "get_session", fake_session)

    async def fake_geocode(names, city, **kwargs):
        return {n: "116.10,39.90" for n in names}

    monkeypatch.setattr("app.agent.trip_planner.geocode_names", fake_geocode)

    app = FastAPI()
    app.include_router(api.router)
    app.include_router(mod.router)

    with maker() as db:
        db.add_all([
            TravelUser(id="ua", username="alice", password_hash="x"),
            TravelUser(id="ub", username="bob", password_hash="x"),
            TravelUser(id="uc", username="carol", password_hash="x"),
        ])
        db.commit()

    current = {"id": "ua"}

    from app.api.deps import get_current_user
    from app.db.session import get_db

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
    return TestClient(app), current


@pytest.fixture()
def trip(client):
    """alice 建行程并拉 bob 进来（carol 不在）。"""
    c, current = client
    tid = c.post("/api/trips", json={"title": "开封两日", "destination": "开封", "days": 2}).json()["id"]
    c.post(f"/api/trips/{tid}/invite", json={"username": "bob"})
    current["id"] = "ub"
    c.post(f"/api/trips/{tid}/invites/respond", json={"accept": True})
    current["id"] = "ua"
    return tid


# ---------- 模块 2：美食 ----------

def test_food_crud_and_top_ordering(client, trip):
    c, _ = client
    c.post(f"/api/trips/{trip}/foods", json={
        "name": "第一楼灌汤包", "day": 1, "meal_type": "午餐", "category": "正餐",
        "price": 45, "rating": 4.7, "address": "鼓楼附近",
        "business_hours": "10:00-21:00", "recommend_food": ["灌汤包", "鲤鱼焙面"],
        "is_favorite": True,
    })
    top = c.post(f"/api/trips/{trip}/foods",
                 json={"name": "黄家老店", "category": "小吃", "is_top": True}).json()
    rows = c.get(f"/api/trips/{trip}/foods").json()
    assert [r["name"] for r in rows] == ["黄家老店", "第一楼灌汤包"]  # TOP 置顶
    assert rows[0]["is_top"] is True and rows[1]["price"] == 45
    assert rows[1]["day"] == 1 and rows[1]["meal_type"] == "午餐"
    assert rows[1]["rating"] == 4.7 and rows[1]["address"] == "鼓楼附近"
    assert rows[1]["business_hours"] == "10:00-21:00"
    assert rows[1]["recommend_food"] == ["灌汤包", "鲤鱼焙面"]
    assert rows[1]["is_favorite"] is True
    assert rows[0]["city"] == "开封"  # 未填城市时回落行程目的地

    c.patch(f"/api/trips/{trip}/foods/{top['id']}", json={"name": "黄家老店", "category": "小吃",
                                                          "note": "排队久", "checked_in": True, "is_top": False})
    rows = c.get(f"/api/trips/{trip}/foods").json()
    assert [r["name"] for r in rows] == ["第一楼灌汤包", "黄家老店"]  # 取消 TOP 后回到时间序
    assert rows[1]["checked_in"] is True and rows[1]["status"] == "checked_in"

    assert c.delete(f"/api/trips/{trip}/foods/{top['id']}").status_code == 200
    assert len(c.get(f"/api/trips/{trip}/foods").json()) == 1


def test_food_rejects_blank_name(client, trip):
    c, _ = client
    assert c.post(f"/api/trips/{trip}/foods", json={"name": "   "}).status_code == 400


def test_food_isolated_to_members(client, trip):
    """非成员一律 404（不泄露行程存在性，同 trip_api 既有约定）。"""
    c, current = client
    c.post(f"/api/trips/{trip}/foods", json={"name": "灌汤包"})
    current["id"] = "uc"  # carol 不在这个行程
    assert c.get(f"/api/trips/{trip}/foods").status_code == 404
    assert c.post(f"/api/trips/{trip}/foods", json={"name": "偷加的"}).status_code == 404


def test_food_cross_trip_id_mismatch_is_404(client, trip):
    """带着 A 行程的 id 去 B 行程的路径下操作，必须 404。"""
    c, _ = client
    other = c.post("/api/trips", json={"title": "别的", "destination": "洛阳", "days": 1}).json()["id"]
    fid = c.post(f"/api/trips/{trip}/foods", json={"name": "灌汤包"}).json()["id"]
    assert c.delete(f"/api/trips/{other}/foods/{fid}").status_code == 404


# ---------- 模块 6：行李三态 ----------

def test_packing_grid_is_per_member(client, trip):
    c, current = client
    body = c.get(f"/api/trips/{trip}/packing").json()
    assert set(body["members"]) == {"alice", "bob"} and "充电宝" in body["templates"]

    item = c.post(f"/api/trips/{trip}/packing", json={"name": "充电宝"}).json()
    c.put(f"/api/trips/{trip}/packing/{item['id']}/state", json={"state": "packed"})
    current["id"] = "ub"
    c.put(f"/api/trips/{trip}/packing/{item['id']}/state", json={"state": "unpacked"})

    grid = c.get(f"/api/trips/{trip}/packing").json()["items"][0]["states"]
    # 两人各自一格，互不覆盖——这正是不用 item 上挂 JSON 的原因
    assert grid == {"alice": "packed", "bob": "unpacked"}


def test_can_mark_on_behalf_of_another_member(client, trip):
    """允许代勾：出发前一个人拿着清单统一核对是真实场景。"""
    c, _ = client
    item = c.post(f"/api/trips/{trip}/packing", json={"name": "护照"}).json()
    r = c.put(f"/api/trips/{trip}/packing/{item['id']}/state",
              json={"state": "packed", "member": "bob"})
    assert r.status_code == 200 and r.json()["by_other"] is True
    row = c.get(f"/api/trips/{trip}/packing").json()["items"][0]
    assert row["states"] == {"bob": "packed"}
    # 留痕：被代勾的人能看到是谁改的
    assert row["marked_by"] == {"bob": "alice"}


def test_self_marking_leaves_no_proxy_mark(client, trip):
    """自己勾自己是常态，不该显示「由 X 代勾」。"""
    c, _ = client
    item = c.post(f"/api/trips/{trip}/packing", json={"name": "耳机"}).json()
    c.put(f"/api/trips/{trip}/packing/{item['id']}/state", json={"state": "packed"})
    row = c.get(f"/api/trips/{trip}/packing").json()["items"][0]
    assert row["states"] == {"alice": "packed"} and row["marked_by"] == {}


def test_cannot_mark_for_a_non_member(client, trip):
    c, _ = client
    item = c.post(f"/api/trips/{trip}/packing", json={"name": "登机牌"}).json()
    r = c.put(f"/api/trips/{trip}/packing/{item['id']}/state",
              json={"state": "packed", "member": "carol"})
    assert r.status_code == 400


def test_packing_state_cycles_and_validates(client, trip):
    c, _ = client
    item = c.post(f"/api/trips/{trip}/packing", json={"name": "雨伞"}).json()
    for st in ("packed", "unpacked", "na"):
        assert c.put(f"/api/trips/{trip}/packing/{item['id']}/state",
                     json={"state": st}).json()["state"] == st
    assert c.put(f"/api/trips/{trip}/packing/{item['id']}/state",
                 json={"state": "hacked"}).status_code == 400


def test_packing_delete_removes_states(client, trip):
    c, _ = client
    item = c.post(f"/api/trips/{trip}/packing", json={"name": "转换插头"}).json()
    c.put(f"/api/trips/{trip}/packing/{item['id']}/state", json={"state": "packed"})
    assert c.delete(f"/api/trips/{trip}/packing/{item['id']}").status_code == 200
    assert c.get(f"/api/trips/{trip}/packing").json()["items"] == []


def test_packing_state_toggles_do_not_flood_event_log(client, trip):
    """三态点击是高频操作，不该把动态时间线刷爆。"""
    c, _ = client
    item = c.post(f"/api/trips/{trip}/packing", json={"name": "洗漱包"}).json()
    before = len(c.get(f"/api/trips/{trip}/events").json())
    for st in ("packed", "unpacked", "packed", "na"):
        c.put(f"/api/trips/{trip}/packing/{item['id']}/state", json={"state": st})
    assert len(c.get(f"/api/trips/{trip}/events").json()) == before


# ---------- 模块 7：避坑 ----------

def test_tips_crud_and_level_ordering(client, trip):
    c, _ = client
    c.post(f"/api/trips/{trip}/tips", json={"content": "夜市 22 点后收摊", "level": "notice"})
    imp = c.post(f"/api/trips/{trip}/tips",
                 json={"content": "清明上河园周一闭园", "level": "important"}).json()
    rows = c.get(f"/api/trips/{trip}/tips").json()
    assert rows[0]["level"] == "important"  # 重要提示排在前面，不被后加的普通提醒挤下去

    c.patch(f"/api/trips/{trip}/tips/{imp['id']}",
            json={"content": "清明上河园周一闭园（已确认）", "level": "important"})
    assert "已确认" in c.get(f"/api/trips/{trip}/tips").json()[0]["content"]
    assert c.delete(f"/api/trips/{trip}/tips/{imp['id']}").status_code == 200
    assert len(c.get(f"/api/trips/{trip}/tips").json()) == 1


def test_tip_bad_level_falls_back_to_notice(client, trip):
    c, _ = client
    t = c.post(f"/api/trips/{trip}/tips", json={"content": "带伞", "level": "critical"}).json()
    assert t["level"] == "notice"


def test_tip_rejects_blank(client, trip):
    c, _ = client
    assert c.post(f"/api/trips/{trip}/tips", json={"content": "  "}).status_code == 400


# ---------- 跨模块：写操作都刷新 updated_at，前端轮询才能看到 ----------

def test_writes_touch_trip_updated_at(client, trip):
    c, _ = client
    before = c.get(f"/api/trips/{trip}").json()["updated_at"]
    c.post(f"/api/trips/{trip}/tips", json={"content": "记得带身份证"})
    after = c.get(f"/api/trips/{trip}").json()["updated_at"]
    assert after != before  # 否则协作方轮询看不到新内容（前端按 updated_at 判断变更）


# ---------- 记账（Phase 87b 增强） ----------

def test_clearing_budget_also_clears_category_breakdown(client, trip):
    """预算清 0 后，面板不该还挂着一串类别金额（线上反馈）。"""
    import json as _json

    from app.db.models import TravelTrip

    c, _ = client
    # 模拟攻略导入写入的按类别计划预算
    from app.db.session import get_db  # noqa: F401  (fixture 已覆盖)
    r = c.patch(f"/api/trips/{trip}", json={"budget": 5000})
    assert r.status_code == 200
    detail = c.get(f"/api/trips/{trip}").json()
    assert detail["budget"] == 5000

    # 直接写 breakdown（导入链路的产物）
    import app.api.trip_api as api
    with api.get_session() as db:
        t = db.get(TravelTrip, trip)
        t.budget_breakdown_json = _json.dumps({"住宿": 2000, "餐饮": 1000})
        db.commit()
    assert c.get(f"/api/trips/{trip}").json()["budget_breakdown"]

    c.patch(f"/api/trips/{trip}", json={"budget": 0})
    after = c.get(f"/api/trips/{trip}").json()
    assert after["budget"] is None
    assert not after.get("budget_breakdown")  # 类别明细一并清掉


def test_expense_records_payer_and_spent_date(client, trip):
    """记账支持指定垫付人和花费日期（补记昨天的账很常见）。"""
    c, _ = client
    r = c.post(f"/api/trips/{trip}/expenses", json={
        "amount": 120, "title": "打车", "category": "交通",
        "payer": "bob", "spent_at": "2026-08-12",
    })
    assert r.status_code == 200
    row = c.get(f"/api/trips/{trip}/expenses").json()[0]
    assert row["payer"] == "bob" and row["spent_at"] == "2026-08-12"


def test_expense_payer_must_be_a_member(client, trip):
    c, _ = client
    r = c.post(f"/api/trips/{trip}/expenses", json={
        "amount": 50, "title": "水", "payer": "carol"})
    assert r.status_code == 400


# ---------- 行李分类管理 ----------

def test_packing_item_can_be_recategorized(client, trip):
    """「管理分类」= 对一批物品逐个改 category。"""
    c, _ = client
    item = c.post(f"/api/trips/{trip}/packing",
                  json={"name": "登机箱", "category": "通用"}).json()
    r = c.patch(f"/api/trips/{trip}/packing/{item['id']}",
                json={"category": "行李箱"})
    assert r.status_code == 200 and r.json()["category"] == "行李箱"
    assert c.get(f"/api/trips/{trip}/packing").json()["items"][0]["category"] == "行李箱"
