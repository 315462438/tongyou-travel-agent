"""图片代理（Phase 12）

攻略里的景点图/酒店图经此代理：同源加载（避免将来 https 混合内容）、
导出长图时不污染 canvas。仅放行图源白名单域名（防 SSRF 开放代理）。
"""

from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

router = APIRouter(prefix="/api", tags=["img"])

# 图源白名单（host 后缀匹配）：高德 + 携程 + 小红书官方 CDN
ALLOWED_HOSTS = ("autonavi.com", "amap.com", "c-ctrip.com", "tripcdn.com", "xhscdn.com")


def _allowed(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().split(":")[0]
    except Exception:  # noqa: BLE001
        return False
    return bool(host) and any(host == d or host.endswith("." + d) for d in ALLOWED_HOSTS)


@router.get("/img")
async def proxy_image(u: str):
    if not u.startswith(("http://", "https://")) or not _allowed(u):
        raise HTTPException(400, "url not allowed")
    try:
        host = urlparse(u).netloc.lower().split(":")[0]
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; TravelBrowserAgent/1.0)",
            **({"Referer": "https://www.xiaohongshu.com/"} if host.endswith(".xhscdn.com") else {}),
        }
        async with httpx.AsyncClient(trust_env=False, follow_redirects=True) as client:
            resp = await client.get(u, timeout=10, headers=headers)
    except Exception:  # noqa: BLE001
        raise HTTPException(502, "fetch failed")
    if resp.status_code != 200:
        raise HTTPException(502, "upstream error")
    # follow_redirects 之后再次校验，避免白名单 URL 通过重定向把代理带到内网或任意域名。
    if not _allowed(str(resp.url)):
        raise HTTPException(502, "redirect target not allowed")
    ctype = resp.headers.get("content-type", "image/jpeg")
    if not ctype.startswith("image/"):
        raise HTTPException(415, "not an image")
    return Response(
        content=resp.content,
        media_type=ctype,
        headers={"Cache-Control": "public, max-age=86400"},
    )
