"""统一联网搜索：阿里 ops-web-search-001 优先，DeepSeek Search 按需补搜。

为什么换掉「浏览器里搜必应」：那条路要起 Chrome、等结果页渲染、再逐个打开网页（每页 5-15s），
一轮采集 40-100s。这个接口纯 HTTP，线上实测 1.7-2.0s 返回，且每条结果自带数百字正文，
多数情况下连网页都不用打开。

结果是外部不可信内容，调用方注入 prompt 前必须照常走 wrap_external（guide 的来源注入已有该防线）。
未配置或失败一律返回 []，由调用方回退浏览器搜索。
"""

from __future__ import annotations

import html
import logging
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_SPACE_RE = re.compile(r"[ \t　\xa0]+")


def enabled() -> bool:
    from app.tools import deepseek_web

    return _aliyun_enabled() or deepseek_web.enabled()


def _aliyun_enabled() -> bool:
    return bool(settings.aliyun_search_api_key and settings.aliyun_search_host)


def _clean(text: str) -> str:
    """去掉高亮 <em> 等标签和 HTML 转义，压缩空白。"""
    text = html.unescape(_TAG_RE.sub("", text if isinstance(text, str) else ""))
    lines = [_SPACE_RE.sub(" ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def parse_results(data: dict) -> list[dict]:
    """接口响应 → [{title, url, content, published}]；结构不符返回 []。"""
    result = data.get("result") if isinstance(data, dict) else None
    items = result.get("search_result") if isinstance(result, dict) else []
    out: list[dict] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        url = it.get("link") or ""
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        content = _clean(it.get("content") or it.get("snippet") or "")
        meta = it.get("meta_info")
        published = meta.get("publishedTime") if isinstance(meta, dict) else ""
        out.append({
            "title": _clean(it.get("title") or "")[:120],
            "url": url,
            "content": content,
            "published": published[:10] if isinstance(published, str) else "",
        })
    return out


async def _aliyun_search(query: str, top_k: int | None = None) -> list[dict]:
    """一次联网搜索。失败/未配置返回 []。"""
    if not _aliyun_enabled() or not (query or "").strip():
        return []
    from app import observability as obs

    url = (f"{settings.aliyun_search_host.rstrip('/')}"
           "/v3/openapi/workspaces/default/web-search/ops-web-search-001")
    body = {"query": query.strip(), "top_k": top_k or settings.web_search_api_top_k}
    with obs.span("web_search_api", input_data=query) as _s:
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=settings.web_search_api_timeout_s) as client:
                resp = await client.post(url, json=body, headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.aliyun_search_api_key}",
                })
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("web search api failed for %r", query, exc_info=True)
            return []
        if not isinstance(data, dict):
            return []
        if resp.status_code != 200:
            logger.warning("web search api %s for %r: %s", resp.status_code, query,
                           str(data.get("message") or "")[:200])
            return []
        results = parse_results(data)
        if _s is not None:
            _s.update(output={"results": len(results)})
        return results


def _url_key(url: str) -> str:
    """仅移除常见跟踪参数与 fragment，保留会改变正文的查询参数。"""
    try:
        p = urlsplit(url)
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in {"gclid", "fbclid"}]
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", urlencode(query), ""))
    except ValueError:
        return url


def _merge(primary: list[dict], secondary: list[dict], limit: int) -> list[dict]:
    out, seen = [], set()
    # 同一 URL 保留阿里排序位置；DS 读到的正文更完整时补正文，不把两个评分直接比较。
    by_key = {}
    for provider, batch in (("aliyun", primary), ("deepseek", secondary)):
        for result in batch:
            key = _url_key(result["url"])
            if key in seen:
                old = by_key[key]
                if len(result.get("content", "")) > len(old.get("content", "")):
                    old.update(content=result["content"], content_provider=provider)
                continue
            item = dict(result)
            item.setdefault("provider", provider)
            item.setdefault("retrieved_at", time.time())
            seen.add(key)
            by_key[key] = item
            out.append(item)
    return sorted(out, key=lambda item: len(item.get("content", "").strip()) < 80)[:limit]


async def search(query: str, top_k: int | None = None) -> list[dict]:
    """阿里资料充足时不调用 DS；缺少有效结果时补搜，失败保留已有资料。"""
    from app.tools import deepseek_web

    if not (query or "").strip():
        return []
    limit = max(1, min(top_k or settings.web_search_api_top_k, 50))
    primary = await _aliyun_search(query, limit)
    unique = _merge(primary, [], limit)
    usable = sum(len(r.get("content", "").strip()) >= 80 for r in unique)
    secondary = []
    if usable < min(limit, max(1, settings.web_search_min_results)) and deepseek_web.enabled():
        secondary = await deepseek_web.search(query, limit)
    return _merge(primary, secondary, limit)
