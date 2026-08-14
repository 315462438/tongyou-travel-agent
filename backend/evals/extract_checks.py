"""本体抽取的检查器（2026-08-14）——纯函数，`TripObject` 进、`Finding` 出。

沿用 `checks.py` 的两条纪律：
- **规则判定，不做 LLM 打分**：拿它当闸门时，分数波动到底是模型抖动还是真退化分不清。
- **新增检查项必须对应真实翻过的车**，不做臆想的规范检查。

这里每一项都对着下游一个具体的坏结果：
    漏天      → 海报少一张图 / 导入的行程少一天
    空停留点  → 海报那天是张白图
    合计成条目→ 预算总额翻倍（Phase 67 死守的那条）
    人数认错  → 人均金额整体翻倍或减半
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from evals.checks import Finding


@dataclass
class Sample:
    id: str
    message_id: str = ""
    sha256: str = ""
    days: list[int] = field(default_factory=list)
    must_stops: list[str] = field(default_factory=list)
    expect_headcount: int = 0
    expects_cost: bool = False
    note: str = ""


# 「合计/小计/总计」这类汇总行不是开销条目。抽进来会被服务端连同逐项一起再求和 →
# 总额翻倍。`extract._is_total_line` 就是防它的，这里做的是**结果侧**的复核：
# 上游改坏了、或换个模型又开始抽了，闸门要能立刻发现。
_TOTAL_WORDS = ("合计", "总计", "小计", "总花费", "总预算", "共计")

# 抽出来的名字里不该留 markdown 残渣——它会原样出现在海报和预算表里
_MD_RESIDUE = re.compile(r"[*_`]{1,2}|\[\[?img[:：]|!\[")


def check_days_covered(trip, s: Sample) -> list[Finding]:
    """守：分块路径（天数 > ontology_single_call_max_days）丢天。"""
    if not s.days:
        return []
    got = {d.day for d in trip.days}
    missing = [d for d in s.days if d not in got]
    out = []
    if missing:
        out.append(Finding("ext_missing_days", f"缺少 Day {missing}（抽到 {sorted(got)}）"))
    if trip.failed_days:
        out.append(Finding("ext_failed_days", f"有整块抽取失败：Day {trip.failed_days}"))
    extra = [d for d in sorted(got) if d not in s.days]
    if extra:
        # 例：Day 6 的「路线A/路线B」二选一被拆成两天
        out.append(Finding("ext_extra_days", f"多出正文里没有的 Day {extra}", level="warn"))
    return out


def check_stops_per_day(trip, s: Sample) -> list[Finding]:
    """守：某天一个地点都没抽到——海报那天就是张白图。"""
    empty = [d for d in s.days if not trip.stops_of_day(d)]
    return [Finding("ext_empty_day", f"这些天没有任何停留点：Day {empty}")] if empty else []


def check_must_stops(trip, s: Sample) -> list[Finding]:
    """守：正文里加粗写着的主地标被漏掉。子串匹配——名字带后缀（「黄鹤楼公园」）也算命中。"""
    names = " | ".join(x.name for x in trip.stops)
    missing = [w for w in s.must_stops if w and w not in names]
    return [Finding("ext_missing_landmark", f"主地标未被抽成停留点：{missing}")] if missing else []


def check_total_not_an_item(trip) -> list[Finding]:
    """守 Phase 67 不变式：「合计」行绝不能进逐项开销。

    它进来的后果是隐蔽的——服务端把逐项求和当总额，而汇总行本身就是那个和，
    总额直接翻倍，而且表面上每一行看着都对。
    """
    bad = [e.name for e in trip.expenses if any(w in e.name for w in _TOTAL_WORDS)]
    return [Finding("ext_total_as_item", f"汇总行被抽成了开销条目：{bad[:3]}")] if bad else []


def check_headcount(trip, s: Sample) -> list[Finding]:
    """守：预算表写「两人合计」「两大一小」时人数没认出来 → 人均金额整体失真。"""
    if not s.expect_headcount:
        return []
    got = int(trip.headcount or 0)
    if got != s.expect_headcount:
        return [Finding("ext_headcount",
                        f"人数认成 {got}，正文口径是 {s.expect_headcount}")]
    return []


def check_cost_present(trip, s: Sample) -> list[Finding]:
    """守：cost 路整条静默失败（`build_trip_object` 里单路失败只是留空）。"""
    if not s.expects_cost:
        return []
    out = []
    if not trip.expenses:
        out.append(Finding("ext_no_expenses", "正文有预算表却一条开销都没抽到"))
    if not any(e.amount > 0 for e in trip.expenses):
        out.append(Finding("ext_zero_amounts", "所有开销金额都是 0"))
    return out


def check_name_hygiene(trip) -> list[Finding]:
    """守：名字里带 `**` / 图片占位符残渣——它会原样显示在海报和预算表里。"""
    named = [*trip.stops, *trip.expenses, *trip.foods, *trip.lodgings]
    bad = [x.name for x in named if x.name and _MD_RESIDUE.search(x.name)]
    return [Finding("ext_markdown_residue", f"{len(bad)} 个名字带 markdown 残渣：{bad[:3]}")] \
        if bad else []


def check_lanes_registered(trip, s: Sample) -> list[Finding]:
    """守：某一路失败时**不登记进 lanes**（登记了就再也不会重试，缓存把空结果焊死）。"""
    from app.ontology.extract import LANE_COST, LANE_ITINERARY

    out = []
    if trip.days and LANE_ITINERARY not in trip.lanes:
        out.append(Finding("ext_lane_unregistered", "抽到了日程却没登记 itinerary 路"))
    if s.expects_cost and trip.expenses and LANE_COST not in trip.lanes:
        out.append(Finding("ext_lane_unregistered", "抽到了开销却没登记 cost 路"))
    if s.expects_cost and not trip.expenses and LANE_COST in trip.lanes:
        # 反向：空结果却登记了 → 缓存会把「什么都没有」当成功结果永久固化
        out.append(Finding("ext_empty_lane_registered", "cost 路是空的却登记了（会被缓存固化）"))
    return out


def run_extract_checks(trip, s: Sample) -> list[Finding]:
    findings: list[Finding] = []
    findings += check_days_covered(trip, s)
    findings += check_stops_per_day(trip, s)
    findings += check_must_stops(trip, s)
    findings += check_total_not_an_item(trip)
    findings += check_headcount(trip, s)
    findings += check_cost_present(trip, s)
    findings += check_name_hygiene(trip)
    findings += check_lanes_registered(trip, s)
    return findings
