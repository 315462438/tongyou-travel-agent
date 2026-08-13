"""Phase 79：第一视角旅行实境预演。全部离线。"""

from types import SimpleNamespace

import pytest

from app.api import immersive_api


def test_normalize_destination_keeps_one_short_place():
    assert immersive_api.normalize_destination(" 天堂寨 ") == "天堂寨"
    assert immersive_api.normalize_destination("武汉、开封、洛阳") == "武汉"
    assert len(immersive_api.normalize_destination("很长的目的地" * 10)) == 24


def test_safe_photo_only_accepts_amap_official_hosts():
    assert immersive_api._safe_photo("https://store.is.autonavi.com/a.jpg")
    assert immersive_api._safe_photo("https://example.com/a.jpg") == ""
    assert immersive_api._safe_photo("javascript:alert(1)") == ""


@pytest.mark.asyncio
async def test_tiantangzhai_preview_has_six_scenes_branch_and_real_images(monkeypatch):
    async def fake_poi(_client, keyword, city=""):
        return {
            "name": keyword,
            "photo": f"https://store.is.autonavi.com/{len(keyword)}.jpg",
        }

    monkeypatch.setattr(immersive_api, "amap_enabled", lambda: True)
    monkeypatch.setattr(immersive_api, "search_poi", fake_poi)
    monkeypatch.setattr(immersive_api, "search_destination_cover", lambda *_: None)

    payload = await immersive_api.build_immersive_preview("天堂寨")

    assert payload["destination"] == "天堂寨"
    assert payload["has_images"] is True
    assert len(payload["scenes"]) == 6
    assert len(payload["scenes"][1]["choices"]) == 2
    route_scene = payload["scenes"][2]
    assert route_scene["variants"]["summit"]["energy_delta"] < route_scene["variants"]["canyon"]["energy_delta"]
    assert all(scene["image"].startswith("https://store.is.autonavi.com/") for scene in payload["scenes"])
    assert all("query" not in scene for scene in payload["scenes"]), "第三方查询词不属于前端契约"


@pytest.mark.asyncio
async def test_preview_survives_all_image_failures(monkeypatch):
    async def broken_poi(*_args, **_kwargs):
        raise RuntimeError("amap down")

    async def broken_cover(*_args, **_kwargs):
        raise RuntimeError("amap down")

    monkeypatch.setattr(immersive_api, "amap_enabled", lambda: True)
    monkeypatch.setattr(immersive_api, "search_poi", broken_poi)
    monkeypatch.setattr(immersive_api, "search_destination_cover", broken_cover)

    payload = await immersive_api.build_immersive_preview("天堂寨")
    assert len(payload["scenes"]) == 6
    assert payload["has_images"] is False
    assert all(scene["image"] == "" for scene in payload["scenes"])


@pytest.mark.asyncio
async def test_preview_endpoint_uses_ttl_cache(monkeypatch):
    calls = 0

    async def fake_build(destination):
        nonlocal calls
        calls += 1
        return {
            "destination": destination,
            "title": destination,
            "subtitle": "x",
            "disclaimer": "x",
            "scenes": [],
            "has_images": True,
        }

    immersive_api._preview_cache.clear()
    monkeypatch.setattr(immersive_api, "build_immersive_preview", fake_build)
    user = SimpleNamespace(id="u1")

    first = await immersive_api.immersive_preview(destination="天堂寨", user=user)
    second = await immersive_api.immersive_preview(destination="天堂寨", user=user)

    assert first == second
    assert calls == 1


def test_generic_destination_keeps_the_same_scene_contract():
    scenes = immersive_api._generic_scenes("平潭岛")
    assert len(scenes) == 6
    assert scenes[1]["choices"]
    assert set(scenes[2]["variants"]) == {"canyon", "summit"}
