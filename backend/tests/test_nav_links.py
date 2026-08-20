"""地点导航 deep link（Phase 100）单测。纯函数，全离线。

关切：`travel_trip_stop.location` 混着两套坐标系（境内 GCJ-02 / 境外 WGS-84）。
在站内一直是对的（全程高德渲染），但往外发链接时必须分流——**苹果地图吃 WGS，
境内不转就偏 ~500m，直接把人导到别的街区**。这类错误不会报任何异常。
"""

import math
from urllib.parse import parse_qs, urlparse

import pytest

from app.agent.nav_links import (
    build_nav_links,
    gcj_to_wgs84,
    out_of_china,
    parse_location,
)


def _meters(lng1, lat1, lng2, lat2) -> float:
    dx = (lng2 - lng1) * 111320 * math.cos(math.radians(lat1))
    dy = (lat2 - lat1) * 110540
    return math.hypot(dx, dy)


# ---------- 坐标系分流（核心） ----------

@pytest.mark.parametrize("name,lng,lat", [
    ("天安门", 116.397, 39.909),
    ("西湖", 120.155, 30.245),
    ("外滩", 121.490, 31.240),
    ("乌鲁木齐", 87.617, 43.793),
])
def test_domestic_shift_is_in_the_right_ballpark(name, lng, lat):
    """境内偏移必须落在 100–1000m：太小说明没转，太大说明转错了。

    两个方向都要卡——「不转」和「转错」的后果一样严重，而且都是静默的。
    """
    w_lng, w_lat = gcj_to_wgs84(lng, lat)
    shift = _meters(lng, lat, w_lng, w_lat)
    assert 100 < shift < 1000, f"{name} 偏移 {shift:.0f}m 不在合理区间"


@pytest.mark.parametrize("name,lng,lat", [
    ("东京塔", 139.745, 35.659),
    ("纽约", -74.006, 40.713),
    ("新加坡", 103.852, 1.290),
    ("伦敦", -0.128, 51.507),
])
def test_overseas_coordinates_are_untouched(name, lng, lat):
    """境外 GCJ≈WGS，必须原样——多转一次就是凭空引入误差。"""
    assert gcj_to_wgs84(lng, lat) == (lng, lat)


@pytest.mark.parametrize("lng,lat,expect_out", [
    (116.397, 39.909, False),   # 北京
    (121.490, 31.240, False),   # 上海
    (87.617, 43.793, False),    # 乌鲁木齐（西部边缘仍在境内）
    (139.745, 35.659, True),    # 东京
    (-74.006, 40.713, True),    # 纽约
    (103.852, 1.290, True),     # 新加坡
])
def test_out_of_china_boundary(lng, lat, expect_out):
    assert out_of_china(lng, lat) is expect_out


# ---------- 链接构造 ----------

def test_amap_keeps_gcj_apple_gets_wgs():
    """同一个境内坐标：高德原样、苹果已转——这是整个改动的要点。"""
    links = build_nav_links("120.155,30.245", "西湖")
    amap_to = parse_qs(urlparse(links["amap"]).query)["to"][0]
    amap_lng, amap_lat = float(amap_to.split(",")[0]), float(amap_to.split(",")[1])
    assert (round(amap_lng, 5), round(amap_lat, 5)) == (120.155, 30.245), "高德不该转"

    apple_q = parse_qs(urlparse(links["apple"]).query)
    a_lat, a_lng = (float(v) for v in apple_q["daddr"][0].split(","))
    assert _meters(120.155, 30.245, a_lng, a_lat) > 100, "苹果必须转"


def test_overseas_stop_gets_identical_coords_in_both_links():
    links = build_nav_links("139.745,35.659", "東京タワー")
    amap_to = parse_qs(urlparse(links["amap"]).query)["to"][0].split(",")
    a_lat, a_lng = (float(v) for v in parse_qs(urlparse(links["apple"]).query)["daddr"][0].split(","))
    assert round(float(amap_to[0]), 5) == round(a_lng, 5)
    assert round(float(amap_to[1]), 5) == round(a_lat, 5)


def test_apple_uses_lat_lng_order():
    """高德是 lng,lat；苹果是 lat,lng——顺序写反会把人导到地球另一边，且不会报错。"""
    links = build_nav_links("120.155,30.245", "西湖")
    a_first, a_second = (float(v) for v in
                         parse_qs(urlparse(links["apple"]).query)["daddr"][0].split(","))
    assert 29 < a_first < 31, "苹果第一个数应该是纬度"
    assert 119 < a_second < 121, "苹果第二个数应该是经度"


@pytest.mark.parametrize("name", [
    "灵隐寺 & 飞来峰", "#网红打卡点", "海底捞(西湖店)", "Café de Paris", "a" * 200,
])
def test_names_are_encoded_and_do_not_break_the_url(name):
    """名称里的 & / # / 空格必须编码，否则会截断或伪造出新的查询参数。"""
    links = build_nav_links("120.155,30.245", name)
    for url in links.values():
        assert " " not in url
        assert url.count("#") == 0
        # 高德的参数个数固定，出现多余的说明 & 没被编码
        assert len(parse_qs(urlparse(links["amap"]).query)) == 4


@pytest.mark.parametrize("bad", [
    None, "", "   ", "abc", "120.155", "120.155,30.245,7", "a,b",
    "999,30", "120,999",           # 越界
])
def test_invalid_location_returns_none(bad):
    """无坐标/坐标非法一律返回 None，绝不抛异常——序列化每个地点时都会走到这里。"""
    assert build_nav_links(bad, "某处") is None
    assert parse_location(bad) is None


def test_missing_name_still_builds():
    links = build_nav_links("120.155,30.245", "")
    assert links and "amap" in links and "apple" in links


# ---------- 接线 ----------

def test_stop_dict_exposes_nav():
    from app.api.trip_api import _stop_dict
    from app.db.models import TravelTripStop

    with_loc = TravelTripStop(id="s1", trip_id="t1", day=1, order_no=0,
                              name="西湖", location="120.155,30.245")
    assert _stop_dict(with_loc)["nav"]["amap"].startswith("https://uri.amap.com/")

    without = TravelTripStop(id="s2", trip_id="t1", day=1, order_no=1, name="待定", location="")
    assert _stop_dict(without)["nav"] is None
