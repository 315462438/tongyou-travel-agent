"""手账海报（Phase 13）单测：payload 组装、URL 构造、staticmap 校验。离线。"""

from urllib.parse import parse_qs, urlparse

from app.agent.poster import _build_poster_payload, _img_proxy, _route_distance, _staticmap_url
from app.api.staticmap_api import _valid_pt
from app.schemas.poster_schema import (
    PosterData,
    PosterDayMeta,
    PosterFood,
    PosterHotel,
    PosterSpecialty,
    PosterStop,
)


def test_img_proxy_encodes():
    assert _img_proxy("http://store.is.autonavi.com/a") == "/travel/api/img?u=http%3A%2F%2Fstore.is.autonavi.com%2Fa"


def test_staticmap_url_format():
    pts = [
        {"location": "104.06,30.62", "order": 1, "day": 1},
        {"location": "104.05,30.55", "order": 2, "day": 1},
    ]
    url = _staticmap_url(pts)
    q = parse_qs(urlparse(url).query)
    assert url.startswith("/travel/api/staticmap?")
    assert q["pts"][0] == "104.06,30.62;104.05,30.55"
    assert q["labels"][0] == "1,2" and q["days"][0] == "1,1"


def test_build_payload_groups_by_day_and_renumbers():
    data = PosterData(
        title="成都2日手账", subtitle="巴适", theme="烟火·慢生活", destination="成都", stops=[],
        day_meta=[PosterDayMeta(day=1, title="市井线", subtitle="老成都烟火")],
    )
    enriched = [
        {"day": 1, "order": 5, "name": "宽窄巷子", "type": "spot", "note": "老成都", "location": "104.06,30.66", "photo": "/p1"},
        {"day": 1, "order": 2, "name": "玉林", "type": "food", "note": "串串", "location": "104.05,30.55", "photo": "/p2"},
        {"day": 2, "order": 1, "name": "九眼桥", "type": "checkin", "note": "夜景", "location": "104.09,30.64", "photo": "/p3"},
    ]
    payload = _build_poster_payload(data, enriched, {}, {})
    assert payload["title"] == "成都2日手账" and payload["theme"] == "烟火·慢生活"
    assert [d["day"] for d in payload["days"]] == [1, 2]
    d1 = payload["days"][0]
    # 天内按 order 排序后重新编号 1,2；玉林(order2)在宽窄巷子(order5)前
    assert [s["name"] for s in d1["stops"]] == ["玉林", "宽窄巷子"]
    assert [s["order"] for s in d1["stops"]] == [1, 2]
    assert d1["title"] == "市井线" and d1["subtitle"] == "老成都烟火"
    assert d1["distance"].startswith("约") and d1["duration"] in ("建议半日游", "建议整日游")
    # 没配 day_meta 的第二天回退默认路线名
    assert payload["days"][1]["title"] == "Day 2 路线"
    assert payload["overall_map"].startswith("/travel/api/staticmap")  # 3 点 ≤10，全程图仍出
    assert d1["map"].startswith("/travel/api/staticmap")  # 逐天小图


def test_build_payload_right_column_sections():
    data = PosterData(
        title="杭州3日", destination="杭州", stops=[],
        hotels=[PosterHotel(name="西湖国宾馆", area="西湖畔", price="¥900/晚", note="园林景观")],
        foods=[PosterFood(name="西湖醋鱼", note="酸甜鲜嫩")],
        specialties=[PosterSpecialty(name="西湖龙井", note="十大名茶")],
        tips=["最佳季节 3-5 月", "景区步行为主"],
    )
    enriched = [
        {"day": 1, "order": 1, "name": "断桥", "type": "spot", "note": "", "location": "120.15,30.26", "photo": ""},
        {"day": 1, "order": 2, "name": "雷峰塔", "type": "spot", "note": "", "location": "120.14,30.23", "photo": ""},
    ]
    payload = _build_poster_payload(data, enriched, {"西湖国宾馆": "/h1"}, {"西湖醋鱼": "/f1"})
    assert payload["hotels"][0]["photo"] == "/h1" and payload["hotels"][0]["price"] == "¥900/晚"
    assert payload["foods"][0]["photo"] == "/f1" and payload["foods"][0]["name"] == "西湖醋鱼"
    assert payload["specialties"][0]["name"] == "西湖龙井"
    assert payload["tips"] == ["最佳季节 3-5 月", "景区步行为主"]


def test_route_distance_haversine():
    stops = [{"location": "120.15,30.26"}, {"location": "120.14,30.23"}]
    d = _route_distance(stops)
    assert 2 < d < 5  # 断桥→雷峰塔 约 3.4km
    assert _route_distance([{"location": "120.15,30.26"}]) == 0.0  # 单点无距离


def test_build_payload_empty():
    assert _build_poster_payload(PosterData(title="x"), [], {}, {}) == {}


def test_staticmap_valid_pt():
    assert _valid_pt("104.06,30.62")
    assert not _valid_pt("104.06")
    assert not _valid_pt("abc,def")
    assert not _valid_pt("200,30")  # 经度越界
    assert not _valid_pt("104,80")  # 纬度越界


def test_poster_schema_defaults():
    s = PosterStop(day=1, name="宽窄巷子")
    assert s.type == "spot" and s.order == 0 and s.note == ""
