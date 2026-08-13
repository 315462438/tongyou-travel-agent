"""本体投影（Phase 86）

对象图 → 各消费者的视图模型。**投影是纯函数、零 LLM 调用**——这正是本体化的收益：
点「手账海报」「预算明细」时不再各跑一次抽取，直接从已有对象图算出来。

刻意保持投影目标为**既有的视图模型**（`PosterData` / `BudgetData` / `TripDraft`），
这样 poster.py 的补坐标补图流水线、budget.py 的服务端汇总、行程导入的落库逻辑
全都不用改——它们只是换了个数据来源。
"""

from __future__ import annotations

from app.agent.trip_planner import (
    BudgetItem,
    DraftDayPlan,
    DraftStay,
    DraftStop,
    HotelOption,
    TripDraft,
)
from app.ontology.objects import TripObject
from app.schemas.budget_schema import BudgetData, BudgetLine, ReservationItem
from app.schemas.poster_schema import (
    PosterData,
    PosterDayMeta,
    PosterFood,
    PosterHotel,
    PosterSpecialty,
    PosterStop,
)

# 上路线图的地点类型：住宿和交通中转不算「玩的点」，不进海报路线（沿用 Phase 13 的表现）
_POSTER_STOP_TYPES = ("spot", "food", "checkin")


def to_poster_data(trip: TripObject) -> PosterData:
    """对象图 → 海报视图。之后仍走 poster.py 的高德补坐标/实景图流水线。"""
    stops = [
        PosterStop(day=s.day, order=s.order, name=s.name, type=s.type, note=s.note)
        for s in trip.stops
        if s.type in _POSTER_STOP_TYPES
    ]
    return PosterData(
        title=trip.title or (f"{trip.destination}行程" if trip.destination else "旅行手账"),
        subtitle=trip.subtitle,
        theme=trip.theme,
        destination=trip.destination,
        stops=stops,
        day_meta=[
            PosterDayMeta(day=d.day, title=d.title, subtitle=d.subtitle) for d in trip.days
        ],
        hotels=[
            PosterHotel(name=h.name, area=h.area or h.city, price=h.price_text, note=h.note)
            for h in trip.lodgings
        ],
        foods=[PosterFood(name=f.name, note=f.note) for f in trip.foods],
        specialties=[PosterSpecialty(name=s.name, note=s.note) for s in trip.specialties],
        tips=list(trip.tips),
    )


def to_budget_data(trip: TripObject) -> BudgetData:
    """对象图 → 预算视图。汇总仍由 `budget.build_budget_payload` 服务端重算。

    不变式没变：金额人均口径、总额由逐项累加得出、`stated_total` 只做对账不采信。
    """
    return BudgetData(
        currency=trip.currency,
        headcount=trip.headcount,
        items=[
            BudgetLine(
                category=e.category, name=e.name, day=e.day, amount=e.amount, note=e.note
            )
            for e in trip.expenses
        ],
        reservations=[
            ReservationItem(name=r.name, channel=r.channel, advance=r.advance, note=r.note)
            for r in trip.reservations
        ],
        notes=list(trip.notes),
        guide_stated_total=trip.stated_total,
    )


def to_trip_draft(trip: TripObject) -> TripDraft:
    """对象图 → 协同行程板导入草稿。

    住宿分流沿用 Phase 54 的区分：挂到具体某晚的是 `stays`（已定住宿），
    没挂天的是 `hotel_options`（候选，不等于已预订）。
    """
    by_cat: dict[str, float] = {}
    for e in trip.expenses:
        by_cat[e.category] = round(by_cat.get(e.category, 0.0) + e.amount, 2)

    return TripDraft(
        title=trip.title or (f"{trip.destination}行程" if trip.destination else "新行程"),
        destination=trip.destination,
        days=trip.days_count or len(trip.day_numbers()),
        stops=[
            DraftStop(
                day=s.day, name=s.name, search_name=s.search_name,
                note=s.note, transport=s.transport,
            )
            for s in trip.stops
            if s.type != "transit"
        ],
        stays=[
            DraftStay(day=h.day, city=h.city, hotel=h.name, price=h.price, source=h.source)
            for h in trip.lodgings
            if h.day > 0
        ],
        day_plans=[
            DraftDayPlan(
                day=d.day, type=d.type,
                overnight_required=d.overnight_required,
                overnight_city=d.overnight_city,
            )
            for d in trip.days
        ],
        hotel_options=[
            HotelOption(
                city=h.city, hotel=h.name, price=h.price, source=h.source, note=h.note
            )
            for h in trip.lodgings
            if h.day <= 0
        ],
        budget_items=[BudgetItem(category=c, amount=a) for c, a in by_cat.items() if a > 0],
        failed_days=list(trip.failed_days),
    )


def to_outline(trip: TripObject) -> str:
    """对象图 → 纯文本行程梗概（无 LLM）。

    给需要「这份攻略讲了什么」的地方用（记忆提炼、跨会话引用、给 agent 的行程快照），
    它们此前只能截攻略正文前 N 字——截断点通常落在第 1 天，后面全丢。
    """
    lines: list[str] = []
    if trip.title:
        lines.append(f"# {trip.title}")
    if trip.destination:
        lines.append(f"目的地：{trip.destination}　天数：{trip.days_count or '未知'}")
    for day in trip.day_numbers():
        d = next((x for x in trip.days if x.day == day), None)
        head = f"Day {day}"
        if d and d.title:
            head += f" {d.title}"
        if d and d.overnight_city:
            head += f"（宿 {d.overnight_city}）"
        names = "、".join(s.name for s in trip.stops_of_day(day))
        lines.append(f"{head}：{names}" if names else head)
    if trip.lodgings:
        lines.append("住宿：" + "、".join(h.name for h in trip.lodgings))
    if trip.expenses:
        total = round(sum(e.amount for e in trip.expenses), 2)
        lines.append(f"预算（人均逐项累加）：约 {total:g} 元")
    return "\n".join(lines)
