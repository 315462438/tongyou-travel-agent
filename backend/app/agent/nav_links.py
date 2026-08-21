"""地点导航 deep link（Phase 100）。

行程板上每个地点都有精确坐标，但用户想真去导航时只能自己打开高德手动搜。
这里拼一条 deep link 直接跳到用户自己的地图 App。

**不消耗我们的高德配额**：请求由用户设备发起、落到高德 C 端产品，与开发者 key 无关，
URL 里也不含任何 key（与「静态图后端签名代拉、key 不进前端」是同一条纪律的另一面）。

## 唯一有技术含量的部分：坐标系分流

`travel_trip_stop.location` 混着两套坐标系（国内高德 GCJ-02 / 海外 WGS-84，
见 `models.py`）。这在站内一直是对的——GCJ 偏移只在中国境内生效，境外 GCJ≈WGS，
而我们全程用高德渲染。但往外发链接时必须显式分流：

| 目标 | 境内 | 境外 |
| --- | --- | --- |
| 高德 | 原样（本来就是 GCJ） | 原样（两者相等） |
| 苹果 | **GCJ→WGS**，否则偏 ~500m | 原样 |

所以只实现 GCJ→WGS 一个方向，且只在「境内 + 苹果」这一格用到。
"""

from __future__ import annotations

import math
from urllib.parse import quote

# GCJ-02 加密算法的常数（公开算法）
_A = 6378245.0          # 克拉索夫斯基椭球长半轴
_EE = 0.00669342162296594323  # 偏心率平方


def out_of_china(lng: float, lat: float) -> bool:
    """是否在 GCJ-02 偏移的适用范围外。

    用经纬度包围盒判定（业界通行做法）。边境地区略有误差，但对导航无影响：
    **误判的后果是境外坐标被多转一次**，而境外本就 GCJ≈WGS，转换量趋近于 0。
    反过来把境内误判成境外才是真错——包围盒取得宽松些正是为了避免这一侧。
    """
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def gcj_to_wgs84(lng: float, lat: float) -> tuple[float, float]:
    """GCJ-02（高德/腾讯）→ WGS-84（GPS/苹果地图/OSM）。

    境外原样返回。这是标准的一次性反解：GCJ 的正向偏移无闭式逆运算，
    但一次减法的残差在米级，对导航足够（要更准需迭代，没必要）。
    """
    if out_of_china(lng, lat):
        return lng, lat
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    d_lng = (d_lng * 180.0) / (_A / sqrt_magic * math.cos(rad_lat) * math.pi)
    return lng - d_lng, lat - d_lat


def parse_location(location: str | None) -> tuple[float, float] | None:
    """`"lng,lat"` → (lng, lat)。任何非法形态返回 None，绝不抛异常。"""
    try:
        lng_s, lat_s = (location or "").split(",")
        lng, lat = float(lng_s), float(lat_s)
    except (ValueError, AttributeError):
        return None
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        return None
    return lng, lat


def build_nav_links(location: str | None, name: str = "") -> dict | None:
    """地点 → `{amap, apple, domestic}` 导航 deep link。无坐标/坐标非法返回 None。

    `name` 只用于地图上显示的标注，编码后拼入；含 `&`/`#` 等字符不会破坏链接结构。

    **`domestic` 是给前端做选择用的，不是调试信息**：选哪个地图应当取决于
    「这个地点在哪」而不是「用户拿的什么设备」——境内地点即使在 Mac/iPhone 上
    也该开高德（国内用户装的是它，POI 与导航体验都对），只有境外才轮到苹果地图
    （高德境外数据弱）。按设备分流是第一版的错误，Mac 用户点境内地点会被送进苹果地图。
    """
    parsed = parse_location(location)
    if parsed is None:
        return None
    lng, lat = parsed
    label = quote((name or "目的地").strip()[:60], safe="")

    # 高德吃 GCJ-02：库里的坐标境内本就是 GCJ、境外两者相等 → 两种情况都原样传
    amap = (f"https://uri.amap.com/navigation?to={lng:.6f},{lat:.6f},{label}"
            f"&mode=car&coordinate=gaode&callnative=1")
    # 苹果吃 WGS-84：境内必须转，否则偏 ~500m（境外 gcj_to_wgs84 内部原样返回）
    w_lng, w_lat = gcj_to_wgs84(lng, lat)
    apple = f"https://maps.apple.com/?daddr={w_lat:.6f},{w_lng:.6f}&q={label}"
    return {"amap": amap, "apple": apple, "domestic": not out_of_china(lng, lat)}
