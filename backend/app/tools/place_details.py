"""On-demand public POI enrichment. Never cache private trip text or trust name-only matches."""
import asyncio
from collections import OrderedDict
import copy
import json
import math
import re
import time
from urllib.parse import quote

import httpx
from app.api.img_api import _allowed
from app.agent.nav_links import out_of_china
from app.tools import amap
from app.tools.geocode import haversine_km

_cache: OrderedDict = OrderedDict()
_limit = asyncio.Semaphore(2)


def text(value):
    return value.strip() if isinstance(value, str) else ""


def norm(value):
    return re.sub(r"[^\w\u4e00-\u9fff]", "", text(value).lower())


def point(value):
    try:
        lng, lat = map(float, value.split(","))
        return (lng, lat) if math.isfinite(lng) and math.isfinite(lat) and -180 <= lng <= 180 and -90 <= lat <= 90 else None
    except (TypeError, ValueError, AttributeError):
        return None


def photo(url, source):
    if not isinstance(url, str) or not url.startswith(("https://", "http://")) or not _allowed(url):
        return None
    return {"url": "/api/img?u=" + quote(url, safe=""), "source": source}


def matching_poi(name, location, pois):
    anchor, wanted = point(location), norm(name)
    if not anchor or len(wanted) < 2:
        return None
    matches = []
    for p in pois:
        if not isinstance(p, dict):
            continue
        pos, candidate = point(p.get("location")), norm(p.get("name"))
        if not pos or not candidate:
            continue
        ratio = min(len(wanted), len(candidate)) / max(len(wanted), len(candidate))
        if wanted != candidate and not (ratio >= .5 and (wanted in candidate or candidate in wanted)):
            continue
        distance = haversine_km(anchor, pos)
        if distance <= 3:
            matches.append((wanted != candidate, distance, p))
    return min(matches, key=lambda x: (x[0], x[1]))[2] if matches else None


async def public_details(name, location):
    anchor = point(location)
    if not anchor or out_of_china(*anchor) or not amap.enabled():
        return {"status": "unavailable", "photos": [], "facts": []}
    key = (name, location)
    now = time.monotonic()
    async with _limit:
        if key in _cache and _cache[key][0] > now:
            _cache.move_to_end(key)
            return copy.deepcopy(_cache[key][1])
        try:
            async with asyncio.timeout(9):
                async with httpx.AsyncClient(trust_env=False) as client:
                    data = await amap._call(client, "/v3/place/around", keywords=name[:80], location=location, radius=3000, offset=10, extensions="all")
            poi = matching_poi(name, location, (data or {}).get("pois") or [])
            status = "ready" if poi else ("unavailable" if data is not None else "temporary_error")
        except Exception:
            poi, status = None, "temporary_error"
        result = {"status": status, "photos": [], "facts": []}
        if poi:
            photos = poi.get("photos") if isinstance(poi.get("photos"), list) else []
            result["photos"] = [p for item in photos if isinstance(item, dict) and (p := photo(item.get("url"), "高德地图"))][:8]
            for label, value in [("地址", poi.get("address")), ("分类", poi.get("type")), ("联系电话", poi.get("tel"))]:
                if text(value):
                    result["facts"].append({"label": label, "value": text(value), "source": "高德地图"})
            result["source_url"] = "https://uri.amap.com/marker?position=" + quote(location) + "&name=" + quote(text(poi.get("name")))
        if status == "temporary_error":
            return result
        _cache[key] = (time.monotonic() + (21600 if status == "ready" else 60), result)
        _cache.move_to_end(key)
        while len(_cache) > 256:
            _cache.popitem(last=False)
        return copy.deepcopy(result)


def guide_material(name, content, meta_json):
    """Only data from the already-authorized imported assistant message, never the whole chat."""
    wanted = norm(name)
    excerpt = ""
    if len(wanted) >= 2:
        for block in (content or "").split("\n\n"):
            if wanted in norm(block):
                excerpt = block[:900]
                break
    photos = []
    try:
        meta = json.loads(meta_json or "{}")
        for source in meta.get("sources", []) if isinstance(meta, dict) else []:
            if not isinstance(source, dict):
                continue
            for img in source.get("images", []) or []:
                if isinstance(img, dict) and len(wanted) >= 2 and norm(img.get("name")) == wanted:
                    if p := photo(img.get("url"), "原攻略配图"):
                        photos.append(p)
    except (ValueError, TypeError):
        pass
    return excerpt, photos[:8]
