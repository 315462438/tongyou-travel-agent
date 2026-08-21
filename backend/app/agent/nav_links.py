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


# 简化的中国大陆国界多边形（顺时针，度）。顶点取自各段边界上的标志性位置，
# 边界处有几公里误差——相比它替换掉的那个矩形（把整片东南亚判成境内，误差 1000+ 公里）
# 完全可以接受。纯常量、零依赖、零网络。
_CHINA_MAINLAND = [
    (134.77, 48.45),  # 抚远 东极
    (131.30, 44.00), (131.00, 42.90),  # 中俄朝交界 图们江口
    (128.00, 42.00), (124.40, 40.00),  # 长白山 → 丹东鸭绿江口
    (122.00, 39.00), (122.10, 37.50),  # 辽东半岛 → 成山头（渤海按直线切）
    (120.00, 34.00), (121.90, 30.90),  # 苏北海岸 → 杭州湾
    (121.60, 28.00), (119.50, 25.50),  # 浙闽海岸
    (117.00, 23.50), (114.50, 22.15),  # 汕头 → 香港以南
    (113.30, 21.85), (110.00, 21.00),  # 澳门以南 → 雷州半岛
    (108.50, 21.50), (106.70, 22.00),  # 北部湾 → 友谊关（中越）
    (105.30, 23.30), (103.50, 22.50),  # 中越陆界 → 河口
    (101.80, 21.15), (99.90, 22.00),   # 西双版纳南端（大陆最南）→ 中缅
    (97.50, 24.00), (97.50, 28.20),    # 德宏 → 独龙江
    (96.20, 29.00), (92.00, 27.70),    # 藏南
    (88.00, 27.30), (85.00, 28.30),    # 不丹/尼泊尔
    (81.00, 30.30), (78.70, 32.50),    # 阿里 → 阿克赛钦
    (76.00, 35.50), (74.50, 37.00),    # 喀喇昆仑 → 瓦罕
    (73.50, 38.60), (75.00, 40.50),    # 帕米尔（最西）→ 中吉
    (80.30, 43.00), (82.50, 45.20),    # 霍尔果斯 → 中哈
    (85.00, 47.00), (87.30, 49.17),    # 中哈 → 中哈俄蒙四国交界（新疆最北 阿勒泰）
    (90.60, 47.85), (95.00, 44.00),    # 中蒙边界东南走向
    (96.40, 42.80), (100.00, 42.60),
    (105.00, 41.80), (110.00, 42.50),
    (115.00, 43.50), (119.90, 45.50),
    (119.90, 47.00), (117.40, 49.60),  # 满洲里
    (120.00, 52.00), (122.00, 53.55),  # 漠河（最北）
    (125.00, 53.20), (127.50, 50.20),  # 黑河
    (130.70, 48.90),
]

# 主多边形按直线切过海湾，这两块岛屿落在外面；高德对两地都有数据，单独补框。
_CHINA_ISLANDS = [
    (108.50, 111.10, 18.10, 20.20),  # 海南岛
    (119.30, 122.10, 21.80, 25.40),  # 台湾
]


def _in_polygon(lng: float, lat: float, polygon: list[tuple[float, float]]) -> bool:
    """射线法。顶点上/边上的点归属不保证，对导航无影响。"""
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lng < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def out_of_china(lng: float, lat: float) -> bool:
    """是否在 GCJ-02 偏移的适用范围外（即：不在中国）。

    ⚠️ 这里**曾经是一个经纬度矩形**（`73.66<lng<135.05 and 3.86<lat<53.55`），
    而那个矩形的纬度下界把**整片东南亚**圈成了「境内」：仙本那(4.48N)、亚庇(5.98N)、
    曼谷(13.75N)、河内(21.03N)、马尼拉(14.60N) 全部误判——同一个马来西亚行程里
    吉隆坡(3.14N)判对、亚庇判错，因为分界线恰好从中间穿过。后果有两个：
    ① 前端据此选高德，而高德没有当地数据 → 用户看到北京 + 服务超时（线上实测）；
    ② `gcj_to_wgs84` 对本就是 WGS-84 的海外坐标再减一次偏移 → 凭空偏 ~380m。

    矩形从根本上做不到：河内(21.03N,105.85E) 与南宁(22.8N,108.3E) 靠得太近，
    任何轴对齐矩形都无法把越南北部与云南/广西分开。故改用简化国界多边形 + 射线法。

    **误判方向的代价不对称，拿不准时要判「境外」**：
    境外→境内 = 开高德、没数据、彻底不可用（就是这个 bug）；
    境内→境外 = 开苹果地图，而苹果在中国大陆用的正是高德数据，仍然可用。
    （原实现的注释把这个方向写反了，包围盒才越取越松。）
    """
    for min_lng, max_lng, min_lat, max_lat in _CHINA_ISLANDS:
        if min_lng <= lng <= max_lng and min_lat <= lat <= max_lat:
            return False
    return not _in_polygon(lng, lat, _CHINA_MAINLAND)


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
    """地点 → `{amap, apple, google, domestic}` 导航 deep link。无坐标/坐标非法返回 None。

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
    # 谷歌也吃 WGS-84。境外 + 非苹果设备（Android/Windows）用它——那一格此前落回高德，
    # 也就是说本 bug 在半数设备上并不会因为境内外判对而消失。
    # 国内打不开谷歌是事实，但导航的真实使用场景是**人到了当地**；而且相比「高德显示北京」，
    # 「打不开」至少不是错误信息。境内一律走高德，压根不会用到这条。
    google = f"https://www.google.com/maps/dir/?api=1&destination={w_lat:.6f},{w_lng:.6f}"
    return {"amap": amap, "apple": apple, "google": google,
            "domestic": not out_of_china(lng, lat)}
