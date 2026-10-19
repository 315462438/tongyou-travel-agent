"""导入并行、完整缓存、先展示后定位与编辑保护的离线集成测试。"""
import asyncio
import json
import re
import threading
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import trip_api as api
from app.agent.trip_planner import TripImportDays, TripImportSummary
from app.db.models import Base, TravelConversation, TravelMessage, TravelTrip, TravelTripStop
from app.ontology import store
from app.ontology.objects import TripObject, StopObject

GUIDE = "\n\n".join(f"## Day {d} 杭州第{d}天\n09:00 西湖，下午去灵隐寺。" for d in range(1, 4))


class LLM:
    def __init__(self):
        self.calls = []

    def parse(self, prompt, schema, **kwargs):
        self.calls.append(schema.__name__)
        if schema is TripImportSummary:
            return TripImportSummary(title="杭州3天", destination="杭州", days=3,
                                     tips=[{"level": "notice", "content": "提前预约"}])
        day = int(re.search(r"Day (\d+)", prompt)[1])
        return TripImportDays(stops=[{"day": day, "name": f"地点{day}", "start_time": "09:00", "stay_min": 90}],
                              day_plans=[{"day": day, "overnight_city": "杭州", "day_title": f"杭州第{day}天"}])


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine)
    @contextmanager
    def session():
        with maker() as db:
            yield db
    monkeypatch.setattr(api, "get_session", session)
    monkeypatch.setattr(store, "get_session", session)
    with session() as db:
        db.add(TravelConversation(id="conv", user_id="owner"))
        db.add(TravelMessage(id="msg", conversation_id="conv", role="assistant", content=GUIDE))
        db.add(TravelTrip(id="trip", title="导入中", owner_id="owner", days=3,
                          source_message_id="msg", source_conversation_id="conv", ai_status="seeding"))
        db.commit()
    return session


def test_summary_and_days_really_overlap_without_dropping_fields():
    started = threading.Event()
    class Parallel(LLM):
        def parse(self, prompt, schema, **kw):
            if schema is TripImportSummary:
                assert started.wait(1), "summary blocked all day extraction"
            else:
                started.set()
            return super().parse(prompt, schema, **kw)
    draft = asyncio.run(api._extract_import_draft(Parallel(), GUIDE))
    assert len(draft.stops) == 3 and all(s.start_time == "09:00" and s.stay_min == 90 for s in draft.stops)


def test_cache_reuses_summary_and_only_successful_days():
    cache = {}
    class Partial(LLM):
        def parse(self, prompt, schema, **kw):
            if schema is TripImportDays and "Day 2–2" in prompt:
                raise ValueError("temporary")
            return super().parse(prompt, schema, **kw)
    first = asyncio.run(api._extract_import_draft(Partial(), GUIDE, cache=cache))
    assert first.failed_days == [2]
    second_llm = LLM()
    second = asyncio.run(api._extract_import_draft(second_llm, GUIDE, cache=cache))
    assert second_llm.calls == ["TripImportDays"]
    assert len(second.stops) == 3 and not second.failed_days
    never = LLM()
    asyncio.run(api._extract_import_draft(never, GUIDE, cache=cache))
    assert never.calls == []


def test_import_is_visible_before_geocoding_and_manual_edits_survive(database, monkeypatch):
    llm = LLM()
    monkeypatch.setattr("app.llm.client.get_llm", lambda: llm)
    checked = []
    async def geocode(stops, plans, destination, geocode_fn):
        with database() as db:
            trip = db.get(TravelTrip, "trip")
            rows = db.execute(select(TravelTripStop).where(TravelTripStop.trip_id == "trip")).scalars().all()
            assert trip.ai_status == "locating" and len(rows) == 3
            assert rows[0].start_time == "09:00"
            # 模拟用户在后台定位期间改名、填位置与备注。
            rows[0].name = "手动修改"
            rows[0].location = "121,31"
            rows[0].note = "保留编辑"
            rows[1].tags = "no_location"
            db.commit()
        checked.append(True)
        return {(s.day, s.name): "120,30" for s in stops}
    monkeypatch.setattr(api, "_geocode_stops_by_city", geocode)
    api._run_import("trip", GUIDE)
    assert checked
    with database() as db:
        trip = db.get(TravelTrip, "trip")
        rows = db.execute(select(TravelTripStop).where(TravelTripStop.trip_id == "trip")).scalars().all()
        assert trip.ai_status is None
        edited = next(r for r in rows if r.name == "手动修改")
        assert edited.location == "121,31" and edited.note == "保留编辑"
        assert next(r for r in rows if r.tags == "no_location").location is None
        assert all(r.location == "120,30" for r in rows if r.id != edited.id and r.tags != "no_location")
    cache = store.load_import_cache("msg", GUIDE)
    assert cache["summary"]["title"] == "杭州3天"
    assert store.load_import_cache("msg", GUIDE + "修改后") == {}


def test_geocode_failure_keeps_imported_stops(database, monkeypatch):
    monkeypatch.setattr("app.llm.client.get_llm", LLM)
    async def broken(*args):
        raise RuntimeError("provider down")
    monkeypatch.setattr(api, "_geocode_stops_by_city", broken)
    api._run_import("trip", GUIDE)
    with database() as db:
        assert db.get(TravelTrip, "trip").ai_status is None
        assert len(db.execute(select(TravelTripStop)).scalars().all()) == 3


