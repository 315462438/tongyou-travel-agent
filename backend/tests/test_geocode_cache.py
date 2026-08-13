"""Phase 55：geocode 持久缓存单测（sqlite 内存库，离线）。

验证：首次未命中打高德并写回缓存；再次同名直接命中缓存、不再打高德。
"""

import asyncio
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.trip_planner import geocode_names
from app.db.models import Base, TravelGeocode
from app.tools.geocode import (
    GeocodeContext, _global_search, city_center_for_name, geocode_cache_key,
    global_search_poi, overseas_search_name,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def wired(monkeypatch, db):
    @contextmanager
    def fake_session():
        yield db

    monkeypatch.setattr("app.db.session.get_session", fake_session)
    calls: list[str] = []

    async def fake_context(city, force_refresh=False):
        return GeocodeContext(city=city, country_code="cn", lng=104.07, lat=30.67)

    async def fake_search_poi(client, keyword, city=""):
        calls.append(keyword)
        coords = {"宽窄巷子": "104.06,30.67", "武侯祠": "104.05,30.64"}
        loc = coords.get(keyword)
        return {"location": loc, "city": "成都市"} if loc else None

    monkeypatch.setattr("app.tools.geocode.resolve_city_context", fake_context)
    monkeypatch.setattr("app.tools.amap.search_poi", fake_search_poi)
    return db, calls


def test_geocode_cache_hit_skips_amap(wired):
    db, calls = wired
    # 首次：两个都未命中 → 打高德两次 + 写回缓存
    r1 = asyncio.run(geocode_names(["宽窄巷子", "武侯祠"], "成都"))
    assert r1 == {"宽窄巷子": "104.06,30.67", "武侯祠": "104.05,30.64"}
    assert sorted(calls) == ["宽窄巷子", "武侯祠"]
    assert db.execute(select(TravelGeocode)).scalars().all().__len__() == 2  # 命中已落库

    # 再次同名：全部命中缓存 → 不再打高德
    calls.clear()
    r2 = asyncio.run(geocode_names(["宽窄巷子", "武侯祠"], "成都"))
    assert r2 == r1
    assert calls == []  # 零次高德调用


def test_geocode_partial_hit_only_queries_misses(wired):
    db, calls = wired
    asyncio.run(geocode_names(["宽窄巷子"], "成都"))  # 预热缓存
    calls.clear()
    # 一个已缓存、一个新 → 只对新的打高德
    r = asyncio.run(geocode_names(["宽窄巷子", "武侯祠"], "成都"))
    assert r == {"宽窄巷子": "104.06,30.67", "武侯祠": "104.05,30.64"}
    assert calls == ["武侯祠"]  # 只查未命中的那个


def test_geocode_miss_not_cached(wired):
    db, calls = wired
    # 查不到坐标的名字不写缓存 → 下次仍会重试（名称可能后续修正）
    asyncio.run(geocode_names(["不存在的地方"], "成都"))
    assert db.execute(select(TravelGeocode)).scalars().all() == []
    calls.clear()
    asyncio.run(geocode_names(["不存在的地方"], "成都"))
    assert calls == ["不存在的地方"]  # 未缓存，仍重查


def test_geocode_city_scoped_key(wired):
    db, _ = wired
    asyncio.run(geocode_names(["宽窄巷子"], "成都"))
    # 不同城市同名 → 不同 key，不会误命中
    keys = {r.key for r in db.execute(select(TravelGeocode)).scalars()}
    assert "v2|amap|cn|成都|宽窄巷子" in keys


def test_overseas_uses_global_provider_and_ignores_poisoned_legacy_cache(monkeypatch, db):
    """旧缓存即使存了国内误坐标，海外 v2 provider/country 键也不能命中它。"""
    @contextmanager
    def fake_session():
        yield db

    db.add(TravelGeocode(key="吉隆坡|双子塔", location="116.40,39.90"))
    db.commit()
    calls: list[str] = []

    async def fake_context(city, force_refresh=False):
        return GeocodeContext(city=city, country_code="my", lng=101.6869, lat=3.1390)

    async def fake_global(name, context):
        calls.append(name)
        return {"location": "101.711700,3.157900", "country_code": "my"}

    async def should_not_call_amap(*args, **kwargs):
        raise AssertionError("海外地点不得调用高德国内 POI")

    monkeypatch.setattr("app.db.session.get_session", fake_session)
    monkeypatch.setattr("app.tools.geocode.resolve_city_context", fake_context)
    monkeypatch.setattr("app.tools.geocode.global_search_poi", fake_global)
    monkeypatch.setattr("app.tools.amap.search_poi", should_not_call_amap)

    result = asyncio.run(geocode_names(["双子塔"], "吉隆坡"))
    assert result == {"双子塔": "101.711700,3.157900"}
    assert calls == ["Petronas Towers"]  # Photon 只索引英文/当地名，中文先转换
    keys = {row.key for row in db.execute(select(TravelGeocode)).scalars()}
    assert "v2|photon|my|吉隆坡|双子塔" in keys


def test_force_refresh_bypasses_v2_cache(monkeypatch, wired):
    db, calls = wired
    asyncio.run(geocode_names(["宽窄巷子"], "成都"))
    calls.clear()
    asyncio.run(geocode_names(["宽窄巷子"], "成都", force_refresh=True))
    assert calls == ["宽窄巷子"]


def test_overseas_cache_outside_city_radius_is_ignored(monkeypatch, db):
    @contextmanager
    def fake_session():
        yield db

    context = GeocodeContext(city="仙本那", country_code="my", lng=118.6111, lat=4.4811)
    key = geocode_cache_key("photon", "my", "仙本那", "汀巴汀巴")
    db.add(TravelGeocode(key=key, location="117.984900,5.770150"))  # 距仙本那约 160km
    db.commit()
    calls: list[str] = []

    async def fake_context(city, force_refresh=False):
        return context

    async def fake_global(name, ctx):
        calls.append(name)
        return None

    monkeypatch.setattr("app.db.session.get_session", fake_session)
    monkeypatch.setattr("app.tools.geocode.resolve_city_context", fake_context)
    monkeypatch.setattr("app.tools.geocode.global_search_poi", fake_global)
    assert asyncio.run(geocode_names(["汀巴汀巴"], "仙本那")) == {}
    assert calls == ["Timba Timba Island"]  # 坏缓存被忽略，重新查询


def test_global_candidate_requires_country_and_city_distance(monkeypatch):
    context = GeocodeContext(city="吉隆坡", country_code="my", lng=101.6869, lat=3.1390)

    async def fake_search(**params):
        assert params["countrycodes"] == "my"
        return [
            # 同名但国家不符
            {"lon": "101.70", "lat": "3.15", "address": {"country_code": "sg"}},
            # 国家正确但离吉隆坡过远
            {"lon": "118.61", "lat": "4.48", "address": {"country_code": "my"}},
            # 正确候选
            {"lon": "101.7117", "lat": "3.1579", "display_name": "双子塔",
             "address": {"country_code": "my"}},
        ]

    monkeypatch.setattr("app.tools.geocode._global_search", fake_search)
    result = asyncio.run(global_search_poi("双子塔", context))
    assert result and result["location"] == "101.711700,3.157900"


def test_photon_and_open_meteo_responses_are_normalized(monkeypatch):
    def fake_request(kind, params):
        if kind == "city":
            assert params["language"] == "zh"
            return [{
                "name": "仙本那", "longitude": 118.61119, "latitude": 4.48178,
                "country_code": "MY", "admin1": "沙巴州", "country": "马来西亚",
            }]
        assert params["countrycode"] == "MY"
        return [{
            "properties": {"name": "Petronas Towers", "countrycode": "MY"},
            "geometry": {"coordinates": [101.7112048, 3.1579679]},
        }]

    monkeypatch.setattr("app.tools.geocode._global_request", fake_request)
    city = asyncio.run(_global_search(q="仙本那", featuretype="city"))
    poi = asyncio.run(_global_search(
        q="Petronas Towers", countrycodes="my", lat=3.139, lon=101.6869,
    ))
    assert city[0]["address"]["country_code"] == "my"
    assert poi[0]["display_name"] == "Petronas Towers"
    assert poi[0]["lon"] == 101.7112048
    assert overseas_search_name("双子塔") == "Petronas Towers"
    semporna = GeocodeContext(city="仙本那", country_code="my", lng=118.6111, lat=4.4811)
    assert city_center_for_name("仙本那镇", semporna) == "118.611100,4.481100"
