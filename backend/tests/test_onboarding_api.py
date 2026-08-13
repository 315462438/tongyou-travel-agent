"""Phase 75：新用户空状态素材。"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import onboarding_api
from app.db.models import Base, TravelConversation, TravelMemory, TravelUser


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _user(db, name):
    u = TravelUser(username=name, password_hash="x")
    db.add(u)
    db.commit()
    return u


def _conv(db, user, destination, days_ago=0):
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db.add(TravelConversation(user_id=user.id, title=destination,
                              destination=destination, updated_at=when))
    db.commit()


def test_first_city_splits_multi_city_destinations():
    """「武汉,开封,洛阳,西安」直接当 chip 会是一张念不出来的卡片。"""
    assert onboarding_api.first_city("武汉,开封,洛阳,西安") == "武汉"
    assert onboarding_api.first_city("大理，丽江") == "大理"
    assert onboarding_api.first_city("平潭岛") == "平潭岛"
    assert onboarding_api.first_city("") == ""


def test_trending_excludes_internal_accounts(db):
    """evalbot 一个人就能把「成都」刷成第一名——必须排除，否则热门榜彻底失真。"""
    bot = _user(db, "evalbot")
    real = _user(db, "猫巷子")
    for _ in range(10):
        _conv(db, bot, "成都")
    _conv(db, real, "平潭岛")

    trending = onboarding_api.trending_destinations(db)
    assert "成都" not in trending
    assert trending == ["平潭岛"]


def test_trending_ranks_by_popularity_and_dedupes(db):
    a, b = _user(db, "a"), _user(db, "b")
    _conv(db, a, "平潭岛")
    _conv(db, b, "平潭岛")
    _conv(db, a, "武功山")
    _conv(db, b, "武汉,开封")   # 拆首城后是「武汉」
    trending = onboarding_api.trending_destinations(db)
    assert trending[0] == "平潭岛"
    assert len(trending) == len(set(trending)), "拆首城后必须去重"


def test_trending_ignores_stale_conversations(db):
    u = _user(db, "u")
    _conv(db, u, "老目的地", days_ago=onboarding_api.TRENDING_DAYS + 5)
    _conv(db, u, "新目的地", days_ago=1)
    assert onboarding_api.trending_destinations(db) == ["新目的地"]


def test_trending_empty_when_no_data(db):
    """没有数据就返回空 —— 前端回退静态示例，不能白屏。"""
    assert onboarding_api.trending_destinations(db) == []


def test_home_city_parsed_from_memory(db):
    u = _user(db, "u")
    db.add(TravelMemory(user_id=u.id, key="常驻城市", content="常驻城市：合肥"))
    db.commit()
    assert onboarding_api.home_city_of(db, u.id) == "合肥"


def test_home_city_absent_returns_empty(db):
    """没有常驻城市记忆时不能凭空编一个出发地。"""
    u = _user(db, "u")
    assert onboarding_api.home_city_of(db, u.id) == ""


def test_onboarding_reports_history_flag(db):
    u = _user(db, "u")
    assert onboarding_api.onboarding(db=db, user=u)["has_history"] is False
    _conv(db, u, "平潭岛")
    assert onboarding_api.onboarding(db=db, user=u)["has_history"] is True


def test_trending_merges_prefixed_variants(db):
    """真实数据里同时有「平潭岛」和「福建平潭岛」——两张 chip 并排出现会穿帮。"""
    a, b, c = _user(db, "a"), _user(db, "b"), _user(db, "c")
    _conv(db, a, "福建平潭岛")
    _conv(db, b, "平潭岛")
    _conv(db, c, "武功山")
    trending = onboarding_api.trending_destinations(db)
    assert "平潭岛" in trending
    assert "福建平潭岛" not in trending, "包含关系应保留更短的地名"
    assert "武功山" in trending
    assert len(trending) == 2


def test_cover_destinations_are_deduped_cleaned_and_limited():
    assert onboarding_api.clean_cover_destinations([
        "武汉,开封", "武汉", "平潭岛", "", "武功山", "杭州", "大理",
    ]) == ["武汉", "平潭岛", "武功山", "杭州", "大理"]


@pytest.mark.asyncio
async def test_destination_covers_cache_success_and_ignore_failure(db, monkeypatch):
    user = _user(db, "cover-user")
    calls: list[str] = []

    async def fake_cover(_client, city):
        calls.append(city)
        if city == "武功山":
            raise RuntimeError("amap unavailable")
        return f"https://store.is.autonavi.com/{city}.jpg"

    onboarding_api._cover_cache.clear()
    monkeypatch.setattr(onboarding_api, "amap_enabled", lambda: True)
    monkeypatch.setattr(onboarding_api, "search_destination_cover", fake_cover)

    first = await onboarding_api.destination_covers(
        destinations=["平潭岛", "武功山"], user=user,
    )
    second = await onboarding_api.destination_covers(
        destinations=["平潭岛", "武功山"], user=user,
    )

    assert first == {"covers": {"平潭岛": "https://store.is.autonavi.com/平潭岛.jpg"}}
    assert second == first
    assert calls == ["平潭岛", "武功山"], "成功和空结果都应命中 TTL 缓存"
