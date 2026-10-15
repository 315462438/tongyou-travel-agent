"""联网搜索 API（2026-10-15）：阿里云 AI 搜索开放平台·联网搜索服务（ops-web-search-001）。

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

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_SPACE_RE = re.compile(r"[ \t　\xa0]+")


def enabled() -> bool:
    return bool(settings.aliyun_search_api_key and settings.aliyun_search_host)


def _clean(text: str) -> str:
    """去掉高亮 <em> 等标签和 HTML 转义，压缩空白。"""
    text = html.unescape(_TAG_RE.sub("", text or ""))
    lines = [_SPACE_RE.sub(" ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def parse_results(data: dict) -> list[dict]:
    """接口响应 → [{title, url, content, published}]；结构不符返回 []。"""
    items = ((data or {}).get("result") or {}).get("search_result") or []
    out: list[dict] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        url = it.get("link") or ""
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        content = _clean(it.get("content") or it.get("snippet") or "")
        out.append({
            "title": _clean(it.get("title") or "")[:120],
            "url": url,
            "content": content,
            "published": ((it.get("meta_info") or {}).get("publishedTime") or "")[:10],
        })
    return out


async def search(query: str, top_k: int | None = None) -> list[dict]:
    """一次联网搜索。失败/未配置返回 []。"""
    if not enabled() or not (query or "").strip():
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
        if resp.status_code != 200:
            logger.warning("web search api %s for %r: %s", resp.status_code, query,
                           str(data.get("message") or "")[:200])
            return []
        results = parse_results(data)
        if _s is not None:
            _s.update(output={"results": len(results)})
        return results
