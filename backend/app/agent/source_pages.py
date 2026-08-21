"""采集来源全文的落库与按需重取（Phase 103）。

## 问题

`_search_and_collect_queries` 抓完页面只留 `_excerpt(page.text)` 的 1500 字摘录，全文丢弃；
而 `collect_sources` 的复用分支（`is_revision`）复用的**就是这 1500 字**。用户第二轮追问
「第 3 家酒店的取消政策」时，信息在原页面里有、在我们手上没有——只能重爬（慢）或让模型编。

深度研究链路早就有这个能力（`research_tools._stash_source` + `read_source(id, offset)`），
opencode 则是做到了全局（`core/tool-output-store.ts` 落盘，预览里带一句
"full content saved to {path}"，还按当前 agent 有没有 task 工具给不同的取回指引）。
这里把 guide 链路缺的那一半补上。

## 边界

- **重取只发生在复用路径**。采集期仍是无关键词的 `_excerpt`（Phase 96 的结构化裁剪不动）
  ——相关性裁剪依赖调用上下文，会破坏幂等，只能用在明确知道「本轮在问什么」的地方。
- `focus_excerpt` 是纯函数：同样的 (全文, 关键词, limit) 永远给同样的结果，可离线单测。
- 不上向量检索。量级是「一个会话几十个页面」，关键词窗口够用（同 Phase 4 对记忆检索的判断）。
"""

import logging
import re

from sqlalchemy import delete, select

from app.config import settings
from app.db.models import TravelSourcePage
from app.db.session import get_session

logger = logging.getLogger(__name__)

# 关键词切分。中文没有空格，直接按「连续汉字块」取会把整句抓成一个词
# （「第3家酒店的取消政策是什么」→ 一个 token，find 永远命中不了），所以先用**虚词字符**
# 把汉字块切开，再留长度 ≥2 的片段。不上分词库：这里只是给 str.find 找锚点，不需要词性，
# 多切几刀比少切安全（切碎了顶多多几个候选，切不开就一个都用不了）。
_CJK = re.compile(r"[一-鿿]+")
_WORD = re.compile(r"[A-Za-z0-9]{2,}")
# 刻意**不含** 中/上/下/里/出/个 —— 它们在真实地名里很常见（中山路、湖里区、出海口）
_FUNCTION_CHARS = "的了是在和与也都很就还要会能可有我你他她它们这那些什么怎样吗呢吧啊请帮给对从把被让再又只更最及以为而且但因所之其或等一二三四五六七八九十"
_SPLIT_CJK = re.compile(f"[{_FUNCTION_CHARS}]+")

# 问句里满地都是的词，当关键词只会让窗口停在无意义的位置
_STOPWORDS = {
    "帮我", "一下", "可以", "什么", "怎么", "这个", "那个", "我们", "他们", "还有",
    "以及", "然后", "如果", "因为", "所以", "推荐", "介绍", "详细", "具体", "安排",
    "旅行", "旅游", "行程", "攻略", "第一", "第二", "第三",
}


def _anchors(frag: str) -> list[str]:
    """长片段再补几个短锚点。

    虚词表切不干净是必然的——动词太多，穷举是输的（「把行程改到湖里区」里 改/到 不是虚词，
    整块粘成「行程改到湖里区」，`str.find` 在页面上永远命中不了）。与其扩表，不如保证
    **短锚点一定存在**：中文短语多为中心语在后（「…的取消政策」「…改到湖里区」），
    所以取末 3/4 字；也有中心语在前的（「早餐几点开始」），所以再取首 2/3 字。
    噪声锚点（「行程改」）匹配不上页面，代价只是白占一个候选位。
    """
    if len(frag) <= 4:
        return []
    return [frag[-3:], frag[-4:], frag[:2], frag[:3]]


def keywords_of(text: str, limit: int = 8) -> list[str]:
    """从本轮用户消息里抽关键词。按长度降序——长词更具体，命中更有意义。"""
    frags = [
        frag
        for block in _CJK.findall(text or "")
        for frag in _SPLIT_CJK.split(block)
        if len(frag) >= 2
    ]
    found = frags + [a for f in frags for a in _anchors(f)] + _WORD.findall(text or "")
    seen: set[str] = set()
    out: list[str] = []
    for w in sorted(found, key=len, reverse=True):
        k = w.lower()
        if k in seen or w in _STOPWORDS:
            continue
        seen.add(k)
        out.append(w)
        if len(out) >= limit:
            break
    return out


