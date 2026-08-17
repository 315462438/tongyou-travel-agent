"""国内/海外地理编码路由与结果校验（Phase 62）。

国内继续走高德；海外城市走 Open-Meteo/GeoNames，POI 走 Photon/OSM。城市上下文
与地点结果都落 `travel_geocode` 持久缓存；公共服务请求严格串行限速。
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import threading
import time
from dataclasses import dataclass

import httpx
from sqlalchemy import select

from app.config import settings

logger = logging.getLogger(__name__)

_MAX_CITY_DISTANCE_KM = 120.0
_global_lock = threading.Lock()
_global_next_at = 0.0

# 高频海外城市给确定锚点：即使全球服务短时不可用，也绝不回退到国内同名结果。
_KNOWN_CITY_ANCHORS: dict[str, tuple[float, float, str]] = {
    "吉隆坡": (101.6869, 3.1390, "my"),
    "kualalumpur": (101.6869, 3.1390, "my"),
    "仙本那": (118.6111, 4.4811, "my"),
    "semporna": (118.6111, 4.4811, "my"),
    "亚庇": (116.0735, 5.9804, "my"),
    "哥打京那巴鲁": (116.0735, 5.9804, "my"),
    "kotakinabalu": (116.0735, 5.9804, "my"),
}

# Photon 公共库只索引 default/de/en/fr；中文展示名需转换为英文/当地官方检索名。
# 高频名称先走确定性表，其他名称由上层在导入/手动修复时批量请 LLM 仅做翻译。
_PLACE_SEARCH_ALIASES: dict[str, str] = {
    "吉隆坡国际机场": "Kuala Lumpur International Airport",
    "吉隆坡国际机场（KLIA）": "Kuala Lumpur International Airport",
    "吉隆坡国际机场(KLIA)": "Kuala Lumpur International Airport",
    "KLIA": "Kuala Lumpur International Airport",
    "双子塔": "Petronas Towers",
    "双子塔（KLCC）": "Petronas Towers",
    "双子塔(KLCC)": "Petronas Towers",
    "KLCC": "Petronas Towers",
    "国家石油公司双子塔": "Petronas Towers",
    "独立广场": "Merdeka Square Kuala Lumpur",
    "鬼仔巷": "Kwai Chai Hong",
    "国家清真寺": "National Mosque of Malaysia",
    "马来西亚国家清真寺": "National Mosque of Malaysia",
    "伊斯兰艺术博物馆": "Islamic Arts Museum Malaysia",
    "茨厂街": "Petaling Street",
    "阿罗街夜市": "Jalan Alor Night Market",
    "阿罗街": "Jalan Alor",
    "亚庇国际机场": "Kota Kinabalu International Airport",
    "亚庇机场": "Kota Kinabalu International Airport",
    "仙本那码头": "Semporna Jetty",
    "仙本那镇": "Semporna",
    "敦沙卡兰海洋公园": "Tun Sakaran Marine Park",
    "马布岛": "Mabul Island",
    "卡帕莱岛": "Kapalai Island",
    "汀巴汀巴岛": "Timba Timba Island",
    "汀巴汀巴": "Timba Timba Island",
    "邦邦岛": "Pom Pom Island",
    "马达京岛": "Mataking Island",
    "马达京": "Mataking Island",
    "珍珠岛": "Bohey Dulang Island",
    "军舰岛": "Sibuan Island",
    "新峰肉骨茶": "Sun Fong Bak Kut Teh",
    "丹绒亚路海滩": "Tanjung Aru Beach",
    "怡丰叻沙": "Yee Fung Laksa",
}

_KNOWN_PLACE_ANCHORS: dict[str, tuple[float, float, str]] = {
    "吉隆坡国际机场": (101.709100, 2.745600, "my"),
    "吉隆坡国际机场klia": (101.709100, 2.745600, "my"),
    "kualalumpurinternationalairport": (101.709100, 2.745600, "my"),
    "klia": (101.709100, 2.745600, "my"),
    "双子塔": (101.711600, 3.157900, "my"),
    "双子塔klcc": (101.711600, 3.157900, "my"),
    "petronastowers": (101.711600, 3.157900, "my"),
    "petronastwintowers": (101.711600, 3.157900, "my"),
    "klcc": (101.711600, 3.157900, "my"),
}


@dataclass(frozen=True)
class GeocodeContext:
    city: str
    country_code: str
    lng: float
    lat: float

    @property
    def overseas(self) -> bool:
        return bool(self.country_code and self.country_code != "cn")


def _norm(value: str) -> str:
    return "".join((value or "").lower().split()).replace("市", "")


def _norm_place(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", (value or "").lower()).replace("市", "")


def _known_context(city: str) -> GeocodeContext | None:
    if any(sep in (city or "") for sep in ("+", "＋", "/", "、", "→", "，", ",")):
        return None
    normalized = _norm(city)
    for alias, (lng, lat, country) in _KNOWN_CITY_ANCHORS.items():
        if _norm(alias) in normalized:
            return GeocodeContext(city=city.strip(), country_code=country, lng=lng, lat=lat)
    return None


def known_overseas_city(city: str) -> bool:
    """无需网络/数据库的快速保护；供高频 GET 路由避免把已知海外城市交给高德 direction。"""
    return bool(_known_context(city))


def overseas_search_name(name: str) -> str:
    raw = (name or "").strip()
    if raw in _PLACE_SEARCH_ALIASES:
        return _PLACE_SEARCH_ALIASES[raw]
    normalized = _norm_place(raw)
    for alias, search_name in _PLACE_SEARCH_ALIASES.items():
        alias_norm = _norm_place(alias)
        if alias_norm and (alias_norm in normalized or normalized in alias_norm):
            return search_name
    return raw


def known_place_location(name: str, context: GeocodeContext) -> str | None:
    normalized = _norm_place(name)
    for alias, (lng, lat, country) in _KNOWN_PLACE_ANCHORS.items():
        alias_norm = _norm_place(alias)
        if (
            country == context.country_code
            and alias_norm
            and (alias_norm in normalized or normalized in alias_norm)
            and haversine_km((lng, lat), (context.lng, context.lat)) <= _MAX_CITY_DISTANCE_KM
        ):
            return f"{lng:.6f},{lat:.6f}"
    return None


def city_center_for_name(name: str, context: GeocodeContext) -> str | None:
    """地点本身就是城市/城镇时直接用可信城市锚点，避免 Photon 返回郊外同名小地点。"""
    normalized = _norm(name).removesuffix("镇").removesuffix("县")
    candidates = {_norm(context.city).removesuffix("镇").removesuffix("县")}
    for alias, (lng, lat, country) in _KNOWN_CITY_ANCHORS.items():
        if country == context.country_code and haversine_km(
            (lng, lat), (context.lng, context.lat),
        ) < 2:
            candidates.add(_norm(alias))
    if normalized in candidates:
        return f"{context.lng:.6f},{context.lat:.6f}"
    return None


def coordinates_probably_overseas(locations: list[str]) -> bool:
    """粗边界只用于决定是否调用国内路径 API，不用于判定坐标正确性。"""
    points: list[tuple[float, float]] = []
    for location in locations:
        try:
            points.append(tuple(float(v) for v in location.split(",")))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    if not points:
        return False
    outside = sum(not (73.0 <= lng <= 135.5 and 17.0 <= lat <= 54.5) for lng, lat in points)
    return outside >= max(1, math.ceil(len(points) / 2))


def _context_key(city: str) -> str:
    return f"v2|context|{_norm(city)}"


def geocode_cache_key(provider: str, country_code: str, city: str, name: str) -> str:
    return f"v2|{provider}|{country_code or 'xx'}|{_norm(city)}|{(name or '').strip()}"[:160]


def _parse_context(city: str, raw: str) -> GeocodeContext | None:
    try:
        coords, country = raw.rsplit("|", 1)
        lng, lat = (float(v) for v in coords.split(","))
        if not country:
            return None
        return GeocodeContext(city=city.strip(), country_code=country.lower(), lng=lng, lat=lat)
    except (TypeError, ValueError):
        return None


def _context_value(ctx: GeocodeContext) -> str:
    return f"{ctx.lng:.6f},{ctx.lat:.6f}|{ctx.country_code}"


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lng1, lat1, lng2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + (
        math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


def location_near_context(location: str | None, ctx: GeocodeContext, max_km: float = 120) -> bool:
    try:
        lng, lat = (float(v) for v in (location or "").split(","))
    except (TypeError, ValueError):
        return False
    return haversine_km((lng, lat), (ctx.lng, ctx.lat)) <= max_km


def _global_request(kind: str, params: dict) -> list[dict]:
    """同步请求放到 worker thread；线程锁保证跨 event loop 也严格限速。"""
    global _global_next_at

    with _global_lock:
        now = time.monotonic()
        if now < _global_next_at:
            time.sleep(_global_next_at - now)
        _global_next_at = time.monotonic() + max(1.0, settings.global_geocoder_min_interval_s)
        try:
            if kind == "city":
                url = f"{settings.global_city_geocoder_url.rstrip('/')}/v1/search"
            else:
                url = f"{settings.global_geocoder_url.rstrip('/')}/api/"
            response = httpx.get(
                url,
                params=params,
                headers={"User-Agent": settings.global_geocoder_user_agent},
                timeout=12,
                follow_redirects=True,
                trust_env=False,
            )
            response.raise_for_status()
            data = response.json()
            if kind == "city":
                return data.get("results") or [] if isinstance(data, dict) else []
            return data.get("features") or [] if isinstance(data, dict) else []
        except Exception:  # noqa: BLE001
            logger.warning("global geocoder request failed", exc_info=True)
            return []


async def _global_search(**params) -> list[dict]:
    """把 Open-Meteo/Photon 的不同返回结构统一为轻量 row。"""
    if params.get("featuretype") == "city":
        raw = await asyncio.to_thread(_global_request, "city", {
            "name": params.get("q") or "",
            "count": params.get("limit") or 5,
            "language": "zh",
        })
        return [{
            "lon": row.get("longitude"),
            "lat": row.get("latitude"),
            "display_name": " ".join(str(row.get(k) or "") for k in ("name", "admin1", "country")),
            "address": {"country_code": str(row.get("country_code") or "").lower()},
        } for row in raw]

    country = str(params.get("countrycodes") or "").upper()
    raw = await asyncio.to_thread(_global_request, "poi", {
        "q": params.get("q") or "",
        "limit": params.get("limit") or 5,
        "lang": "en",
        "countrycode": country,
        "lat": params.get("lat"),
        "lon": params.get("lon"),
        "location_bias_scale": 0.2,
    })
    rows: list[dict] = []
    for feature in raw:
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue
        rows.append({
            "lon": coords[0], "lat": coords[1],
            "display_name": props.get("name") or "",
            "address": {"country_code": str(props.get("countrycode") or "").lower()},
        })
    return rows


def _candidate_context(city: str, rows: list[dict]) -> GeocodeContext | None:
    normalized = _norm(city)
    for row in rows:
        address = row.get("address") if isinstance(row.get("address"), dict) else {}
        country = str(address.get("country_code") or "").lower()
        display = _norm(str(row.get("display_name") or ""))
        if not country or (normalized and normalized not in display):
            continue
        try:
            return GeocodeContext(
                city=city.strip(), country_code=country,
                lng=float(row["lon"]), lat=float(row["lat"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
    # 中文译名偶尔不在 display_name；只有单一候选时仍采纳其国家与锚点。
    if len(rows) == 1:
        row = rows[0]
        address = row.get("address") if isinstance(row.get("address"), dict) else {}
        country = str(address.get("country_code") or "").lower()
        try:
            return GeocodeContext(city=city.strip(), country_code=country,
                                  lng=float(row["lon"]), lat=float(row["lat"])) if country else None
        except (KeyError, TypeError, ValueError):
            return None
    return None


async def resolve_city_context(city: str, *, force_refresh: bool = False) -> GeocodeContext | None:
    """城市 → 国家码+锚点。已知海外城市优先；国内先用高德精确行政区，失败再查全球。"""
    city = (city or "").strip()
    if not city:
        return None
    known = _known_context(city)
    if known:
        return known

    from app.db.models import TravelGeocode
    from app.db.session import get_session

    key = _context_key(city)
    if not force_refresh:
        with get_session() as db:
            row = db.get(TravelGeocode, key)
        cached = _parse_context(city, row.location) if row else None
        if cached:
            return cached

    context: GeocodeContext | None = None
    try:
        from app.tools.amap import geocode_address, region_matches

        async with httpx.AsyncClient(trust_env=False) as client:
            candidate = await geocode_address(client, city)
        if candidate and region_matches(city, candidate):
            country = str(candidate.get("country") or "")
            # 国内普通 Key 的可信精确命中统一记 cn；海外权限接口由独立域名/授权管理。
            if not country or "中国" in country or country.lower() in ("china", "cn"):
                lng, lat = (float(v) for v in candidate["location"].split(","))
                context = GeocodeContext(city=city, country_code="cn", lng=lng, lat=lat)
    except Exception:  # noqa: BLE001
        logger.warning("amap city context failed for %s", city, exc_info=True)

    if context is None:
        rows = await _global_search(q=city, featuretype="city")
        context = _candidate_context(city, rows)
    if context:
        try:
            with get_session() as db:
                db.merge(TravelGeocode(key=key, location=_context_value(context)))
                db.commit()
        except Exception:  # noqa: BLE001
            logger.warning("geocode context cache write failed", exc_info=True)
    return context


async def global_search_poi(name: str, context: GeocodeContext) -> dict | None:
    """在已知国家内搜索 POI，并拒绝距目标城市过远的同名候选。"""
    rows = await _global_search(
        # Photon 用锚点+国家约束；不要把中文 city 拼进英文 POI 查询，否则未索引的中文 token
        # 会让本可命中的结果变成空集。
        q=(name or "").strip(),
        countrycodes=context.country_code,
        lat=context.lat,
        lon=context.lng,
    )
    for row in rows:
        address = row.get("address") if isinstance(row.get("address"), dict) else {}
        if str(address.get("country_code") or "").lower() != context.country_code:
            continue
        try:
            lng, lat = float(row["lon"]), float(row["lat"])
        except (KeyError, TypeError, ValueError):
            continue
        if haversine_km((lng, lat), (context.lng, context.lat)) <= _MAX_CITY_DISTANCE_KM:
            # Photon 已按相关性排序；距离只作硬门槛，不能反过来让市中心的弱相关项胜出。
            return {
                "name": row.get("display_name") or name,
                "location": f"{lng:.6f},{lat:.6f}",
                "country_code": context.country_code,
            }
    return None


async def is_overseas_city(city: str) -> bool | None:
    context = await resolve_city_context(city)
    return context.overseas if context else None
