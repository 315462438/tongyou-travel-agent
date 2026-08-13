"""高德静态地图代理（Phase 13）

前端只传点位/编号/颜色，后端构造 markers+path、签名、拉图返回，
高德 key/sig 不进前端。仅用于手账海报路线图。
"""

import hashlib
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.config import settings
from app.tools.amap import sign_params

router = APIRouter(prefix="/api", tags=["staticmap"])

AMAP_STATICMAP = "https://restapi.amap.com/v3/staticmap"
# 每天一色，标记编号在当天内从 1 开始
DAY_COLORS = ["0xFF5A5F", "0x2EC4B6", "0x3D5AFE", "0xFF9F1C", "0x9B5DE5", "0x00B894"]


def _valid_pt(pt: str) -> bool:
    parts = pt.split(",")
    if len(parts) != 2:
        return False
    try:
        lng, lat = float(parts[0]), float(parts[1])
    except ValueError:
        return False
    return 70 < lng < 140 and 3 < lat < 55  # 中国经纬度粗校验


@router.get("/staticmap")
async def staticmap(pts: str, labels: str = "", days: str = "", size: str = "750*450"):
    """pts=lng,lat;lng,lat...  labels=1,2,..（可选）  days=1,1,2,..（每点属第几天，控制颜色+连线）"""
    point_list = [p for p in pts.split(";") if p]
    if not point_list or len(point_list) > 40 or not all(_valid_pt(p) for p in point_list):
        raise HTTPException(400, "invalid pts")
    if size not in ("750*450", "750*350", "500*300", "600*400", "600*600", "560*620"):
        size = "750*450"

    label_list = labels.split(",") if labels else [str(i + 1) for i in range(len(point_list))]
    day_list = days.split(",") if days else ["1"] * len(point_list)

    # markers：按天着色、带编号
    markers_by_group: dict[str, list[str]] = {}
    for i, pt in enumerate(point_list):
        d = day_list[i] if i < len(day_list) else "1"
        lbl = (label_list[i] if i < len(label_list) else str(i + 1))[:1] or "1"
        color = DAY_COLORS[(int(d) - 1) % len(DAY_COLORS)] if d.isdigit() else DAY_COLORS[0]
        markers_by_group.setdefault(f"mid,{color},{lbl}", []).append(pt)
    markers = "|".join(f"{style}:{';'.join(pts_)}" for style, pts_ in markers_by_group.items())

    # path：同一天的点按顺序连线
    paths = []
    for d in dict.fromkeys(day_list):
        seq = [point_list[i] for i in range(len(point_list)) if (day_list[i] if i < len(day_list) else "1") == d]
        if len(seq) >= 2:
            color = DAY_COLORS[(int(d) - 1) % len(DAY_COLORS)] if d.isdigit() else DAY_COLORS[0]
            paths.append(f"4,{color},0.9,,:" + ";".join(seq))

    params = {"key": settings.amap_key, "size": size, "scale": "2", "markers": markers}
    if paths:
        params["path"] = "|".join(paths)
    params["sig"] = sign_params(params, settings.amap_secret)

    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.get(f"{AMAP_STATICMAP}?{urlencode(params)}", timeout=12)
    except Exception:  # noqa: BLE001
        raise HTTPException(502, "staticmap fetch failed")
    if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image/"):
        raise HTTPException(502, "staticmap upstream error")
    etag = hashlib.md5(pts.encode()).hexdigest()[:16]
    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "image/png"),
        headers={"Cache-Control": "public, max-age=86400", "ETag": etag},
    )