def focus_excerpt(full_text: str, keywords: list[str], limit: int = 2400) -> str:
    """从全文里按关键词取窗口，拼成不超过 limit 的摘录。**纯函数、幂等。**

    命中处前后各取一段（`_WINDOW_BEFORE`/`_WINDOW_AFTER`），窗口相交则合并，按出现顺序
    拼接，段间用「…」标出不连续。一个关键词都没命中时返回空串——**由调用方决定退回原
    summary**，而不是在这里悄悄给个头部截断（那样调用方无从区分「找到了」和「没找到」）。
    """
    text = full_text or ""
    if not text or not keywords:
        return ""
    spans: list[tuple[int, int]] = []
    lowered = text.lower()
    for kw in keywords:
        start = 0
        k = kw.lower()
        while True:
            i = lowered.find(k, start)
            if i < 0:
                break
            spans.append((max(0, i - _WINDOW_BEFORE), min(len(text), i + len(kw) + _WINDOW_AFTER)))
            start = i + len(kw)
            if len(spans) >= _MAX_SPANS:
                break
        if len(spans) >= _MAX_SPANS:
            break
    if not spans:
        return ""
    spans.sort()
    merged: list[list[int]] = [list(spans[0])]
    for lo, hi in spans[1:]:
        if lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    parts: list[str] = []
    total = 0
    for lo, hi in merged:
        chunk = text[lo:hi].strip()
        if not chunk:
            continue
        if total + len(chunk) > limit:
            chunk = chunk[: max(0, limit - total)]
        if not chunk:
            break
        parts.append(chunk)
        total += len(chunk)
        if total >= limit:
            break
    return "\n…\n".join(parts)


_WINDOW_BEFORE = 200
_WINDOW_AFTER = 600
_MAX_SPANS = 12


def save_page(cid: str, url: str, title: str, full_text: str) -> str | None:
    """存一页全文，返回 page_id。失败只记日志——全文是增强，不能拖垮采集。"""
    if not cid or not url or not (full_text or "").strip():
        return None
    text = (full_text or "")[: settings.source_full_text_max_chars]
    try:
        with get_session() as db:
            row = db.execute(
                select(TravelSourcePage).where(
                    TravelSourcePage.conversation_id == cid, TravelSourcePage.url == url[:512]
                )
            ).scalar_one_or_none()
            if row is None:
                row = TravelSourcePage(
                    conversation_id=cid, url=url[:512], title=(title or "")[:512], full_text=text
                )
                db.add(row)
            else:
                row.full_text = text
                row.title = (title or row.title or "")[:512]
            db.flush()
            page_id = row.id
            _prune(db, cid)
            db.commit()
            return page_id
    except Exception:  # noqa: BLE001
        logger.warning("save source page failed cid=%s url=%s", cid, url[:80], exc_info=True)
        return None


def _prune(db, cid: str) -> None:
    """每会话只留最近 N 页。长会话里旧目的地的页面早已无关，留着纯占空间。"""
    ids = db.execute(
        select(TravelSourcePage.id)
        .where(TravelSourcePage.conversation_id == cid)
        .order_by(TravelSourcePage.created_at.desc())
        .offset(settings.source_page_keep)
    ).scalars().all()
    if ids:
        db.execute(delete(TravelSourcePage).where(TravelSourcePage.id.in_(ids)))


def load_texts(page_ids: list[str]) -> dict[str, str]:
    """批量取全文。取不到的键直接不出现，调用方按缺失退回原 summary。"""
    ids = [p for p in page_ids if p]
    if not ids:
        return {}
    try:
        with get_session() as db:
            rows = db.execute(
                select(TravelSourcePage).where(TravelSourcePage.id.in_(ids))
            ).scalars().all()
            return {r.id: r.full_text or "" for r in rows}
    except Exception:  # noqa: BLE001
        logger.warning("load source pages failed", exc_info=True)
        return {}


def refresh_reused_summaries(sources: list[dict], user_text: str) -> tuple[list[dict], int]:
    """复用旧来源时，按**本轮**关键词从全文重新取窗口。返回 (新 sources, 命中页数)。

    没有 page_id（存量消息抓的来源）、全文取不到、或关键词一个都没命中的，原样保留它的
    旧 summary——**降级方向永远是「和改造前一样」**，不会更差。
    """
    if not sources:
        return sources, 0
    kws = keywords_of(user_text)
    if not kws:
        return sources, 0
    texts = load_texts([s.get("page_id", "") for s in sources])
    if not texts:
        return sources, 0
    out: list[dict] = []
    hits = 0
    for s in sources:
        full = texts.get(s.get("page_id", ""), "")
        focused = focus_excerpt(full, kws, limit=settings.source_focus_max_chars) if full else ""
        if focused:
            hits += 1
            out.append({**s, "summary": focused})
        else:
            out.append(s)
    return out, hits
