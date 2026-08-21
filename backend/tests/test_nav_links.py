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
    for key in ("amap", "apple"):
        url = links[key]
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


def test_domestic_flag_drives_frontend_choice():
    """`domestic` 让前端按「地点在哪」选地图，而不是按「用户什么设备」。

    第一版按设备判 /Macintosh/，Mac 用户点国内地点被送进苹果地图——境内应当一律高德。
    """
    assert build_nav_links("120.155,30.245", "西湖")["domestic"] is True
    assert build_nav_links("139.745,35.659", "東京タワー")["domestic"] is False


# ---------------------------------------------------------------- 境内外判定（线上 bug 修复）

# 每条陆地边界两侧各取真实城市。重点是**矩形做不到**的中越/中老/中缅/中泰边境带：
# 河内(21.03N,105.85E) 与南宁(22.82N,108.37E) 靠得太近，任何轴对齐矩形都分不开。
OVERSEAS_CITIES = [
    ("仙本那", 118.61, 4.48),    # ← 线上报的这个：点导航开高德，地图停在北京+服务超时
    ("亚庇", 116.07, 5.98),      # 同一个行程里，与吉隆坡分属旧矩形的两侧
    ("吉隆坡", 101.69, 3.14),
    ("曼谷", 100.50, 13.75), ("清迈", 98.98, 18.79),
    ("河内", 105.85, 21.03), ("万象", 102.60, 17.97),
    ("仰光", 96.16, 16.87), ("金边", 104.92, 11.55),
    ("马尼拉", 120.98, 14.60), ("新加坡", 103.82, 1.35),
    ("巴厘岛", 115.19, -8.41),
    ("加德满都", 85.32, 27.71), ("新德里", 77.21, 28.61),
    ("乌兰巴托", 106.92, 47.92), ("海参崴", 131.89, 43.12),
    ("平壤", 125.76, 39.04), ("首尔", 126.98, 37.57), ("东京", 139.69, 35.68),
    ("阿拉木图", 76.89, 43.24), ("比什凯克", 74.60, 42.87),
]

DOMESTIC_CITIES = [
    ("北京", 116.40, 39.90), ("上海", 121.47, 31.23), ("广州", 113.26, 23.13),
    ("杭州", 120.15, 30.27), ("哈尔滨", 126.53, 45.80),
    ("三亚", 109.51, 18.25), ("海口", 110.20, 20.04),          # 海南岛（主多边形切海湾，靠补框）
    ("台北", 121.56, 25.03),                                    # 台湾（同上）
    ("香港", 114.17, 22.32), ("澳门", 113.55, 22.20),
    ("昆明", 102.83, 24.88), ("西双版纳", 100.80, 22.01),        # 与万象/清迈同纬度带
    ("南宁", 108.37, 22.82),                                    # 与河内只差 1.8 度
    ("腾冲", 98.50, 25.02), ("丹东", 124.38, 40.12),
    ("延吉", 129.51, 42.91), ("满洲里", 117.43, 49.60),
    ("漠河", 122.54, 53.47), ("喀什", 75.99, 39.47),
    ("拉萨", 91.14, 29.65), ("日喀则", 88.88, 29.27),
    ("乌鲁木齐", 87.62, 43.83), ("喀纳斯", 87.02, 48.70),        # 阿勒泰，多边形第一版切掉过
    ("敦煌", 94.66, 40.14),
]


@pytest.mark.parametrize("name, lng, lat", OVERSEAS_CITIES)
def test_overseas_cities_classified_as_overseas(name, lng, lat):
    """旧实现是单个经纬度矩形（lat 下界 3.86N），把整片东南亚圈成了「境内」。"""
    assert out_of_china(lng, lat) is True, f"{name} 被判成境内"


@pytest.mark.parametrize("name, lng, lat", DOMESTIC_CITIES)
def test_domestic_cities_classified_as_domestic(name, lng, lat):
    assert out_of_china(lng, lat) is False, f"{name} 被判成境外"


def test_semporna_hotel_end_to_end():
    """线上原始 case：马来西亚仙本那的酒店。两个后果都要消失。"""
    nav = build_nav_links("118.61,4.48", "DBC Hotel Semporna")
    assert nav["domestic"] is False              # ① 不再选高德
    assert "4.480000,118.610000" in nav["apple"]  # ② 坐标不再被凭空偏移 ~380m


def test_overseas_coordinates_are_never_shifted():
    """海外坐标本就是 WGS-84（Phase 62：海外走 Open-Meteo/GeoNames/Photon），
    再做一次 GCJ→WGS 反解就是凭空偏移。"""
    for _name, lng, lat in OVERSEAS_CITIES:
        assert gcj_to_wgs84(lng, lat) == (lng, lat)


def test_domestic_coordinates_are_still_shifted():
    """修边界不能把境内该做的转换一起弄丢。"""
    for _name, lng, lat in DOMESTIC_CITIES:
        w_lng, w_lat = gcj_to_wgs84(lng, lat)
        assert (w_lng, w_lat) != (lng, lat)


def test_google_link_uses_wgs84():
    """谷歌吃 WGS-84，和苹果同一份坐标。"""
    nav = build_nav_links("120.15,30.27", "西湖")
    assert "30.272320,120.145291" in nav["google"]
    assert "30.272320,120.145291" in nav["apple"]


def test_amap_link_never_shifts():
    """高德吃 GCJ：境内库里本就是 GCJ、境外两者相等 → 两种情况都原样传。"""
    for loc in ["120.150000,30.270000", "118.610000,4.480000"]:
        assert loc in build_nav_links(loc, "x")["amap"]
