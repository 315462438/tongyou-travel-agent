"""小红书 MCP 客户端（Phase 59）——xpzouying/xiaohongshu-mcp 薄封装。

服务器上 docker 跑 MCP 服务（127.0.0.1:18060，扫码登录 cookie 文件挂载持久化），
本模块经 mcp streamable HTTP 调它的 search_feeds / get_feed_detail。
当年「小红书风控封云 IP」的坑被登录态会话绕开（已实测：云 IP 搜索/详情正常）。

设计约束：
- `XHS_MCP_URL` 未配置（本地开发默认）→ `enabled()=False`，调用方全部跳过；
- 一切失败（超时/未登录/结构变化）→ 返回空，由调用方回退必应，绝不阻塞主流程；
- 笔记正文是外部不可信内容，调用方注入 prompt 前必须走 wrap_external（guide 的
  tool 消息、研究的 _stash_source 都已有该防线）。
"""

from __future__ import annotations

import asyncio
import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(settings.xhs_mcp_url)


# ---------- 纯解析（可离线测） ----------

def _parse_feeds(text: str) -> list[dict]:
    """search_feeds 返回 JSON → [{feed_id, xsec_token, title}]。

    实测结构：{"feeds": [{"id", "xsec_token", "title"(常为空), "note_card":{"display_title"}}]}；
    容错 data/feeds 两种外层、驼峰/下划线 token 字段。没有 id+token 的条目丢弃。
    """
    try:
        data = json.loads(text)
    except ValueError:
        return []
    feeds = data.get("feeds") or data.get("data") or []
    out: list[dict] = []
    for f in feeds:
        if not isinstance(f, dict):
            continue
        fid = f.get("id") or f.get("feed_id") or ""
        token = f.get("xsec_token") or f.get("xsecToken") or ""
        title = f.get("title") or (f.get("note_card") or {}).get("display_title") or ""
        if fid and token:
            out.append({"feed_id": fid, "xsec_token": token, "title": title})
    return out


def _parse_detail(text: str) -> dict | None:
    """get_feed_detail 返回 JSON → {title, desc, images}；结构不符返回 None。

    实测结构：{"data": {"note": {"title", "desc", "imageList": [
      {"urlDefault", "urlPre", "width", "height"}, ...
    ]}}}。图片字段在 MCP 返回里是驼峰；兼容旧版下划线与备用 URL。
    """
    try:
        data = json.loads(text)
    except ValueError:
        return None
    note = ((data.get("data") or {}).get("note")) or data.get("note") or {}
    if not isinstance(note, dict):
        return None
    title = (note.get("title") or "").strip()
    desc = (note.get("desc") or "").strip()
    if not desc:
        return None
    images: list[dict] = []
    seen: set[str] = set()
    raw_images = note.get("imageList") or note.get("image_list") or note.get("images") or []
    if isinstance(raw_images, list):
        for raw in raw_images:
            if not isinstance(raw, dict):
                continue
            url = raw.get("urlDefault") or raw.get("url_default") or raw.get("urlPre") or raw.get("url")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue
            # MCP 实测给 http CDN 地址；页面本身可能运行在 https，统一升级避免混合内容。
            if url.startswith("http://"):
                url = "https://" + url.removeprefix("http://")
            if url in seen:
                continue
            seen.add(url)
            images.append({
                "url": url,
                "width": raw.get("width"),
                "height": raw.get("height"),
            })
            if len(images) >= 2:  # 每篇留封面 + 一张内页，避免图组淹没攻略
                break
    return {"title": title or desc[:30], "desc": desc, "images": images}


def note_url(feed_id: str) -> str:
    return f"https://www.xiaohongshu.com/explore/{feed_id}"


# ---------- MCP 调用 ----------

# Phase 68 安全护栏：这个第三方 MCP（xpzouying/xiaohongshu-mcp）还暴露了
# publish_content / publish_with_video / post_comment_to_feed / reply_comment_in_feed /
# like_feed / favorite_feed / delete_cookies 等**写操作**，而登录态是全平台共享的
# 单个运维账号（/home/ubuntu/xhs-mcp-data/cookies.json，无 user_id 维度）。
# 一旦有代码路径把工具名交给 LLM 决定（或抓来的笔记正文带 prompt 注入），
# 就可能以运维账号身份发帖/评论。这里硬编码只读白名单，让越权在结构上不可能。
_READONLY_TOOLS = frozenset({"search_feeds", "get_feed_detail"})


class XHSToolNotAllowed(RuntimeError):
    """调用了非只读白名单内的小红书工具。"""


async def _call_tool(tool: str, args: dict) -> str:
    """单次 MCP 工具调用，返回文本内容。整体超时兜底（MCP 服务僵死不能拖垮主流程）。"""
    if tool not in _READONLY_TOOLS:
        logger.error("拒绝调用非只读小红书工具 %r（白名单：%s）", tool, sorted(_READONLY_TOOLS))
        raise XHSToolNotAllowed(f"xhs tool not allowed: {tool}")

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async def _inner() -> str:
        async with streamablehttp_client(settings.xhs_mcp_url) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool(tool, args)
                return "\n".join(
                    c.text for c in res.content if getattr(c, "type", "") == "text"
                )

    return await asyncio.wait_for(_inner(), timeout=settings.xhs_mcp_timeout_s)


