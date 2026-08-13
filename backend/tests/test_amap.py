"""高德地图接入（Phase 10）单测：签名、来源组装、未配置禁用。全部离线。"""

import asyncio

import pytest

from app.config import settings
from app.tools import amap
from app.tools.amap import build_amap_source, enabled, sign_params


def test_sign_params_known_value():
    """签名算法：字典序拼 k=v& + 私钥取 MD5（与铺探 amap-proxy 一致）"""
    import hashlib

    params = {"address": "黄山", "key": "k1"}
    expect = hashlib.md5("address=黄山&key=k1SECRET".encode()).hexdigest()
    assert sign_params(params, "SECRET") == expect


def test_disabled_without_key(monkeypatch):
    monkeypatch.setattr(settings, "amap_key", "")
    monkeypatch.setattr(settings, "amap_secret", "")
    assert enabled() is False
    assert asyncio.run(build_amap_source("黄山")) is None


def test_build_source_composes_weather_and_pois(monkeypatch):
    monkeypatch.setattr(settings, "amap_key", "k")
    monkeypatch.setattr(settings, "amap_secret", "s")

    responses = {
        "/v3/geocode/geo": {"status": "1", "geocodes": [{
            "adcode": "341003", "city": "黄山市", "province": "安徽省",
            "country": "中国", "formatted_address": "安徽省黄山市", "location": "118.17,30.13",
        }]},
        "/v3/weather/weatherInfo": {"status": "1", "forecasts": [{"casts": [
            {"date": "2026-07-06", "dayweather": "小雨", "nighttemp": "24", "daytemp": "33"},
            {"date": "2026-07-07", "dayweather": "多云", "nighttemp": "23", "daytemp": "31"},
        ]}]},
        "/v3/place/text": {"status": "1", "pois": [
            {"name": "黄山风景区", "address": "汤口镇", "location": "118.16,30.13",
             "biz_ext": {"rating": "4.8"}},
            {"name": "光明顶", "address": [], "location": "118.15,30.12", "biz_ext": {"rating": []}},
        ]},
    }

    async def fake_call(client, path, **params):
        return responses[path]

    monkeypatch.setattr(amap, "_call", fake_call)
    src = asyncio.run(build_amap_source("黄山"))
    assert src is not None and src["site"] == "amap"
    s = src["summary"]
    assert "07-06 小雨 24-33°C" in s
    assert "黄山风景区｜评分4.8｜汤口镇｜坐标118.16,30.13" in s
    assert "光明顶" in s and "评分[]" not in s  # 空评分/列表地址不渲染成垃圾


def test_build_source_geocode_failure_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "amap_key", "k")
    monkeypatch.setattr(settings, "amap_secret", "s")

    async def fake_call(client, path, **params):
        return None

    monkeypatch.setattr(amap, "_call", fake_call)
    assert asyncio.run(build_amap_source("黄山")) is None
