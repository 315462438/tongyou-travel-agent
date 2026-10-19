"""DeepSeek Search / Fetch（2026-10-17 官方 JSON API）。

复用模型密钥；原始网页始终是不可信资料，由调用方 wrap_external 后交给模型。
Search / Fetch 分别限速，进程内跨事件循环共享；多进程部署需另设账号级限流。
"""

import asyncio
import logging
import threading
import time
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.tools.url_guard import UnsafeURLError, ensure_safe_url, is_safe_url

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_next_request = {"search": 0.0, "fetch": 0.0}
_RETRYABLE = {408, 429, 500, 502, 503, 504}


def enabled(kind: str = "search") -> bool:
    flag = settings.deepseek_fetch_enabled if kind == "fetch" else settings.deepseek_search_enabled
    return bool(flag and settings.deepseek_api_key)


async def _wait_for_slot(kind: str) -> None:
    # 官方每种接口各 5 QPS；留出少量余量，避免滑动窗口边界抖动。
    with _lock:
        now = time.monotonic()
        slot = max(now, _next_request[kind])
        _next_request[kind] = slot + 0.22
    if slot > now:
        await asyncio.sleep(slot - now)


async def _post(kind: str, body: dict) -> dict:
    if not enabled(kind):
        return {}
    from app import observability as obs

    url = settings.deepseek_web_base_url.rstrip("/") + "/v1/tools/" + kind
    with obs.span("deepseek_web_" + kind) as span:
        try:
            # 总截止包含排队、重试和读包；不能每次重试重新等满一整个超时。
            async with asyncio.timeout(settings.deepseek_web_timeout_s):
                async with httpx.AsyncClient(trust_env=False, timeout=settings.deepseek_web_timeout_s) as client:
                    for attempt in range(2):
                        await _wait_for_slot(kind)
                        response = await client.post(url, json=body, headers={
                            "Authorization": f"Bearer {settings.deepseek_api_key}",
                            "Content-Type": "application/json",
                        })
                        if response.status_code in _RETRYABLE and attempt == 0:
                            await asyncio.sleep(0.5)
                            continue
                        if span is not None:
                            span.update(output={"status": response.status_code})
                        if response.status_code != 200:
                            logger.warning("DeepSeek %s HTTP %s", kind, response.status_code)
                            return {}
                        data = response.json()
                        return data if isinstance(data, dict) else {}
        except (httpx.HTTPError, ValueError, TimeoutError):
            logger.warning("DeepSeek %s unavailable", kind)
    return {}


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def parse_results(data: dict) -> list[dict]:
    items = data.get("results") if isinstance(data, dict) else None
    results = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        url = _text(item.get("url"))
        try:
            parsed = urlparse(url)
            if not is_safe_url(url, resolve_dns=False)[0] or parsed.username or parsed.password:
                continue
        except ValueError:
            continue
        content = next((_text(item.get(k)) for k in ("content", "summary", "snippet")
                        if _text(item.get(k)).strip()), "")
        results.append({
            "title": _text(item.get("title"))[:120], "url": url,
            "content": content[:20_000], "published": _text(item.get("date"))[:10],
            "provider": "deepseek", "rerank_score": item.get("rerank_score"),
            "authority": item.get("authority"), "retrieved_at": time.time(),
        })
    return results


async def search(query: str, top_k: int | None = None) -> list[dict]:
    query = (query or "").strip()
    # 不截断查询，避免把末尾 site:/日期条件切坏；长查询由阿里或原浏览器处理。
    if not enabled() or not 1 <= len(query) <= 128:
        return []
    count = max(1, min(top_k or settings.web_search_api_top_k, 50))
    return parse_results(await _post("search", {"query": query, "count": count, "need_content": True}))


async def fetch(url: str) -> dict | None:
    if not enabled("fetch"):
        return None
    try:
        parsed = urlparse(url)
        if len(url) > 8192 or parsed.username or parsed.password:
            return None
        ensure_safe_url(url)
    except (UnsafeURLError, ValueError):
        return None
    data = await _post("fetch", {"url": url})
    content = _text(data.get("content"))
    if not content.strip():
        return None
    return {"title": _text(data.get("title"))[:120], "url": url,
            "content": content[:20_000], "provider": "deepseek", "retrieved_at": time.time()}