async def search_notes(keyword: str) -> list[dict]:
    """搜笔记 → [{feed_id, xsec_token, title}]；未启用/失败返回 []。

    搜索是整条链路的网关（失败=这轮小红书全军覆没回退必应），冷加载偶发超时——重试一次。
    """
    if not enabled():
        return []
    from app import observability as obs

    with obs.span("xhs_search", input_data=keyword) as _s:
        for attempt in range(2):
            try:
                feeds = _parse_feeds(await _call_tool("search_feeds", {"keyword": keyword}))
                if _s is not None:
                    _s.update(output={"feeds": len(feeds)})
                return feeds
            except Exception:  # noqa: BLE001 — 超时/未登录/服务挂了都静默降级
                logger.warning("xhs search_notes failed for %r (attempt %d)", keyword,
                               attempt + 1, exc_info=attempt == 1)
    return []


async def note_detail(feed_id: str, xsec_token: str) -> dict | None:
    """取笔记详情 → {title, desc}；失败返回 None。"""
    if not enabled():
        return None
    from app import observability as obs

    with obs.span("xhs_detail", input_data=feed_id) as _s:
        try:
            det = _parse_detail(await _call_tool(
                "get_feed_detail", {"feed_id": feed_id, "xsec_token": xsec_token}
            ))
            if _s is not None:
                _s.update(output={"chars": len((det or {}).get("desc") or "")})
            return det
        except Exception:  # noqa: BLE001
            logger.warning("xhs note_detail failed for %s", feed_id, exc_info=True)
            return None


async def collect_xhs_sources(
    query: str, limit: int | None = None,
    on_note=None,
) -> list[dict]:
    """搜索 + 取前 N 篇详情，组装成 guide 流水线的 source dict 列表。

    返回 [{title, url, summary, site: "xhs", images}]；未启用/失败返回 []。
    详情串行取（MCP 后端是单浏览器会话，并发反而互相拖慢）。

    - 尝试上限 = n+2：每篇详情要开一次真实笔记页（~20s）。走查实测「太短跳过继续取下一篇」
      无上限时为凑 5 篇抓了 11 篇（≈2 分钟纯浪费，是首轮等待的最大头）。宁可少一两篇来源，
      不让用户空等；配额烧完直接收工，缺口由必应档位（_web_search_mode）自然补位。
    - on_note(i, total, title)：逐篇进度回调（i 从 1 起）。每篇 ~20s，不播的话
      「当前动作」会静止数分钟，用户以为卡死（走查 P1-2）。
    """
    if not enabled():
        return []

    # 2026-08-14 整轮总预算：搜索+全部详情合起来不超过 xhs_collect_timeout_s。
    # 单次 40s 超时 + 连续失败熔断都挡不住「半死」MCP（失败-成功交替/每篇卡在超时边缘），
    # 最坏 2×40s 搜索 + 7×40s 详情 ≈ 5 分钟纯等待；超预算整轮放弃，必应兜底。
    try:
        return await asyncio.wait_for(
            _collect_within_budget(query, limit, on_note),
            timeout=settings.xhs_collect_timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "xhs collect exceeded total budget %.0fs for %r, dropping xhs sources",
            settings.xhs_collect_timeout_s, query,
        )
        return []
    except asyncio.CancelledError:
        raise  # 用户停止：不得被吞


async def _collect_within_budget(query: str, limit: int | None, on_note) -> list[dict]:
    n = limit or settings.xhs_notes_per_turn
    feeds = await search_notes(query)
    out: list[dict] = []
    attempts = 0
    consecutive_failures = 0  # 2026-08-13 熔断：MCP 垮了（500/超时）时连续失败要快速放弃，
    # 否则每篇详情都等 40s 超时，5-7 篇 ≈ 3-5 分钟纯等待，且期间停止按钮无检查点。
    for f in feeds:
        if len(out) >= n or attempts >= n + 2:
            break
        attempts += 1
        if on_note is not None:
            try:
                on_note(attempts, min(n + 2, len(feeds)), (f.get("title") or "")[:24])
            except Exception:  # noqa: BLE001 — 进度回调绝不能影响采集
                pass
        det = await note_detail(f["feed_id"], f["xsec_token"])
        if det is None:  # MCP 故障（超时/500/未登录）
            consecutive_failures += 1
            if consecutive_failures >= 2:
                logger.warning(
                    "xhs collect circuit broken: %d consecutive failures for %r",
                    consecutive_failures, query,
                )
                break
            continue
        # 2026-08-14 名实修复：只要 MCP 有响应（含短笔记）就算健康，**重置连续计数**。
        # 旧代码漏了重置 → 实际是「累计 2 次失败」，健康 MCP 下删帖/登录墙/解析失败
        # 零星撞上 2 次就会误熔断丢料；「连续」才是 MCP 故障的强信号。
        consecutive_failures = 0
        if len(det["desc"]) < 100:  # 太短的笔记（纯图/广告位）不当来源，但不计故障
            continue
        source_title = det["title"][:40]
        images = [{
            # 受控前缀供终稿兜底分散插图；标题同时保留图片与笔记的语义关系。
            "name": f"小红书灵感·{source_title}·{i + 1}",
            "url": image["url"],
        } for i, image in enumerate(det.get("images") or [])]
        out.append({
            "title": f"小红书｜{source_title}",
            "url": note_url(f["feed_id"]),
            "summary": det["desc"][:2500],  # 笔记细节是攻略质量的原料，给足（原1500）
            "site": "xhs",
            "images": images,
        })
    return out
