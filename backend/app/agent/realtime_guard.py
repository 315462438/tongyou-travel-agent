"""Phase 51 批5：实时数据可信度守卫。

酒店/火车/航班的「实时价格/房态/时刻」在没有出发日期时无法真实查询——弱模型却容易
一本正经地编具体房价和车次。本模块负责（纯函数、可测）：
1. `realtime_kind`：判定这轮是否在问「实时价格/时刻」类需求（hotel / transport）；
2. `extract_travel_date`：从话里抽出行/入住日期（相对词 + 显式日期）；
3. `credibility_directive`：生成注入生成 prompt 的可信度纪律——
   无日期 → 标「参考价（非实时）」+ 先追问日期；有日期 → 标注查询日期 + 数据来源。

生成侧只做 prompt 注入，不伪造数据；真正联网实时抓取仍走深度推理/携程接管链路。
"""

from __future__ import annotations

import re
from datetime import date, timedelta

_HOTEL_WORDS = ("酒店", "住宿", "民宿", "宾馆", "旅馆", "客栈", "订房", "房价", "住哪", "hotel")
_TRANSPORT_WORDS = ("火车", "高铁", "动车", "机票", "航班", "飞机", "车票", "12306", "航空")

_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def realtime_kind(text: str) -> str:
    """这轮是否在问实时价格/时刻类：'transport' / 'hotel' / ''（都不是）。

    交通词优先——「查去成都的高铁并订酒店」以交通口径提示（都要日期，纪律一致）。
    """
    t = text or ""
    if any(w in t for w in _TRANSPORT_WORDS):
        return "transport"
    if any(w in t for w in _HOTEL_WORDS):
        return "hotel"
    return ""


def extract_travel_date(text: str, today: date | None = None) -> str:
    """从话里抽出行/入住日期，返回 ISO 'YYYY-MM-DD'；抽不到返回 ''。

    支持：YYYY-MM-DD、X月X日/号、MM-DD/M.D、今天/明天/后天/大后天、周末、(下)周X。
    过去的月份/日份按明年算（如今天 12 月说「1月2号」→ 明年）。
    """
    t = text or ""
    today = today or date.today()

    # 显式 ISO：2026-08-02 / 2026/8/2
    m = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", t)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            pass
    # X月X日 / X月X号
    m = re.search(r"(\d{1,2})月(\d{1,2})[日号]", t)
    if m:
        mo, d = map(int, m.groups())
        y = today.year + (1 if mo < today.month else 0)
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            pass
    # MM-DD / M.D（避免吞掉纯数字，前后不接数字）
    m = re.search(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})(?!\d)", t)
    if m:
        mo, d = map(int, m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31:
            y = today.year + (1 if mo < today.month else 0)
            try:
                return date(y, mo, d).isoformat()
            except ValueError:
                pass

    # 相对词（长词优先，避免「大后天」被「后天」截胡）
    for word, delta in (("大后天", 3), ("后天", 2), ("明天", 1), ("今天", 0)):
        if word in t:
            return (today + timedelta(days=delta)).isoformat()
    # 周末 = 最近的周六
    if "周末" in t or "週末" in t:
        return (today + timedelta(days=(5 - today.weekday()) % 7)).isoformat()
    # (下)周X / 礼拜X
    m = re.search(r"(下)?[周週礼拜]([一二三四五六日天])", t)
    if m:
        nxt = bool(m.group(1))
        ahead = (_WEEKDAYS[m.group(2)] - today.weekday()) % 7
        if nxt:
            ahead += 7
        return (today + timedelta(days=ahead)).isoformat()
    return ""


def resolve_date(*texts: str, today: date | None = None) -> str:
    """按顺序在多段文本里找第一个可解析日期（本轮 user_text 优先，其次近轮上下文）。"""
    for t in texts:
        d = extract_travel_date(t or "", today)
        if d:
            return d
    return ""


def credibility_directive(text: str, *, context: str = "", today: date | None = None) -> str:
    """据「是否实时类需求 + 是否有日期」返回注入 system prompt 的可信度纪律；不涉及则空串。"""
    kind = realtime_kind(text) or realtime_kind(context)
    if not kind:
        return ""
    d = resolve_date(text, context, today=today)
    label = "酒店房价/房态" if kind == "hotel" else "车次/航班的班次时刻与票价"
    src = "铁路(12306)/航空官方或聚合平台" if kind == "transport" else "携程/美团等预订平台"
    if d:
        return (
            f"\n\n【实时数据纪律】用户目标日期约为 {d}。涉及{label}时，必须标注"
            f"「查询日期 {d}」与数据来源（{src}）；没有可靠实时来源就给参考区间并说明是估算，"
            f"绝不编造精确到具体房态/车次的数字。"
        )
    return (
        f"\n\n【实时数据纪律】用户尚未给出行/入住日期，无法查{label}的实时数据。"
        f"因此：①先用一句话请用户补充具体日期；②所有价格一律标注「参考价（非实时）」，"
        f"绝不伪造具体房态/车次/航班时刻；③只给参考区间与选择建议，并说明给了日期即可查实时（{src}）。"
    )
