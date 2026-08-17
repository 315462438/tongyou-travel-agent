"""Phase 35 协同行程单测：串路线纯函数（不走回头路/永不劣化）+ API 权限与协同（sqlite 全离线）。"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.agent.trip_planner import build_review_facts, order_stops, route_km
from app.db.models import Base, TravelUser


# ---------- 串路线纯函数 ----------

def _s(i, day, order, loc):
    return {"id": f"s{i}", "day": day, "order_no": order, "name": f"点{i}", "location": loc}


def test_order_stops_fixes_backtracking():
    """构造回头路：A(0,0) → C(2,0) → B(1,0)，优化后应为 A→B→C，总里程严格下降。"""
    stops = [
        _s(1, 1, 0, "116.00,39.90"),  # A
        _s(2, 1, 1, "116.20,39.90"),  # C（先跑远）
        _s(3, 1, 2, "116.10,39.90"),  # B（又折回来 = 回头路）
    ]
    before = route_km(sorted(stops, key=lambda s: s["order_no"]))
    ordered = order_stops(stops)
    after = route_km(ordered)
    assert after < before
    assert [s["id"] for s in ordered] == ["s1", "s3", "s2"]  # A→B→C


def test_order_stops_never_worse():
    """已是最优序时保持不变（永不劣化保证）。"""
    stops = [
        _s(1, 1, 0, "116.00,39.90"),
        _s(2, 1, 1, "116.10,39.90"),
        _s(3, 1, 2, "116.20,39.90"),
    ]
    ordered = order_stops(stops)
    assert route_km(ordered) <= route_km(stops) + 1e-9
    assert [s["id"] for s in ordered] == ["s1", "s2", "s3"]


def test_order_stops_cross_day_anchoring():
    """次日从前一天终点最近的点起步（跨天首尾衔接），且不改 day 归属。"""
    stops = [
        _s(1, 1, 0, "116.00,39.90"),
        _s(2, 1, 1, "116.30,39.90"),   # day1 终点在东侧
        _s(3, 2, 0, "116.05,39.90"),   # day2 西侧点
        _s(4, 2, 1, "116.28,39.90"),   # day2 东侧点（离 day1 终点近 → 应先去）
    ]
    ordered = order_stops(stops)
    day2 = [s["id"] for s in ordered if s["day"] == 2]
    assert day2 == ["s4", "s3"]
    assert all(s["day"] in (1, 2) for s in ordered)


def test_order_stops_unlocated_kept_at_day_end():
    stops = [
        _s(1, 1, 0, None),  # 无坐标
        _s(2, 1, 1, "116.20,39.90"),
        _s(3, 1, 2, "116.10,39.90"),
    ]
    ordered = order_stops(stops)
    assert ordered[-1]["id"] == "s1"  # 无坐标排到天末
    assert len(ordered) == 3


def test_review_facts_contain_km_and_gaps():
    stops = [
        _s(1, 1, 0, "116.00,39.90"),
        _s(2, 1, 1, "116.20,39.90"),
        {"id": "s9", "day": 1, "order_no": 2, "name": "神秘地点", "location": None, "note": ""},
    ]
    facts = build_review_facts(stops)
    assert "Day1" in facts and "km" in facts
    assert "无坐标：神秘地点" in facts
    assert "备注为空" in facts


# ---------- API：权限 + 协同 ----------

@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=__import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)

    from contextlib import contextmanager

    @contextmanager
    def fake_session():
        db = maker()
        try:
            yield db
        finally:
            db.close()

    import app.api.trip_api as api

    monkeypatch.setattr(api, "get_session", fake_session)

    async def fake_geocode(names, city, **kwargs):
        return {n: "116.10,39.90" for n in names}

    monkeypatch.setattr("app.agent.trip_planner.geocode_names", fake_geocode)

    app = FastAPI()
    app.include_router(api.router)
    app.state.test_maker = maker

    from app.api.deps import get_current_user
    from app.db.session import get_db

    with maker() as db:
        ua = TravelUser(id="ua", username="alice", password_hash="x")
        ub = TravelUser(id="ub", username="bob", password_hash="x")
        uc = TravelUser(id="uc", username="carol", password_hash="x")
        db.add_all([ua, ub, uc])
        db.commit()

    current = {"id": "ua", "username": "alice"}

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


def test_trip_collaboration_flow(client):
    c, current = client
    # alice 建行程 + 加点
    trip_id = c.post("/api/trips", json={"title": "开封两日", "destination": "开封", "days": 2}).json()["id"]
    c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "开封府"})
    # bob 未受邀 → 404
    current["id"] = "ub"
    assert c.get(f"/api/trips/{trip_id}").status_code == 404
    assert c.get("/api/trips").json() == []
    # alice 邀请 bob（35b：先 pending，待接受）
    current["id"] = "ua"
    assert c.post(f"/api/trips/{trip_id}/invite", json={"username": "bob"}).status_code == 200
    assert c.post(f"/api/trips/{trip_id}/invite", json={"username": "bob"}).status_code == 409  # 重复
    assert c.post(f"/api/trips/{trip_id}/invite", json={"username": "nobody"}).status_code == 404
    # bob 收到邀请卡；接受前行程仍不可见
    current["id"] = "ub"
    assert c.get(f"/api/trips/{trip_id}").status_code == 404
    invites = c.get("/api/trips/invites/pending").json()
    assert len(invites) == 1 and invites[0]["inviter"] == "alice" and invites[0]["trip_id"] == trip_id
    assert c.post(f"/api/trips/{trip_id}/invites/respond", json={"accept": True}).status_code == 200
    assert c.get("/api/trips/invites/pending").json() == []
    # bob 可见可编辑
    detail = c.get(f"/api/trips/{trip_id}").json()
    assert {m["username"] for m in detail["members"]} == {"alice", "bob"}
    r = c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "鼓楼夜市", "note": "晚上去"})
    assert r.status_code == 200 and r.json()["location"]  # 建点时补了坐标
    # bob 是 editor，不能邀请/删除
    assert c.post(f"/api/trips/{trip_id}/invite", json={"username": "carol"}).status_code == 403
    assert c.delete(f"/api/trips/{trip_id}").status_code == 403
    # alice 侧轮询能看到 bob 的改动
    current["id"] = "ua"
    names = [s["name"] for s in c.get(f"/api/trips/{trip_id}").json()["stops"]]
    assert "鼓楼夜市" in names


def test_stop_no_location_can_be_unchecked_and_regeocoded(client):
    c, _current = client
    trip_id = c.post("/api/trips", json={"title": "吉隆坡一日", "destination": "吉隆坡", "days": 1}).json()["id"]
    created = c.post(f"/api/trips/{trip_id}/stops", json={
        "day": 1,
        "name": "值机",
        "note": "机场办理",
        "no_location": True,
    }).json()

    assert created["location"] == ""
    assert "no_location" in created["tags"]

    updated = c.patch(f"/api/trips/{trip_id}/stops/{created['id']}", json={
        "name": "值机",
        "note": "机场办理",
        "location": "吉隆坡国际机场",
        "no_location": False,
    })
    assert updated.status_code == 200
    body = updated.json()
    assert body["location"] == "116.10,39.90"
    assert "no_location" not in body["tags"]

    detail = c.get(f"/api/trips/{trip_id}").json()
    saved = next(s for s in detail["stops"] if s["id"] == created["id"])
    assert saved["location"] == "116.10,39.90"
    assert "no_location" not in saved["tags"]


def test_source_guide_is_visible_to_members_but_private_chat_stays_private(client):
    """editor 通过行程成员权限读原攻略；接口只给原攻略，不授予 owner 私人会话权限。"""
    import json

    from app.db.models import TravelConversation, TravelMessage, TravelTrip

    c, current = client
    with c.app.state.test_maker() as db:
        conv = TravelConversation(id="source-conv", user_id="ua", title="吉隆坡攻略")
        message = TravelMessage(
            id="source-msg",
            conversation_id=conv.id,
            role="assistant",
            content="## Day 1\n![双子塔](/travel/api/img?u=x)\n\n预算表",
            meta_json=json.dumps({"sources": [
                {"title": "小红书｜吉隆坡机位", "url": "https://www.xiaohongshu.com/explore/abc"},
                {"title": "坏链接", "url": "javascript:alert(1)"},
            ]}),
        )
        db.add_all([conv, message])
        db.commit()

    trip_id = c.post("/api/trips", json={"title": "马来西亚之旅", "destination": "吉隆坡"}).json()["id"]
    with c.app.state.test_maker() as db:
        trip = db.get(TravelTrip, trip_id)
        trip.source_conversation_id = "source-conv"
        trip.source_message_id = "source-msg"
        db.commit()

    # owner 预览时可回自己的原对话。
    owner_view = c.get(f"/api/trips/{trip_id}/source-guide")
    assert owner_view.status_code == 200
    assert owner_view.json()["can_open_conversation"] is True
    assert owner_view.json()["conversation_id"] == "source-conv"
    assert owner_view.json()["sources"] == [{
        "title": "小红书｜吉隆坡机位",
        "url": "https://www.xiaohongshu.com/explore/abc",
    }]

    c.post(f"/api/trips/{trip_id}/invite", json={"username": "bob"})
    current["id"] = "ub"
    c.post(f"/api/trips/{trip_id}/invites/respond", json={"accept": True})
    member_view = c.get(f"/api/trips/{trip_id}/source-guide")
    assert member_view.status_code == 200
    assert member_view.json()["content"].startswith("## Day 1")
    assert member_view.json()["can_open_conversation"] is False
    assert member_view.json()["conversation_id"] == ""

    current["id"] = "uc"
    assert c.get(f"/api/trips/{trip_id}/source-guide").status_code == 404


def test_stop_patch_and_reorder(client):
    c, current = client
    trip_id = c.post("/api/trips", json={"title": "t", "destination": "北京"}).json()["id"]
    s1 = c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "故宫"}).json()
    s2 = c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "颐和园"}).json()
    # 改备注/换天/换序
    r = c.patch(f"/api/trips/{trip_id}/stops/{s1['id']}", json={"note": "早上去", "day": 2})
    assert r.json()["note"] == "早上去" and r.json()["day"] == 2
    c.patch(f"/api/trips/{trip_id}/stops/{s2['id']}", json={"order_no": 99})
    # 删除
    assert c.delete(f"/api/trips/{trip_id}/stops/{s1['id']}").status_code == 200
    assert len(c.get(f"/api/trips/{trip_id}").json()["stops"]) == 1


def test_ai_order_endpoint(client):
    c, _ = client
    trip_id = c.post("/api/trips", json={"title": "t", "destination": "北京"}).json()["id"]
    assert c.post(f"/api/trips/{trip_id}/ai/order").status_code == 400  # 空行程
    for name in ("A", "B", "C"):
        c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": name})
    r = c.post(f"/api/trips/{trip_id}/ai/order")
    assert r.status_code == 200
    body = r.json()
    assert "km_before" in body and "km_after" in body
    assert body["km_after"] <= body["km_before"] + 1e-6


def test_invite_reject_allows_reinvite(client):
    c, current = client
    trip_id = c.post("/api/trips", json={"title": "t", "destination": "北京"}).json()["id"]
    c.post(f"/api/trips/{trip_id}/invite", json={"username": "bob"})
    current["id"] = "ub"
    assert c.post(f"/api/trips/{trip_id}/invites/respond", json={"accept": False}).status_code == 200
    assert c.get(f"/api/trips/{trip_id}").status_code == 404  # 拒绝后不可见
    assert c.post(f"/api/trips/{trip_id}/invites/respond", json={"accept": True}).status_code == 404  # 已处理
    current["id"] = "ua"
    assert c.post(f"/api/trips/{trip_id}/invite", json={"username": "bob"}).status_code == 200  # 可再邀


def test_import_from_chat(client, monkeypatch):
    c, current = client
    # 会话与攻略消息（归 alice）
    import app.api.trip_api as api
    from app.db.models import TravelConversation, TravelMessage

    with api.get_session() as db:  # api.get_session 已被 fixture 替换为 sqlite
        db.add(TravelConversation(id="conv1", user_id="ua", title="哈尔滨攻略"))
        db.add(TravelMessage(id="msg1", conversation_id="conv1", role="assistant",
                             content="## Day 1\n- 中央大街\n- 圣索菲亚教堂"))
        db.commit()

    from app.agent.trip_planner import DraftStop, TripImportDays, TripImportSummary

    class _LLM:
        def parse(self, prompt, schema, system="", **kwargs):
            assert "中央大街" in prompt
            if schema is TripImportSummary:
                return TripImportSummary(title="哈尔滨两日", destination="哈尔滨", days=2)
            assert schema is TripImportDays
            return TripImportDays(stops=[
                    DraftStop(day=1, name="中央大街", note="夜景"),
                    DraftStop(day=1, name="圣索菲亚教堂", note=""),
                ])

    monkeypatch.setattr("app.llm.client.get_llm", lambda: _LLM())

    # 归属校验：bob 不能导入 alice 的会话
    current["id"] = "ub"
    assert c.post("/api/trips/import",
                  json={"conversation_id": "conv1", "message_id": "msg1"}).status_code == 404
    # alice 导入成功（TestClient 会同步执行 BackgroundTasks）
    current["id"] = "ua"
    r = c.post("/api/trips/import", json={"conversation_id": "conv1", "message_id": "msg1"})
    assert r.status_code == 200
    trip_id = r.json()["id"]
    detail = c.get(f"/api/trips/{trip_id}").json()
    assert detail["title"] == "哈尔滨两日" and detail["destination"] == "哈尔滨"
    assert {s["name"] for s in detail["stops"]} == {"中央大街", "圣索菲亚教堂"}
    assert detail["ai_status"] is None  # 导入完成


def test_import_extracts_stays_and_budget(client, monkeypatch):
    """Phase 51：导入时抽住宿→🏨 stop（带价格）+ 预算拆分→budget_breakdown（归一聚合）。"""
    c, current = client
    import app.api.trip_api as api
    from app.db.models import TravelConversation, TravelMessage

    with api.get_session() as db:
        db.add(TravelConversation(id="conv2", user_id="ua", title="川西攻略"))
        db.add(TravelMessage(id="msg2", conversation_id="conv2", role="assistant",
                             content="## Day1 成都\n住如家。预算：住宿400 门票200\n## Day2 返程"))
        db.commit()

    from app.agent.trip_planner import (
        BudgetItem, DraftDayPlan, DraftStay, DraftStop, HotelOption,
        TripImportDays, TripImportSummary,
    )

    class _LLM:
        def parse(self, prompt, schema, system="", **kwargs):
            if schema is TripImportSummary:
                return TripImportSummary(
                    title="川西4日", destination="成都", days=2,
                    hotel_options=[HotelOption(
                        city="成都", hotel="亚朵酒店", price=480, source="携程", note="地铁方便",
                    )],
                    budget_items=[
                        BudgetItem(category="住宿", amount=400),
                        BudgetItem(category="门票", amount=200),
                        BudgetItem(category="机票", amount=1000),  # 归一到「大交通」
                    ],
                )
            assert schema is TripImportDays
            return TripImportDays(
                stops=[DraftStop(day=1, name="宽窄巷子", note="", transport="步行")],
                stays=[DraftStay(day=1, city="成都", hotel="如家酒店", price=400, source="携程")],
                day_plans=[
                    DraftDayPlan(day=1, type="stay", overnight_required=True, overnight_city="成都"),
                    DraftDayPlan(day=2, type="return", overnight_required=False, overnight_city=""),
                ],
            )

    monkeypatch.setattr("app.llm.client.get_llm", lambda: _LLM())
    current["id"] = "ua"
    r = c.post("/api/trips/import", json={"conversation_id": "conv2", "message_id": "msg2"})
    assert r.status_code == 200
    detail = c.get(f"/api/trips/{r.json()['id']}").json()

    # 住宿 → 🏨 stop，带 ticket_price
    stays = [s for s in detail["stops"] if "🏨" in s["name"]]
    assert len(stays) == 1
    assert stays[0]["name"] == "🏨 如家酒店" and stays[0]["ticket_price"] == 400
    assert "携程" in stays[0]["note"]
    assert next(s for s in detail["stops"] if s["name"] == "宽窄巷子")["transport"] == "步行"
    assert detail["day_plans"][1] == {
        "day": 2, "type": "return", "overnight_required": False, "overnight_city": "",
    }
    assert detail["hotel_recommendations"] == [{
        "city": "成都", "hotel": "亚朵酒店", "price": 480.0,
        "source": "携程", "note": "地铁方便",
    }]
    # 预算拆分归一聚合 + 总额
    assert detail["budget_breakdown"] == {"住宿": 400, "门票": 200, "大交通": 1000}
    assert detail["budget"] == 1600


def test_import_18_days_is_chunked_and_keeps_day_18(client, monkeypatch):
    """长攻略按天分块抽取；导入后保留 Day 18，不再被 15 天上限截断。"""
    import re
    import app.api.trip_api as api
    from app.db.models import TravelConversation, TravelMessage
    from app.agent.trip_planner import (
        BudgetItem, DraftDayPlan, DraftStop, TripImportDays, TripImportSummary,
    )

    c, current = client
    guide = "\n".join(
        f"## Day {day}\n- 第{day}天景点\n- 住宿：第{day}城"
        for day in range(1, 19)
    ) + "\n## 预算估算\n住宿 7650 元，交通 8856 元"
    with api.get_session() as db:
        db.add(TravelConversation(id="conv18", user_id="ua", title="18天跨省攻略"))
        db.add(TravelMessage(
            id="msg18", conversation_id="conv18", role="assistant", content=guide,
        ))
        db.commit()

    calls = {"summary": 0, "days": 0}

    class _LLM:
        def parse(self, prompt, schema, system="", **kwargs):
            if schema is TripImportSummary:
                calls["summary"] += 1
                return TripImportSummary(
                    title="18天跨省之旅", destination="西安至丽江", days=18,
                    budget_items=[
                        BudgetItem(category="住宿", amount=7650),
                        BudgetItem(category="大交通", amount=8856),
                    ],
                )
            assert schema is TripImportDays
            calls["days"] += 1
            assert "## 预算估算" not in prompt  # 全局章节不能泄漏进最后一个 Day 分块
            match = re.search(r"本段只允许提取 Day (\d+)[–-](\d+)", prompt)
            assert match
            lo, hi = map(int, match.groups())
            return TripImportDays(
                stops=[DraftStop(day=day, name=f"第{day}天景点") for day in range(lo, hi + 1)],
                day_plans=[
                    DraftDayPlan(
                        day=day,
                        type="return" if day == 18 else "stay",
                        overnight_required=day != 18,
                        overnight_city="" if day == 18 else f"第{day}城",
                    )
                    for day in range(lo, hi + 1)
                ],
            )

    monkeypatch.setattr("app.llm.client.get_llm", lambda: _LLM())
    current["id"] = "ua"
    response = c.post(
        "/api/trips/import",
        json={"conversation_id": "conv18", "message_id": "msg18"},
    )
    assert response.status_code == 200
    detail = c.get(f"/api/trips/{response.json()['id']}").json()
    assert calls == {"summary": 1, "days": 18}
    assert detail["days"] == 18
    assert any(s["day"] == 18 and s["name"] == "第18天景点" for s in detail["stops"])
    assert len(detail["day_plans"]) == 18
    assert detail["budget_breakdown"] == {"住宿": 7650, "大交通": 8856}
    assert detail["ai_status"] is None


def test_trip_day_limit_is_30(client):
    c, _ = client
    trip_id = c.post(
        "/api/trips", json={"title": "长行程", "destination": "全国", "days": 31},
    ).json()["id"]
    assert c.get(f"/api/trips/{trip_id}").json()["days"] == 30
    assert c.patch(f"/api/trips/{trip_id}", json={"days": 18}).status_code == 200
    assert c.get(f"/api/trips/{trip_id}").json()["days"] == 18


def test_geocode_cooldown_retries_only_missing(monkeypatch):
    import asyncio
    from app.api.trip_api import _geocode_with_cooldown

    calls = []

    async def fake_geocode(names, city):
        calls.append((list(names), city))
        if len(calls) == 1:
            return {"A": "1,1"}
        return {"B": "2,2"}

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr("app.api.trip_api.asyncio.sleep", no_wait)
    result = asyncio.run(_geocode_with_cooldown(["A", "B", "A"], "测试城", fake_geocode))
    assert result == {"A": "1,1", "B": "2,2"}
    assert calls == [(["A", "B", "A"], "测试城"), (["B"], "测试城")]


def test_multicity_geocode_uses_day_city_and_return_uses_previous(monkeypatch):
    import asyncio
    from app.agent.trip_planner import DraftDayPlan, DraftStop
    from app.api.trip_api import _geocode_stops_by_city

    calls = []

    async def fake_geocode(names, city):
        calls.append((list(names), city))
        return {name: f"{city}-坐标" for name in names}

    stops = [
        DraftStop(day=1, name="钟楼", search_name="Xi'an Bell Tower"),
        DraftStop(day=2, name="中山桥"),
        DraftStop(day=3, name="兰州西站"),
    ]
    plans = [
        DraftDayPlan(day=1, overnight_city="西安"),
        DraftDayPlan(day=2, overnight_city="兰州"),
        DraftDayPlan(day=3, type="return", overnight_required=False, overnight_city=""),
    ]
    result = asyncio.run(_geocode_stops_by_city(stops, plans, "西安至兰州", fake_geocode))
    assert result[(1, "钟楼")] == "西安-坐标"
    assert result[(2, "中山桥")] == "兰州-坐标"
    assert result[(3, "兰州西站")] == "兰州-坐标"
    assert sorted(city for _names, city in calls) == ["兰州", "西安"]
    assert any("Xi'an Bell Tower" in names for names, _city in calls)


def test_transfer_day_geocode_retries_other_trip_city():
    """Day2 过夜仙本那，但上午的吉隆坡机场应在行程其他城市中重试命中。"""
    import asyncio
    from app.agent.trip_planner import DraftDayPlan, DraftStop
    from app.api.trip_api import _geocode_stops_by_city

    async def fake_geocode(names, city):
        available = {
            ("Kuala Lumpur International Airport", "吉隆坡"): "101.70,2.74",
            ("Semporna", "仙本那"): "118.61,4.48",
        }
        return {name: available[(name, city)] for name in names if (name, city) in available}

    stops = [
        DraftStop(day=2, name="吉隆坡国际机场", search_name="Kuala Lumpur International Airport"),
        DraftStop(day=2, name="仙本那镇", search_name="Semporna"),
    ]
    plans = [
        DraftDayPlan(day=1, overnight_city="吉隆坡"),
        DraftDayPlan(day=2, overnight_city="仙本那"),
    ]
    result = asyncio.run(_geocode_stops_by_city(stops, plans, "吉隆坡、仙本那", fake_geocode))
    assert result[(2, "吉隆坡国际机场")] == "101.70,2.74"
    assert result[(2, "仙本那镇")] == "118.61,4.48"


# ---------- Phase 36：检查中心 + 字段 + 联动 ----------

def test_build_issues_rules():
    from app.agent.trip_planner import build_issues

    stops = [
        # Day1：三个点拉出 >8km 步行 + 顺序可优化（远点在中间）
        {"id": "a", "day": 1, "order_no": 0, "name": "A", "location": "116.00,39.90",
         "start_time": "09:00", "stay_min": 120, "transport": "", "ticket_price": 300},
        {"id": "b", "day": 1, "order_no": 1, "name": "B", "location": "116.12,39.90",
         "start_time": "10:00", "stay_min": None, "transport": "步行", "ticket_price": None},  # 与 A 冲突
        {"id": "c", "day": 1, "order_no": 2, "name": "C", "location": "116.06,39.90",
         "start_time": "", "stay_min": None, "transport": "步行", "ticket_price": None},
        {"id": "d", "day": 2, "order_no": 3, "name": "神秘店", "location": "",
         "start_time": "", "stay_min": None, "transport": "", "ticket_price": None},  # 无坐标
    ]
    forecast = [{"date": "2026-08-02", "dayweather": "中雨"}]  # Day2 下雨
    issues = build_issues(stops, budget=200, start_date="2026-08-01", forecast=forecast)
    kinds = {i["kind"] for i in issues}
    assert {"walk", "order", "time", "noloc", "budget", "weather"} <= kinds
    time_issue = next(i for i in issues if i["kind"] == "time")
    assert time_issue["stop_id"] == "b"  # 冲突定位到后一个条目
    weather_issue = next(i for i in issues if i["kind"] == "weather")
    assert weather_issue["day"] == 2


def test_classify_days_transit_and_return():
    """Phase 51 批4：城际转移日=transit，末日=return(不过夜)，普通日=stay。"""
    from app.agent.trip_planner import classify_days

    stops = [
        # Day1：成都市内两点（相距很近）→ stay
        {"id": "a", "day": 1, "order_no": 0, "name": "宽窄巷子", "location": "104.06,30.67"},
        {"id": "b", "day": 1, "order_no": 1, "name": "武侯祠", "location": "104.05,30.64"},
        # Day2：成都(104.06)→康定(101.96)，直线数百 km → transit
        {"id": "c", "day": 2, "order_no": 0, "name": "成都出发", "location": "104.06,30.67"},
        {"id": "d", "day": 2, "order_no": 1, "name": "康定", "location": "101.96,30.05"},
        # Day3：康定市内 → 但它是末日 → return
        {"id": "e", "day": 3, "order_no": 0, "name": "情歌广场", "location": "101.96,30.05"},
    ]
    cls = classify_days(stops, total_days=3)
    assert cls[1]["type"] == "stay" and cls[1]["overnight_required"] is True
    assert cls[2]["type"] == "transit" and cls[2]["overnight_required"] is True
    assert cls[3]["type"] == "return" and cls[3]["overnight_required"] is False
    assert cls[2]["span_km"] > 60  # 城际跨度


def test_build_issues_transit_not_flagged_walk_and_detail():
    """转移日不误报步行；步行告警带「计算依据」逐腿明细。"""
    from app.agent.trip_planner import build_issues

    stops = [
        # Day1 市内暴走（步行、3 点拉长）→ walk 告警 + detail
        {"id": "a", "day": 1, "order_no": 0, "name": "A", "location": "116.00,39.90", "transport": "步行"},
        {"id": "b", "day": 1, "order_no": 1, "name": "B", "location": "116.12,39.90", "transport": "步行"},
        {"id": "c", "day": 1, "order_no": 2, "name": "C", "location": "116.20,39.90", "transport": "步行"},
        # Day2 城际转移（首末数百 km）→ 不应报 walk，应报 transit info
        {"id": "d", "day": 2, "order_no": 0, "name": "甲城", "location": "116.00,39.90"},
        {"id": "e", "day": 2, "order_no": 1, "name": "乙城", "location": "118.00,39.90"},
        # Day3 收尾（末日 return）
        {"id": "f", "day": 3, "order_no": 0, "name": "尾", "location": "118.00,39.90"},
    ]
    issues = build_issues(stops, total_days=3)
    walks = [i for i in issues if i["kind"] == "walk"]
    assert len(walks) == 1 and walks[0]["day"] == 1
    assert "计算依据" in walks[0]["detail"] and "A→B" in walks[0]["detail"]
    transit = [i for i in issues if i["kind"] == "transit"]
    assert len(transit) == 1 and transit[0]["day"] == 2  # Day2 报转移，不报步行
    assert not any(i["kind"] == "walk" and i["day"] == 2 for i in issues)


def test_build_issues_only_sums_walking_legs():
    """Phase 54：3km 步行 + 7km 驾车不能被误报成 10km 步行。"""
    from app.agent.trip_planner import build_issues

    stops = [
        {"id": "a", "day": 1, "order_no": 0, "name": "A", "location": "116.00,39.90", "transport": ""},
        {"id": "b", "day": 1, "order_no": 1, "name": "B", "location": "116.03,39.90", "transport": "步行"},
        {"id": "c", "day": 1, "order_no": 2, "name": "C", "location": "116.10,39.90", "transport": "驾车"},
    ]
    issues = build_issues(stops, total_days=2)
    assert not any(i["kind"] == "walk" for i in issues)


def test_infer_transport_corrects_impossible_airport_legs_and_keeps_boat():
    from app.agent.trip_planner import infer_leg_transport

    airport_to_city = {
        "name": "鬼仔巷", "location": "101.6977,3.1416", "transport": "步行",
    }
    airport = {"name": "吉隆坡国际机场", "location": "101.7064,2.7431"}
    assert infer_leg_transport(airport, airport_to_city) == "打车"

    semporna = {"name": "仙本那镇", "location": "118.6111,4.4811", "transport": "拼车"}
    assert infer_leg_transport(airport, semporna) == "飞机"

    island = {"name": "马达京", "location": "118.9489,4.5763", "transport": "船"}
    assert infer_leg_transport(semporna, island) == "船"


def test_build_issues_geometry_wins_over_llm_transit():
    """检查中心：几何能度量时以几何为准——LLM 把市内/短途日误标 transit，不误报城际转移
    （修复：14.7km 成都市内日被判「城际转移日」）。当天≥2个坐标即视为可度量。"""
    from app.agent.trip_planner import build_issues

    stops = [
        # Day1 市内暴走（3点都有坐标、首末跨度 <60km）
        {"id": "a", "day": 1, "order_no": 0, "name": "A", "location": "116.00,39.90", "transport": "步行"},
        {"id": "b", "day": 1, "order_no": 1, "name": "B", "location": "116.12,39.90", "transport": "步行"},
        {"id": "c", "day": 1, "order_no": 2, "name": "C", "location": "116.20,39.90", "transport": "步行"},
        {"id": "z", "day": 2, "order_no": 0, "name": "末", "location": "116.20,39.90"},
    ]
    # LLM 误标 Day1=transit，但几何可度量且跨度小 → 几何赢：照报步行，不误报城际转移
    plans = [{"day": 1, "type": "transit", "overnight_required": True, "overnight_city": "北京"}]
    issues = build_issues(stops, total_days=2, day_plans=plans)
    assert any(i["kind"] == "walk" and i["day"] == 1 for i in issues)
    assert not any(i["kind"] == "transit" and i["day"] == 1 for i in issues)


def test_build_issues_trusts_llm_transit_when_unmeasurable():
    """几何测不了时（当天<2个坐标，如过夜火车整天在途）信 LLM 的 transit 标注：报转移、不报步行。"""
    from app.agent.trip_planner import build_issues

    stops = [
        {"id": "a", "day": 1, "order_no": 0, "name": "卧铺出发", "location": ""},  # 无坐标
        {"id": "z", "day": 2, "order_no": 0, "name": "到站", "location": "116.00,39.90"},
    ]
    plans = [{"day": 1, "type": "transit", "overnight_required": False, "overnight_city": ""}]
    issues = build_issues(stops, total_days=2, day_plans=plans)
    assert any(i["kind"] == "transit" and i["day"] == 1 for i in issues)
    assert not any(i["kind"] == "walk" and i["day"] == 1 for i in issues)


def test_day_cities_prefers_structured_overnight_plan(client, monkeypatch):
    """当天往返景点不能按景点行政区订房；火车过夜/返程日不提示酒店。"""
    c, _ = client
    import json
    import app.api.trip_api as api

    trip_id = c.post("/api/trips", json={"title": "西藏", "destination": "拉萨", "days": 3}).json()["id"]
    with api.get_session() as db:
        from app.db.models import TravelTrip

        trip = db.get(TravelTrip, trip_id)
        trip.day_plan_json = json.dumps([
            {"day": 1, "type": "transit", "overnight_required": False, "overnight_city": ""},
            {"day": 2, "type": "stay", "overnight_required": True, "overnight_city": "拉萨"},
            {"day": 3, "type": "return", "overnight_required": False, "overnight_city": ""},
        ], ensure_ascii=False)
        db.commit()

    async def fake_regeo(_loc):
        return "山南市"

    monkeypatch.setattr("app.tools.amap.regeo", fake_regeo)
    body = c.get(f"/api/trips/{trip_id}/day-cities").json()
    assert body["overnight"] == {"1": False, "2": True, "3": False}
    assert body["cities"].get("2") == "拉萨"
    assert "1" not in body["cities"] and "3" not in body["cities"]


def test_stop_extended_fields_and_trip_patch(client):
    c, _ = client
    trip_id = c.post("/api/trips", json={"title": "t", "destination": "北京"}).json()["id"]
    s1 = c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "故宫"}).json()
    r = c.patch(f"/api/trips/{trip_id}/stops/{s1['id']}", json={
        "start_time": "09:30", "stay_min": 90, "transport": "步行",
        "ticket_price": 60, "tags": ["历史", "拍照"],
    }).json()
    assert r["start_time"] == "09:30" and r["stay_min"] == 90
    assert r["transport"] == "步行" and r["ticket_price"] == 60 and r["tags"] == ["历史", "拍照"]

    assert c.patch(f"/api/trips/{trip_id}", json={"budget": 2000, "start_date": "2026-08-01"}).status_code == 200
    detail = c.get(f"/api/trips/{trip_id}").json()
    assert detail["budget"] == 2000 and detail["start_date"] == "2026-08-01"

    r = c.get(f"/api/trips/{trip_id}/issues").json()
    assert r["ticket_total"] == 60
    assert isinstance(r["issues"], list)


def test_import_links_both_ways(client, monkeypatch):
    """Phase 36 联动：trip 记来源会话；来源消息 meta 打上 imported_trip_id。"""
    c, current = client
    import json as _json

    import app.api.trip_api as api
    from app.db.models import TravelConversation, TravelMessage

    with api.get_session() as db:
        db.add(TravelConversation(id="conv2", user_id="ua", title="开封攻略"))
        db.add(TravelMessage(id="msg2", conversation_id="conv2", role="assistant",
                             content="## Day 1\n- 开封府"))
        db.commit()

    from app.agent.trip_planner import DraftStop, TripDraft

    class _LLM:
        def parse(self, prompt, schema, system=""):
            return TripDraft(title="开封行", destination="开封", days=1,
                             stops=[DraftStop(day=1, name="开封府", note="")])

    monkeypatch.setattr("app.llm.client.get_llm", lambda: _LLM())
    current["id"] = "ua"
    trip_id = c.post("/api/trips/import",
                     json={"conversation_id": "conv2", "message_id": "msg2"}).json()["id"]

    detail = c.get(f"/api/trips/{trip_id}").json()
    assert detail["source_conversation_id"] == "conv2"  # 板 → 对话
    with api.get_session() as db:
        meta = _json.loads(db.get(TravelMessage, "msg2").meta_json)
        assert meta["imported_trip_id"] == trip_id  # 对话 → 板


# ---------- Phase 37：Copilot 提案制 ----------

def _copilot_llm(monkeypatch, reply, changes):
    from app.agent.trip_planner import ChangeOp, CopilotResult

    class _LLM:
        def parse(self, prompt, schema, system="", model=None, max_tokens=8000):
            return CopilotResult(reply=reply, changes=[ChangeOp(**c) for c in changes])

    monkeypatch.setattr("app.llm.client.get_llm", lambda: _LLM())


def test_copilot_answer_only_no_proposal(client, monkeypatch):
    c, _ = client
    trip_id = c.post("/api/trips", json={"title": "t", "destination": "北京"}).json()["id"]
    c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "故宫"})
    _copilot_llm(monkeypatch, "故宫周一闭馆，建议避开。", [])

    assert c.post(f"/api/trips/{trip_id}/ai/copilot", json={"prompt": "故宫哪天闭馆"}).status_code == 200
    sgs = c.get(f"/api/trips/{trip_id}/suggestions").json()
    assert sgs[0]["status"] == "answered" and "闭馆" in sgs[0]["reply"] and sgs[0]["changes"] == []


def test_copilot_proposal_apply_and_revert(client, monkeypatch):
    c, _ = client
    trip_id = c.post("/api/trips", json={"title": "t", "destination": "北京"}).json()["id"]
    s1 = c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "远郊景区"}).json()
    _copilot_llm(monkeypatch, "减少奔波：删远郊、加市区点。", [
        {"op": "delete", "stop_id": s1["id"], "reason": "太远"},
        {"op": "add", "day": 1, "name": "景山公园", "note": "看故宫全景", "reason": "市区替代"},
    ])
    c.post(f"/api/trips/{trip_id}/ai/copilot", json={"prompt": "减少奔波"})
    sg = c.get(f"/api/trips/{trip_id}/suggestions").json()[0]
    assert sg["status"] == "pending" and len(sg["changes"]) == 2
    assert sg["changes"][0]["reason"]  # AI Explain 必须有

    # 采纳：删旧加新（fake geocode 会给新点坐标）
    assert c.post(f"/api/trips/{trip_id}/suggestions/{sg['id']}/apply").status_code == 200
    names = [s["name"] for s in c.get(f"/api/trips/{trip_id}").json()["stops"]]
    assert names == ["景山公园"]

    # 恢复：回到 apply 前
    assert c.post(f"/api/trips/{trip_id}/suggestions/{sg['id']}/revert").status_code == 200
    names = [s["name"] for s in c.get(f"/api/trips/{trip_id}").json()["stops"]]
    assert names == ["远郊景区"]


def test_copilot_reject_keeps_data(client, monkeypatch):
    c, _ = client
    trip_id = c.post("/api/trips", json={"title": "t", "destination": "北京"}).json()["id"]
    s1 = c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "故宫"}).json()
    _copilot_llm(monkeypatch, "建议删除。", [{"op": "delete", "stop_id": s1["id"], "reason": "r"}])
    c.post(f"/api/trips/{trip_id}/ai/copilot", json={"prompt": "删掉故宫"})
    sg = c.get(f"/api/trips/{trip_id}/suggestions").json()[0]
    assert c.post(f"/api/trips/{trip_id}/suggestions/{sg['id']}/reject").status_code == 200
    assert len(c.get(f"/api/trips/{trip_id}").json()["stops"]) == 1  # 数据没动
    assert c.post(f"/api/trips/{trip_id}/suggestions/{sg['id']}/apply").status_code == 404  # 已处理


def test_copilot_falls_back_to_fast_model(client, monkeypatch):
    """复杂请求把规划模型输出撑截断时，回退快模型仍能产出提案（而非直接失败）。"""
    c, _ = client
    trip_id = c.post("/api/trips", json={"title": "拉萨", "destination": "拉萨", "days": 15}).json()["id"]
    s1 = c.post(f"/api/trips/{trip_id}/stops", json={"day": 10, "name": "远郊景点"}).json()

    from app.agent.trip_planner import ChangeOp, CopilotResult

    calls: list = []

    class _LLM:
        def parse(self, prompt, schema, system="", model=None, max_tokens=8000):
            calls.append(model)
            if model is None:  # 第一次=规划模型（run_copilot 不传 model）→ 模拟截断成非法 JSON
                raise ValueError("LLM 结构化输出解析失败: json_invalid")
            # 回退快模型 → 正常产出结构化改动
            return CopilotResult(reply="已缩短为 7 天，删掉多余天的地点。",
                                 changes=[ChangeOp(op="delete", stop_id=s1["id"], reason="超出目标天数")])

    monkeypatch.setattr("app.llm.client.get_llm", lambda: _LLM())
    assert c.post(f"/api/trips/{trip_id}/ai/copilot",
                  json={"prompt": "把15天缩短到7天"}).status_code == 200
    detail = c.get(f"/api/trips/{trip_id}").json()
    assert detail["ai_status"] is None
    sg = c.get(f"/api/trips/{trip_id}/suggestions").json()[0]
    assert sg["status"] == "pending" and len(sg["changes"]) == 1  # 回退成功产出可采纳提案
    assert calls[0] is None and calls[1] is not None  # 先规划模型、后快模型


def test_copilot_parse_failure_degrades_gracefully(client, monkeypatch):
    """解析失败（如整体重规划输出被截断）不留「任务失败」死状态，
    而是写一条可操作的 answered 建议，ai_status 清空。"""
    c, _ = client
    trip_id = c.post("/api/trips", json={"title": "拉萨", "destination": "拉萨", "days": 7}).json()["id"]
    c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "成都"})

    class _BadLLM:  # 规划模型和快模型两次都失败 → 才走优雅降级
        def parse(self, prompt, schema, system="", model=None, max_tokens=8000):
            raise ValueError("LLM 结构化输出解析失败（重试后仍不合法）")

    monkeypatch.setattr("app.llm.client.get_llm", lambda: _BadLLM())
    assert c.post(f"/api/trips/{trip_id}/ai/copilot",
                  json={"prompt": "15天，从武汉出发一个来回，规划一下"}).status_code == 200
    detail = c.get(f"/api/trips/{trip_id}").json()
    assert detail["ai_status"] is None  # 不是 "failed"，板头不报错
    sg = c.get(f"/api/trips/{trip_id}/suggestions").json()[0]
    assert sg["status"] == "answered" and sg["changes"] == []
    assert "拆小" in sg["reply"] or "主对话" in sg["reply"]  # 给了可操作出路


def test_seed_on_nonempty_trip_goes_proposal(client, monkeypatch):
    c, _ = client
    trip_id = c.post("/api/trips", json={"title": "t", "destination": "北京"}).json()["id"]
    c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "故宫"})
    _copilot_llm(monkeypatch, "重排方案", [{"op": "add", "day": 1, "name": "北海公园", "reason": "顺路"}])
    r = c.post(f"/api/trips/{trip_id}/ai/seed", json={"prompt": "轻松一点"})
    assert r.json().get("proposal") is True
    assert c.get(f"/api/trips/{trip_id}/suggestions").json()[0]["status"] == "pending"
    assert len(c.get(f"/api/trips/{trip_id}").json()["stops"]) == 1  # 没被直接覆盖


# ---------- Phase 38：评论 / presence / 修改记录 ----------

def test_comments_crud_and_permission(client):
    c, current = client
    trip_id = c.post("/api/trips", json={"title": "t", "destination": "北京"}).json()["id"]
    s1 = c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "中央大街"}).json()
    c.post(f"/api/trips/{trip_id}/invite", json={"username": "bob"})
    current["id"] = "ub"
    c.post(f"/api/trips/{trip_id}/invites/respond", json={"accept": True})
    c.post(f"/api/trips/{trip_id}/stops/{s1['id']}/comments", json={"content": "晚上灯最好看"})
    current["id"] = "ua"
    comments = c.get(f"/api/trips/{trip_id}/comments").json()
    assert comments[0]["username"] == "bob" and comments[0]["stop_id"] == s1["id"]
    assert comments[0]["mine"] is False
    # 不能删别人的
    assert c.delete(f"/api/trips/{trip_id}/comments/{comments[0]['id']}").status_code == 403
    current["id"] = "ub"
    assert c.delete(f"/api/trips/{trip_id}/comments/{comments[0]['id']}").status_code == 200


def test_trip_chat_flow_incremental_and_permissions(client):
    c, current = client
    trip_id = c.post("/api/trips", json={"title": "川西同行", "destination": "成都"}).json()["id"]
    c.post(f"/api/trips/{trip_id}/invite", json={"username": "bob"})
    current["id"] = "ub"
    c.post(f"/api/trips/{trip_id}/invites/respond", json={"accept": True})

    assert c.post(f"/api/trips/{trip_id}/chat", json={"content": "  "}).status_code == 400
    first = c.post(
        f"/api/trips/{trip_id}/chat",
        json={"content": "  明早八点酒店门口集合  "},
    )
    assert first.status_code == 200
    first_message = first.json()
    assert first_message["content"] == "明早八点酒店门口集合"
    assert first_message["username"] == "bob" and first_message["mine"] is True

    second = c.post(f"/api/trips/{trip_id}/chat", json={"content": "x" * 1100}).json()
    assert len(second["content"]) == 1000
    delta = c.get(f"/api/trips/{trip_id}/chat?after={first_message['id']}").json()
    assert [message["id"] for message in delta] == [second["id"]]

    current["id"] = "ua"
    messages = c.get(f"/api/trips/{trip_id}/chat").json()
    assert [message["content"] for message in messages] == [
        "明早八点酒店门口集合",
        "x" * 1000,
    ]
    assert all(message["mine"] is False for message in messages)
    assert c.delete(f"/api/trips/{trip_id}/chat/{first_message['id']}").status_code == 403

    current["id"] = "uc"
    assert c.get(f"/api/trips/{trip_id}/chat").status_code == 404
    assert c.post(f"/api/trips/{trip_id}/chat", json={"content": "偷看"}).status_code == 404

    current["id"] = "ub"
    assert c.delete(f"/api/trips/{trip_id}/chat/{first_message['id']}").status_code == 200
    assert [message["id"] for message in c.get(f"/api/trips/{trip_id}/chat").json()] == [second["id"]]


def test_presence_reported_via_poll(client):
    c, _ = client
    trip_id = c.post("/api/trips", json={"title": "t", "destination": "北京"}).json()["id"]
    detail = c.get(f"/api/trips/{trip_id}?editing_day=2").json()
    me = next(m for m in detail["members"] if m["username"] == "alice")
    assert me["online"] is True and me["editing_day"] == 2


def test_events_logged(client):
    c, _ = client
    trip_id = c.post("/api/trips", json={"title": "t", "destination": "北京"}).json()["id"]
    s1 = c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "故宫"}).json()
    c.patch(f"/api/trips/{trip_id}/stops/{s1['id']}", json={"note": "早点去"})
    c.delete(f"/api/trips/{trip_id}/stops/{s1['id']}")
    actions = " | ".join(e["action"] for e in c.get(f"/api/trips/{trip_id}/events").json())
    assert "添加了「故宫」" in actions and "编辑了「故宫」" in actions and "删除了「故宫」" in actions


# ---------- Phase 39：真实交通时间 ----------

def test_segment_times(client, monkeypatch):
    c, _ = client
    trip_id = c.post("/api/trips", json={"title": "t", "destination": "北京"}).json()["id"]
    c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "A"})
    c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "B"})

    async def fake_route_time(client_, origin, dest, mode="步行"):
        return {"minutes": 12, "km": 0.9, "mode": mode}

    monkeypatch.setattr("app.tools.amap.route_time", fake_route_time)
    segs = c.get(f"/api/trips/{trip_id}/segment-times?day=1").json()["segments"]
    assert len(segs) == 1 and segs[0]["minutes"] == 12 and segs[0]["km"] == 0.9


def test_overseas_segment_times_are_estimated_without_amap(client, monkeypatch):
    c, _ = client
    trip_id = c.post("/api/trips", json={
        "title": "吉隆坡", "destination": "吉隆坡", "days": 1,
    }).json()["id"]
    c.post(f"/api/trips/{trip_id}/stops", json={
        "day": 1, "name": "双子塔", "location": "101.7117,3.1579",
    })
    c.post(f"/api/trips/{trip_id}/stops", json={
        "day": 1, "name": "独立广场", "location": "101.6932,3.1478",
    })

    async def should_not_call(*args, **kwargs):
        raise AssertionError("海外坐标不得调用高德 direction")

    monkeypatch.setattr("app.tools.amap.route_time", should_not_call)
    segment = c.get(f"/api/trips/{trip_id}/segment-times?day=1").json()["segments"][0]
    assert segment["estimated"] is True
    assert segment["minutes"] > 0 and segment["km"] > 0
    assert "海外" in segment["note"]


def test_repair_overseas_coordinates_updates_and_clears_bad_points(client, monkeypatch):
    c, _ = client
    import json
    import app.api.trip_api as api
    from app.db.models import TravelTrip, TravelTripStop

    trip_id = c.post("/api/trips", json={
        "title": "马来西亚", "destination": "吉隆坡 + 仙本那", "days": 1,
    }).json()["id"]
    with api.get_session() as db:
        trip = db.get(TravelTrip, trip_id)
        trip.day_plan_json = json.dumps([{
            "day": 1, "type": "stay", "overnight_required": True, "overnight_city": "吉隆坡",
        }], ensure_ascii=False)
        db.add_all([
            TravelTripStop(trip_id=trip_id, day=1, order_no=0, name="双子塔", location="116.40,39.90"),
            TravelTripStop(trip_id=trip_id, day=1, order_no=1, name="未知小店", location="118.00,31.00"),
        ])
        db.commit()

    async def fake_geocode(names, city, **kwargs):
        assert city == "吉隆坡" and kwargs["force_refresh"] is True
        return {"双子塔": "101.711700,3.157900"}

    monkeypatch.setattr("app.agent.trip_planner.geocode_names", fake_geocode)
    result = c.post(f"/api/trips/{trip_id}/geocode/repair")
    assert result.status_code == 200
    assert result.json()["updated"] == 1 and result.json()["cleared"] == 1
    detail = c.get(f"/api/trips/{trip_id}").json()
    by_name = {s["name"]: s["location"] for s in detail["stops"]}
    assert by_name == {"双子塔": "101.711700,3.157900", "未知小店": ""}


def test_build_issues_flags_multiple_impossible_jumps_as_geocode():
    from app.agent.trip_planner import build_issues

    stops = [
        {"id": "a", "day": 1, "order_no": 0, "name": "吉隆坡机场", "location": "103.0,23.0"},
        {"id": "b", "day": 1, "order_no": 1, "name": "双子塔", "location": "116.4,39.9"},
        {"id": "c", "day": 1, "order_no": 2, "name": "独立广场", "location": "121.4,31.2"},
    ]
    issues = build_issues(stops, total_days=2)
    geocode = [issue for issue in issues if issue["kind"] == "geocode"]
    assert len(geocode) == 1
    assert geocode[0]["action"] == "repair_geocode"
    assert not any(issue["kind"] == "transit" and issue["day"] == 1 for issue in issues)


# ---------- Phase 40：拖拽批量重排 ----------

def test_reorder_stops(client):
    c, _ = client
    trip_id = c.post("/api/trips", json={"title": "t", "destination": "北京"}).json()["id"]
    ids = [c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": n}).json()["id"]
           for n in ("A", "B", "C")]
    d2 = c.post(f"/api/trips/{trip_id}/stops", json={"day": 2, "name": "D"}).json()["id"]

    # Day1 倒序 + 把 D 拖进 Day1 中间；夹带一个非法 id 应被忽略
    r = c.post(f"/api/trips/{trip_id}/stops/reorder",
               json={"day": 1, "ordered_ids": [ids[2], d2, ids[1], "bogus", ids[0]]})
    assert r.status_code == 200 and r.json()["moved"] == 4
    stops = c.get(f"/api/trips/{trip_id}").json()["stops"]
    day1 = [s["name"] for s in stops if s["day"] == 1]
    assert day1 == ["C", "D", "B", "A"]
    assert all(s["day"] == 1 for s in stops)  # D 已跨天移入


# ---------- Phase 41：多人记账本 ----------

def test_settle_expenses_algorithm():
    from app.agent.trip_planner import settle_expenses

    r = settle_expenses([
        # alice 垫 300，三人摊（各 100）
        {"payer_user_id": "ua", "amount": 300, "category": "餐饮", "participants": ["ua", "ub", "uc"]},
        # bob 垫 120，只有 bob/carol 参与（各 60）
        {"payer_user_id": "ub", "amount": 120, "category": "门票", "participants": ["ub", "uc"]},
    ])
    assert r["total"] == 420
    assert r["by_category"] == {"餐饮": 300, "门票": 120}
    pp = {p["user_id"]: p for p in r["per_person"]}
    assert pp["ua"]["balance"] == 200      # 垫 300 摊 100
    assert pp["ub"]["balance"] == -40      # 垫 120 摊 160
    assert pp["uc"]["balance"] == -160     # 摊 160
    # 转账守恒：欠款合计 = 债权合计 = 200
    assert round(sum(t["amount"] for t in r["transfers"]), 2) == 200
    assert all(t["to_user"] == "ua" for t in r["transfers"])  # 都转给 alice
    assert len(r["transfers"]) == 2  # 最小转账次数


def test_settle_ignores_invalid_and_rounds():
    from app.agent.trip_planner import settle_expenses

    r = settle_expenses([
        {"payer_user_id": "ua", "amount": 100, "category": "其他", "participants": ["ua", "ub", "uc"]},
        {"payer_user_id": "ub", "amount": 0, "category": "其他", "participants": ["ua"]},  # 无效
        {"payer_user_id": "ub", "amount": 50, "category": "其他", "participants": []},  # 无效
    ])
    assert r["total"] == 100
    pp = {p["user_id"]: p for p in r["per_person"]}
    assert pp["ub"]["share"] == 33.33  # 100/3 保留两位


def test_expense_api_flow(client):
    c, current = client
    trip_id = c.post("/api/trips", json={"title": "东北行", "destination": "哈尔滨"}).json()["id"]
    c.post(f"/api/trips/{trip_id}/invite", json={"username": "bob"})
    current["id"] = "ub"
    c.post(f"/api/trips/{trip_id}/invites/respond", json={"accept": True})

    # alice 记 300 全员摊；bob 记 120 只 bob 自己参与
    current["id"] = "ua"
    assert c.post(f"/api/trips/{trip_id}/expenses",
                  json={"amount": 300, "title": "晚餐", "category": "餐饮"}).status_code == 200
    assert c.post(f"/api/trips/{trip_id}/expenses",
                  json={"amount": -5, "title": "x"}).status_code == 400
    current["id"] = "ub"
    c.post(f"/api/trips/{trip_id}/expenses",
           json={"amount": 120, "title": "门票", "category": "门票", "participant_usernames": ["bob"]})

    items = c.get(f"/api/trips/{trip_id}/expenses").json()
    assert len(items) == 2 and items[0]["payer"] == "bob" and items[1]["participants"] == ["alice", "bob"]

    s = c.get(f"/api/trips/{trip_id}/expenses/summary").json()
    assert s["total"] == 420
    pp = {p["username"]: p for p in s["per_person"]}
    assert pp["alice"]["balance"] == 150   # 垫300 摊150
    assert pp["bob"]["balance"] == -150    # 垫120 摊270(150+120)
    assert s["transfers"] == [{"from": "bob", "to": "alice", "amount": 150}]
    assert "bob → alice" in s["text"] and "¥150.00" in s["text"]

    # Phase 87b：协同记账放开权限——任何成员都能改/删任何一笔。
    # 原来限制成「只能动自己记的」，导致别人记错的账挂在账本上没人能修（线上反馈）。
    exp_alice = next(i for i in items if i["payer"] == "alice")
    r = c.patch(f"/api/trips/{trip_id}/expenses/{exp_alice['id']}",
                json={"amount": 288, "title": "住宿(改)", "category": "住宿",
                      "payer": "bob", "spent_at": "2026-08-12"})
    assert r.status_code == 200  # bob 能改 alice 记的账
    fixed = next(i for i in c.get(f"/api/trips/{trip_id}/expenses").json()
                 if i["id"] == exp_alice["id"])
    assert fixed["amount"] == 288 and fixed["payer"] == "bob"
    assert fixed["spent_at"] == "2026-08-12"  # 花费日期与记账时间分开
    assert c.delete(f"/api/trips/{trip_id}/expenses/{exp_alice['id']}").status_code == 200


# ---------- Phase 42：分享链接加入 ----------

def test_share_link_flow(client):
    c, current = client
    trip_id = c.post("/api/trips", json={"title": "东北行", "destination": "哈尔滨"}).json()["id"]
    # 开启分享（仅 owner）
    token = c.post(f"/api/trips/{trip_id}/share", json={}).json()["token"]
    assert len(token) == 32
    assert c.post(f"/api/trips/{trip_id}/share", json={}).json()["token"] == token  # 幂等
    # 免登录预览（带鉴权 client 也一样走这个端点，返回最小信息）
    prev = c.get(f"/api/trips/shared/{token}").json()
    assert prev == {"title": "东北行", "destination": "哈尔滨", "inviter": "alice", "member_count": 1}
    # bob 凭 token 加入 → 直接 accepted
    current["id"] = "ub"
    r = c.post("/api/trips/join", json={"token": token})
    assert r.status_code == 200 and r.json()["trip_id"] == trip_id
    assert c.post("/api/trips/join", json={"token": token}).status_code == 200  # 幂等
    assert c.get(f"/api/trips/{trip_id}").status_code == 200  # 已可见
    # editor 不能管理分享
    assert c.post(f"/api/trips/{trip_id}/share", json={}).status_code == 403
    # owner 重置 → 旧 token 失效
    current["id"] = "ua"
    new_token = c.post(f"/api/trips/{trip_id}/share", json={"reset": True}).json()["token"]
    assert new_token != token
    assert c.get(f"/api/trips/shared/{token}").status_code == 404
    current["id"] = "uc"
    assert c.post("/api/trips/join", json={"token": token}).status_code == 404  # 旧链接进不来
    assert c.post("/api/trips/join", json={"token": new_token}).status_code == 200
    # owner 关闭分享
    current["id"] = "ua"
    assert c.delete(f"/api/trips/{trip_id}/share").status_code == 200
    assert c.get(f"/api/trips/shared/{new_token}").status_code == 404


def test_join_upgrades_pending_invite(client):
    """之前被用户名邀请（pending）的人点分享链接进来 = 视为接受。"""
    c, current = client
    trip_id = c.post("/api/trips", json={"title": "t", "destination": "北京"}).json()["id"]
    c.post(f"/api/trips/{trip_id}/invite", json={"username": "bob"})
    token = c.post(f"/api/trips/{trip_id}/share", json={}).json()["token"]
    current["id"] = "ub"
    assert c.post("/api/trips/join", json={"token": token}).status_code == 200
    detail = c.get(f"/api/trips/{trip_id}").json()
    assert "bob" in {m["username"] for m in detail["members"]}


def test_short_link_redirect(client):
    c, current = client
    current["id"] = "ua"
    trip_id = c.post("/api/trips", json={"title": "t", "destination": "北京"}).json()["id"]
    r = c.post(f"/api/trips/{trip_id}/share", json={}).json()
    token, code = r["token"], r["short_code"]
    assert code == token[:8]

    resp = c.get(f"/api/trips/t/{code}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == f"/travel/?join={token}"
    assert c.get("/api/trips/t/nope99", follow_redirects=False).status_code == 404
    # 关闭分享后短链失效
    c.delete(f"/api/trips/{trip_id}/share")
    assert c.get(f"/api/trips/t/{code}", follow_redirects=False).status_code == 404


# ---------- Phase 46：酒店推荐 ----------

def test_search_hotels_parses_amap(monkeypatch):
    import asyncio
    from app.tools import amap

    monkeypatch.setattr(amap, "enabled", lambda: True)

    async def fake_call(client, path, **params):
        if path == "/v3/geocode/geo":
            return {"geocodes": [{
                "location": "91.13,29.65", "country": "中国",
                "province": "西藏自治区", "city": "拉萨市",
                "formatted_address": "西藏自治区拉萨市",
            }]}
        assert params["keywords"] == "酒店" and params["city"] == "拉萨"
        return {"pois": [
            {"name": "拉萨饭店", "location": "91.1,29.6", "address": "北京中路",
             "biz_ext": {"rating": "4.5"}},
            {"name": "无坐标店", "location": [], "address": "x"},  # 无坐标丢弃
            {"name": "香格里拉", "location": "91.0,29.65", "address": ["列表地址"],
             "biz_ext": {"rating": []}},
        ]}

    monkeypatch.setattr(amap, "_call", fake_call)
    hotels = asyncio.run(amap.search_hotels("拉萨"))
    assert [h["name"] for h in hotels] == ["拉萨饭店", "香格里拉"]  # 无坐标被过滤
    assert hotels[0]["rating"] == "4.5" and hotels[0]["address"] == "北京中路"
    assert hotels[1]["rating"] == "" and hotels[1]["address"] == ""  # []rating/list地址→空


def test_search_hotels_disabled_returns_empty(monkeypatch):
    import asyncio
    from app.tools import amap

    monkeypatch.setattr(amap, "enabled", lambda: False)
    assert asyncio.run(amap.search_hotels("拉萨")) == []


def test_trip_hotels_endpoint(client, monkeypatch):
    c, _ = client
    trip_id = c.post("/api/trips", json={"title": "西藏行", "destination": "拉萨"}).json()["id"]

    async def fake_search(city, limit=12):
        return [{"name": f"{city}酒店A", "rating": "4.6", "address": "a", "location": "91,29"}]

    monkeypatch.setattr("app.tools.amap.search_hotels", fake_search)
    # 默认用 trip.destination
    r = c.get(f"/api/trips/{trip_id}/hotels").json()
    assert r["city"] == "拉萨" and r["hotels"][0]["name"] == "拉萨酒店A"
    # city 覆盖（多城行程按城查）
    r2 = c.get(f"/api/trips/{trip_id}/hotels?city=成都").json()
    assert r2["city"] == "成都" and r2["hotels"][0]["name"] == "成都酒店A"


# ---------- Phase 48：每晚住哪按天订房 ----------

def test_regeo_parses_and_falls_back(monkeypatch):
    import asyncio
    from app.tools import amap

    monkeypatch.setattr(amap, "enabled", lambda: True)

    async def fake_call(client, path, **params):
        assert params["location"] == "104.06,30.57"
        return {"regeocode": {"addressComponent": {"city": [], "district": "武侯区", "province": "四川省"}}}

    monkeypatch.setattr(amap, "_call", fake_call)
    # 直辖市 city=[] → 回退 district
    assert asyncio.run(amap.regeo("104.06,30.57")) == "武侯区"


def test_regeo_disabled_empty(monkeypatch):
    import asyncio
    from app.tools import amap
    monkeypatch.setattr(amap, "enabled", lambda: False)
    assert asyncio.run(amap.regeo("104,30")) == ""


def test_day_cities_endpoint(client, monkeypatch):
    c, _ = client
    trip_id = c.post("/api/trips", json={"title": "川藏", "destination": "拉萨"}).json()["id"]
    # Day1 两个点（后者有坐标）；Day2 一个无坐标点 → 回退目的地
    c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "武汉"})
    c.post(f"/api/trips/{trip_id}/stops", json={"day": 1, "name": "成都"})  # fake geocode 给坐标
    c.post(f"/api/trips/{trip_id}/stops", json={"day": 2, "name": "神秘地"})

    async def fake_regeo(loc):
        return "成都市"

    async def fake_geocode(names, city):
        # Day2 的点查不到坐标（返回空），Day1 的有
        return {n: "104,30" for n in names if n != "神秘地"}

    monkeypatch.setattr("app.tools.amap.regeo", fake_regeo)
    monkeypatch.setattr("app.agent.trip_planner.geocode_names", fake_geocode)
    # 重新加 Day2 无坐标点（前面 fixture 的 fake_geocode 给所有点坐标，这里覆盖后重加）
    r = c.get(f"/api/trips/{trip_id}/day-cities").json()
    assert r["default"] == "拉萨"
    assert r["cities"].get("1") == "成都"  # Day1 逆地理编码 + 去「市」后缀统一命名
