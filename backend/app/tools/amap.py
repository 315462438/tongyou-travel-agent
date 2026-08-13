"""高德地图 Web 服务 API（Phase 10）

httpx 直连 restapi.amap.com，毫秒级返回结构化数据（vs 浏览器爬取分钟级）：
- 地理编码：目的地 → 坐标/adcode
- 天气预报：未来 3-4 天
- POI 搜索：景点清单（名称/评分/地址/坐标）

key 开启了数字签名：参数按字典序拼 `k=v&...`（原始值，未 URL 编码）+ 私钥取
MD5，随 sig 参数发送（算法与铺探项目 amap-proxy 一致）。
未配置 AMAP_KEY/AMAP_SECRET 时整体禁用（build_amap_source 返回 None）。
"""

import asyncio
import hashlib
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE = "https://restapi.amap.com"


def sign_params(params: dict, secret: str) -> str:
    """高德数字签名：字典序拼接原始参数 + 私钥，MD5。"""
    sorted_kv = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.md5((sorted_kv + secret).encode()).hexdigest()


def enabled() -> bool:
    return bool(settings.amap_key and settings.amap_secret)


async def _call(client: httpx.AsyncClient, path: str, **params) -> dict | None:
    params["key"] = settings.amap_key
    params["sig"] = sign_params(params, settings.amap_secret)
    # QPS 限流（CUQPS_HAS_EXCEEDED_THE_LIMIT，key 与铺探共用配额）时退避重试
    for attempt in range(4):
        try:
            resp = await client.get(f"{BASE}{path}", params=params, timeout=8)
            data = resp.json()
        except Exception:  # noqa: BLE001
            logger.warning("amap %s failed", path, exc_info=True)
            return None
        if data.get("status") == "1":
            return data
        info = (data.get("info") or "").upper()
        if "CUQPS" in info and attempt < 3:  # 瞬时 QPS 超限：指数退避 + 随机抖动后重试
            # 抖动防「惊群」——多个并发请求同时超限时错开重试，别再一起打上去（chapter5）
            import random

            await asyncio.sleep(0.4 * (2 ** attempt) + random.uniform(0, 0.3))
            continue
        logger.warning("amap %s error: %s", path, data.get("info"))
        return None
    return None


async def search_poi(client: httpx.AsyncClient, keyword: str, city: str = "") -> dict | None:
    """按名称查单个 POI，返回 {name, location, photo}（首个结果）。查不到返回 None。

    海报补全用：给攻略里的餐馆/打卡点补坐标 + 实景图。
    """
    data = await _call(
        client, "/v3/place/text", keywords=keyword, city=city, offset=1, extensions="all"
    )
    pois = (data or {}).get("pois") or []
    if not pois:
        return None
    p = pois[0]
    loc = p.get("location")
    if not loc or isinstance(loc, list):
        return None
    return {
        "name": p.get("name") or keyword,
        "location": loc,
        "photo": _first_photo(p.get("photos")),
        # Phase 62：调用方必须用行政区校验，不能只拿首个坐标（海外中文名会误中国内同名点）。
        "province": p.get("pname") or "",
        "city": p.get("cityname") or "",
        "district": p.get("adname") or "",
        "address": p.get("address") if isinstance(p.get("address"), str) else "",
    }


async def search_destination_cover(client: httpx.AsyncClient, destination: str) -> str:
    """为首页热门目的地找一张真实景点封面。

    与 ``search_poi`` 不同，这里会向后查看多条 POI，避免排名第一的城市地标没有照片就让
    整张卡片空掉。失败只返回空串；首页图片属于增强项，绝不能影响主入口可用性。
    """
    dest = (destination or "").strip()[:24]
    if not dest or not enabled():
        return ""
    data = await _call(
        client,
        "/v3/place/text",
        keywords=f"{dest} 景点",
        city=dest,
        offset=8,
        extensions="all",
        sortrule="weight",
    )
    for poi in (data or {}).get("pois") or []:
        photo = _first_photo(poi.get("photos"))
        if photo:
            return photo
    return ""