def test_cache_survives_poster_budget_write_and_rejects_modified_source(database):
    cache = {"version": 1, "summary": {"title": "缓存"}, "days": {}}
    store.save_import_cache("msg", GUIDE, cache)
    obj = TripObject(title="杭州", stops=[StopObject(name="西湖")], lanes=["itinerary"])
    store.save_trip_object(obj, message_id="msg", conversation_id="conv", guide=GUIDE)
    assert store.load_import_cache("msg", GUIDE) == cache
    with database() as db:
        db.get(TravelMessage, "msg").content = "修改过的攻略"
        db.commit()
    store.save_import_cache("msg", GUIDE, {"version": 1, "summary": {"title": "旧写入"}})
    assert store.load_import_cache("msg", GUIDE) == cache


def test_concurrent_ontology_requests_only_extract_once(database, monkeypatch):
    from app.ontology import extract
    calls = []
    async def build(*args, **kwargs):
        calls.append(kwargs["lanes"])
        await asyncio.sleep(0.05)
        return TripObject(title="杭州", stops=[StopObject(name="西湖")], lanes=["itinerary"])
    monkeypatch.setattr(extract, "build_trip_object", build)
    async def run():
        return await asyncio.gather(*[store.ensure_trip_object("conv", "msg", llm=object(), need=("itinerary",)) for _ in range(2)])
    out = asyncio.run(run())
    assert len(calls) == 1 and all(t.stops for t in out)


def test_cancelled_waiter_releases_guard_registry():
    from app.ontology.coordination import source_guard, _registry
    async def run():
        entered = asyncio.Event()
        async def waiter():
            entered.set()
            async with source_guard("same"):
                pytest.fail("waiter should have been cancelled")
        async with source_guard("same"):
            task = asyncio.create_task(waiter())
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert "same" not in _registry
    asyncio.run(run())


def test_different_ontology_lanes_still_run_in_parallel_and_merge(database, monkeypatch):
    from app.ontology import extract
    from app.ontology.objects import ExpenseObject
    entered = set()
    async def build(*args, **kwargs):
        lane = kwargs["lanes"][0]
        entered.add(lane)
        for _ in range(30):
            if len(entered) == 2:
                break
            await asyncio.sleep(0.01)
        assert len(entered) == 2, "unrelated lanes were serialized"
        return (TripObject(title="杭州", stops=[StopObject(name="西湖")], lanes=[lane])
                if lane == "itinerary" else TripObject(expenses=[ExpenseObject(category="门票", name="门票", amount=45)], lanes=[lane]))
    monkeypatch.setattr(extract, "build_trip_object", build)
    async def run():
        await asyncio.gather(*[store.ensure_trip_object("conv", "msg", llm=object(), need=(lane,)) for lane in ("itinerary", "cost")])
    asyncio.run(run())
    cached = store.load_trip_object("msg", GUIDE)
    assert set(cached.lanes) == {"itinerary", "cost"} and cached.stops and cached.expenses


def test_retry_preserves_other_days_titles_and_user_global_edits(database, monkeypatch):
    monkeypatch.setattr("app.llm.client.get_llm", LLM)
    async def geocode(*args):
        return {}
    monkeypatch.setattr(api, "_geocode_stops_by_city", geocode)
    api._run_import("trip", GUIDE)
    with database() as db:
        trip = db.get(TravelTrip, "trip")
        trip.title = "我的手动标题"
        trip.day_titles_json = json.dumps({"1": "我改过的第1天", "2": "第二天", "3": "第三天"})
        trip.budget_breakdown_json = json.dumps({"餐饮": 888})
        trip.ai_status = "seeding"
        db.commit()
    api._run_import("trip", GUIDE, only_days={2})
    with database() as db:
        trip = db.get(TravelTrip, "trip")
        assert trip.title == "我的手动标题"
        assert json.loads(trip.day_titles_json)["1"] == "我改过的第1天"
        assert len(json.loads(trip.day_plan_json)) == 3
        assert json.loads(trip.budget_breakdown_json) == {"餐饮": 888}


def test_selecting_a_day_for_route_order_does_not_touch_other_days(database, monkeypatch):
    from app.db.models import TravelUser, TravelTripMember
    user = TravelUser(id="owner", username="owner", password_hash="x")
    with database() as db:
        db.add(user)
        db.add(TravelTripMember(trip_id="trip", user_id="owner", role="owner", status="accepted"))
        for day in (1, 2):
            for index, lng in enumerate((120.0, 120.2, 120.1)):
                db.add(TravelTripStop(trip_id="trip", day=day, name=f"点{day}-{index}", order_no=index, location=f"{lng},30"))
        db.commit()
        before = [(s.id, s.order_no) for s in db.execute(select(TravelTripStop).where(TravelTripStop.day == 2)).scalars()]
        asyncio.run(api.ai_order("trip", db, user, day=1))
        after = [(s.id, s.order_no) for s in db.execute(select(TravelTripStop).where(TravelTripStop.day == 2)).scalars()]
        assert after == before


def test_legacy_cache_with_missing_times_is_not_used_as_complete_import(database):
    store.save_trip_object(
        TripObject(title="杭州", stops=[StopObject(name="西湖")], lanes=["itinerary", "cost"]),
        message_id="msg", conversation_id="conv", guide=GUIDE,
    )
    assert api._draft_from_ontology("trip", GUIDE) is None