async def geocode_address(client: httpx.AsyncClient, address: str) -> dict | None:
    """结构化地址解析首项，保留行政区元数据供地域校验（Phase 62）。"""
    data = await _call(client, "/v3/geocode/geo", address=(address or "").strip())
    rows = (data or {}).get("geocodes") or []
    if not rows:
        return None
    row = rows[0]
    loc = row.get("location")
    if not loc or isinstance(loc, list):
        return None
    return {
        "location": loc,
        "country": row.get("country") or "",
        "province": row.get("province") or "",
        "city": row.get("city") if isinstance(row.get("city"), str) else "",
        "district": row.get("district") if isinstance(row.get("district"), str) else "",
        "formatted_address": row.get("formatted_address") or "",
        "adcode": row.get("adcode") or "",
    }


def region_matches(query: str, candidate: dict | None) -> bool:
    """高德候选行政区是否真的包含查询城市；拒绝海外名称误中的国内同名 POI。"""
    q = (query or "").strip()
    if not q or not candidate:
        return False
    # 多城市目的地不能拿来约束一个 POI，调用方应先传逐日城市。
    if any(sep in q for sep in ("+", "＋", "/", "、", "→", "，", ",")):
        return False
    variants = {q}
    for suffix in ("市", "省", "区", "县", "自治州", "特别行政区"):
        if q.endswith(suffix) and len(q) > len(suffix) + 1:
            variants.add(q[:-len(suffix)])
    region = " ".join(str(candidate.get(k) or "") for k in (
        "country", "province", "city", "district", "formatted_address", "address",
    ))
    return any(v and v in region for v in variants)


async def build_amap_source(destination: str) -> dict | None:
    """目的地 → 高德结构化来源（天气预报 + 热门景点清单）。失败/未配置返回 None。"""
    dest = (destination or "").strip()
    if not dest or not enabled():
        return None
    async with httpx.AsyncClient(trust_env=False) as client:
        g = await geocode_address(client, dest)
        if not g or not region_matches(dest, g):
            return None
        adcode, city = g.get("adcode", ""), g.get("city") or dest

        weather = await _call(
            client, "/v3/weather/weatherInfo", city=adcode, extensions="all"
        ) if adcode else None
        pois = await _call(
            client, "/v3/place/text",
            keywords=f"{dest} 景点", city=city, offset=10, extensions="all",
        )

    lines = [f"高德地图实时数据（{dest}）："]
    casts = ((weather or {}).get("forecasts") or [{}])[0].get("casts") or []
    if casts:
        wparts = [
            f"{c.get('date', '')[5:]} {c.get('dayweather')} {c.get('nighttemp')}-{c.get('daytemp')}°C"
            for c in casts[:4]
        ]
        lines.append("未来天气预报：" + "；".join(wparts))
    poi_list = (pois or {}).get("pois") or []
    images: list[dict] = []
    if poi_list:
        lines.append("热门景点（真实 POI，含坐标可用于就近排程）：")
        for i, p in enumerate(poi_list[:10], 1):
            rating = ((p.get("biz_ext") or {}).get("rating") or "") if isinstance(p.get("biz_ext"), dict) else ""
            name = p.get("name", "")
            parts = [name]
            if rating and rating != []:
                parts.append(f"评分{rating}")
            if p.get("address") and not isinstance(p.get("address"), list):
                parts.append(str(p["address"])[:30])
            if p.get("location"):
                parts.append(f"坐标{p['location']}")
            lines.append(f"{i}. " + "｜".join(str(x) for x in parts if x))
            # 首图作为景点配图（前 6 个有图的景点）
            photo = _first_photo(p.get("photos"))
            if name and photo and len(images) < 6:
                images.append({"name": name, "url": photo})
    if len(lines) <= 1:
        return None
    return {
        "title": f"高德地图实时数据：{dest}天气与景点",
        "url": "https://lbs.amap.com/",
        "summary": "\n".join(lines),
        "site": "amap",
        "images": images,
    }


def _first_photo(photos) -> str:
    """从 POI photos 取第一张有效图 URL。"""
    for ph in photos or []:
        url = (ph or {}).get("url")
        if url and isinstance(url, str) and url.startswith("http"):
            return url
    return ""


async def weather_forecast(destination: str) -> list[dict]:
    """目的地 → 未来几天预报 casts（[{date, dayweather, daytemp, nighttemp, ...}]）。
    失败/未配置返回 []（Phase 36 行程检查中心用，拿不到就静默跳过天气项）。"""
    dest = (destination or "").strip()
    if not dest or not enabled():
        return []
    async with httpx.AsyncClient(trust_env=False) as client:
        geo = await _call(client, "/v3/geocode/geo", address=dest)
        if not geo or not geo.get("geocodes"):
            return []
        first = geo["geocodes"][0]
        if not region_matches(dest, first):
            return []
        adcode = first.get("adcode", "")
        if not adcode:
            return []
        weather = await _call(client, "/v3/weather/weatherInfo", city=adcode, extensions="all")
    return ((weather or {}).get("forecasts") or [{}])[0].get("casts") or []


async def route_time(client: httpx.AsyncClient, origin: str, dest: str, mode: str = "步行") -> dict | None:
    """两点间真实路线时间（Phase 39）：步行/骑行走对应 direction 接口，其余按驾车估。
    返回 {"minutes": int, "km": float, "mode": str}；失败返回 None（调用方回退直线估算）。"""
    path = {"步行": "/v3/direction/walking", "骑行": "/v4/direction/bicycling"}.get(mode, "/v3/direction/driving")
    data = await _call(client, path, origin=origin, destination=dest)
    if not data:
        return None
    # v3 walking/driving: route.paths[0]; v4 bicycling: data.paths[0]
    paths = ((data.get("route") or {}).get("paths")) or ((data.get("data") or {}).get("paths")) or []
    if not paths:
        return None
    p = paths[0]
    try:
        return {"minutes": max(1, round(int(p["duration"]) / 60)),
                "km": round(int(p["distance"]) / 1000, 1), "mode": mode if mode in ("步行", "骑行") else "驾车"}
    except (KeyError, ValueError, TypeError):
        return None


async def search_hotels(city: str, limit: int = 12) -> list[dict]:
    """目的地城市 → 高德酒店 POI（Phase 46 协同板酒店推荐）。快、无浏览器、无登录墙。
    返回 [{name, rating, address, location}]（无实时价格/房态，那需携程）。失败/未配置返回 []。"""
    dest = (city or "").strip()
    if not dest or not enabled():
        return []
    async with httpx.AsyncClient(trust_env=False) as client:
        city_geo = await geocode_address(client, dest)
        if not city_geo or not region_matches(dest, city_geo):
            return []
        data = await _call(
            client, "/v3/place/text",
            keywords="酒店", city=dest, types="100000",  # 100000=住宿服务大类
            offset=min(25, max(1, limit)), extensions="all", sortrule="weight",
        )
    out: list[dict] = []
    for p in (data or {}).get("pois") or []:
        loc = p.get("location")
        if not loc or isinstance(loc, list):
            continue
        biz = p.get("biz_ext") if isinstance(p.get("biz_ext"), dict) else {}
        rating = biz.get("rating") or ""
        addr = p.get("address")
        out.append({
            "name": p.get("name") or "",
            "rating": str(rating) if rating and rating != [] else "",
            "address": str(addr)[:60] if addr and not isinstance(addr, list) else "",
            "location": loc,
        })
        if len(out) >= limit:
            break
    return out


async def regeo(location: str) -> str:
    """逆地理编码（Phase 48）：'lng,lat' → 城市名。直辖市 city 为 [] 时回退 district/province。
    失败/未配置返回 ''。"""
    loc = (location or "").strip()
    if not loc or isinstance(loc, list) or not enabled():
        return ""
    async with httpx.AsyncClient(trust_env=False) as client:
        data = await _call(client, "/v3/geocode/regeo", location=loc)
    comp = ((data or {}).get("regeocode") or {}).get("addressComponent") or {}
    for key in ("city", "district", "province"):
        v = comp.get(key)
        if v and not isinstance(v, list):
            return str(v)
    return ""
