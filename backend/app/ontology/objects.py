"""本体对象类型与链接（Phase 86）

## Object Type

每个对象类型有：稳定 id（`oid`）、类型化属性、以及**只能经 Action 修改**的约定。
id 由内容派生（确定性哈希），因此同一份攻略重复抽取会得到同样的 id——这是实体归一
（entity resolution）的最小形态：海报里的「灵隐寺」和预算里的「灵隐寺门票」能对上，
而不是两个互不相干的字符串。

## Link

链接不靠外键隐含，而由 `TripObject.LINKS` 显式声明 + 访问器实现。
好处是「有哪些关系」可被代码枚举（做校验、做投影、给 agent 描述本体时都要用）。

## 与既有模型的关系

`TravelTripStop` 等 ORM 模型是**协同行程板**这条链路的持久化对象；本模块是**对话/攻略**
链路的对象层。两者经 `projections.to_trip_draft` 单向对接（攻略 → 行程板导入）。
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field

# 对象图结构版本。改了字段语义就 +1，`store` 据此判定缓存失效重建。
SCHEMA_VERSION = 1

# 地点类型。lodging 单列是因为它在路线图上不算「玩的点」，但在预算里是住宿。
STOP_TYPES = ("spot", "food", "checkin", "lodging", "transit")

# 开销类别复用协同行程板那套归一（trip_planner.BUDGET_CATEGORIES），保持全系统一致
EXPENSE_CATEGORIES = ("住宿", "交通", "餐饮", "门票", "大交通", "其他")


def oid(kind: str, *parts: object) -> str:
    """内容派生的稳定对象 id。

    同样的 (kind, parts) 永远得到同样的 id —— 攻略被多轮重写后重新抽取，未变化的地点
    id 不变，因此引用它的 Action（如「删掉第 2 天的灵隐寺」）不会失效。
    """
    raw = "|".join(str(p).strip().lower() for p in parts)
    return f"{kind}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"


class StopObject(BaseModel):
    """行程中的一个地点。"""

    oid: str = ""
    day: int = 1
    order: int = 0
    name: str
    # 海外地点的英文/当地官方检索名，只用于地理编码，界面仍展示 name（沿用 DraftStop 语义）
    search_name: str = ""
    type: str = "spot"
    note: str = ""
    # 「从上一地点到本地点」的交通方式，与 TravelTripStop/segment-times 语义一致
    transport: str = ""
    start_time: str = ""
    stay_min: int = 0
    ticket_price: float = 0.0

    def normalized(self) -> StopObject:
        t = self.type if self.type in STOP_TYPES else "spot"
        day = max(1, int(self.day or 1))
        name = (self.name or "").strip()
        return self.model_copy(
            update={
                "oid": oid("stop", day, name, t),
                "day": day,
                "type": t,
                "name": name,
                "note": (self.note or "").strip(),
                "order": max(0, int(self.order or 0)),
                "stay_min": max(0, int(self.stay_min or 0)),
                "ticket_price": max(0.0, float(self.ticket_price or 0)),
            }
        )


class DayObject(BaseModel):
    """一天 = 一条路线。title/subtitle 供海报做路线命名。"""

    oid: str = ""
    day: int = 1
    title: str = ""
    subtitle: str = ""
    overnight_city: str = ""
    # stay / transit / return，沿用 DraftDayPlan 语义
    type: str = "stay"
    overnight_required: bool = True

    def normalized(self) -> DayObject:
        day = max(1, int(self.day or 1))
        return self.model_copy(
            update={
                "oid": oid("day", day),
                "day": day,
                "title": (self.title or "").strip(),
                "subtitle": (self.subtitle or "").strip(),
                "overnight_city": (self.overnight_city or "").strip(),
            }
        )


class ExpenseObject(BaseModel):
    """一项开销。金额一律**人均**口径（Phase 67 不变式，汇总由服务端重算）。"""

    oid: str = ""
    category: str = "其他"
    name: str
    day: int = 0  # 0 = 整趟通用
    amount: float = 0.0
    note: str = ""

    def normalized(self) -> ExpenseObject:
        from app.agent.trip_planner import normalize_budget_category

        name = (self.name or "").strip()
        cat = normalize_budget_category(self.category)
        day = max(0, int(self.day or 0))
        return self.model_copy(
            update={
                "oid": oid("expense", day, name, cat),
                "category": cat,
                "name": name,
                "day": day,
                "amount": round(float(self.amount or 0), 2),
                "note": (self.note or "").strip(),
            }
        )


class ReservationObject(BaseModel):
    """需提前预约/抢票的项目。"""

    oid: str = ""
    name: str
    channel: str = ""
    advance: str = ""
    note: str = ""

    def normalized(self) -> ReservationObject:
        name = (self.name or "").strip()
        return self.model_copy(
            update={
                "oid": oid("resv", name),
                "name": name,
                "channel": (self.channel or "").strip(),
                "advance": (self.advance or "").strip(),
                "note": (self.note or "").strip(),
            }
        )


class LodgingObject(BaseModel):
    """住宿候选。**候选不等于已预订**（沿用 Phase 54 HotelOption 的区分）。"""

    oid: str = ""
    name: str
    city: str = ""
    area: str = ""
    price_text: str = ""  # 展示用，如「¥400/晚」
    price: float | None = None  # 数值，供预算/导入用
    day: int = 0
    source: str = ""
    note: str = ""

    def normalized(self) -> LodgingObject:
        name = (self.name or "").strip()
        return self.model_copy(
            update={
                "oid": oid("lodging", name, (self.city or "").strip()),
                "name": name,
                "city": (self.city or "").strip(),
                "area": (self.area or "").strip(),
                "price_text": (self.price_text or "").strip(),
                "day": max(0, int(self.day or 0)),
                "source": (self.source or "").strip(),
                "note": (self.note or "").strip(),
            }
        )


class FoodObject(BaseModel):
    oid: str = ""
    name: str
    note: str = ""

    def normalized(self) -> FoodObject:
        name = (self.name or "").strip()
        return self.model_copy(
            update={"oid": oid("food", name), "name": name, "note": (self.note or "").strip()}
        )


class SpecialtyObject(BaseModel):
    oid: str = ""
    name: str
    note: str = ""

    def normalized(self) -> SpecialtyObject:
        name = (self.name or "").strip()
        return self.model_copy(
            update={"oid": oid("spec", name), "name": name, "note": (self.note or "").strip()}
        )


class TripObject(BaseModel):
    """行程对象图的根。**所有下游视图都从这里投影，不再各自解析 Markdown。**"""

    oid: str = ""
    schema_version: int = SCHEMA_VERSION
    title: str = ""
    subtitle: str = ""
    theme: str = ""
    destination: str = ""
    days_count: int = 0
    headcount: int = 1
    currency: str = "CNY"
    # 攻略正文自报的合计（团组口径）。只留档做对账，**永不作为总额采信**（Phase 67 不变式）
    stated_total: float = 0.0

    days: list[DayObject] = Field(default_factory=list)
    stops: list[StopObject] = Field(default_factory=list)
    expenses: list[ExpenseObject] = Field(default_factory=list)
    reservations: list[ReservationObject] = Field(default_factory=list)
    lodgings: list[LodgingObject] = Field(default_factory=list)
    foods: list[FoodObject] = Field(default_factory=list)
    specialties: list[SpecialtyObject] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    # 抽取失败的天（部分成功时非空），供调用方提示「部分导入」并只重跑这些天
    failed_days: list[int] = Field(default_factory=list)
    # 已填充的抽取「路」（profile / cost / days）。**按需抽取的依据**：点海报只跑
    # profile+days，点预算才补 cost —— 否则第一次点击要为另外两个面板的数据买单
    # （2026-08-13 线上：合并前置让海报从 37.9s 变成 ~110s）。
    lanes: list[str] = Field(default_factory=list)

    # ---------- Link 声明 ----------
    # (link 名, 源类型, 目标类型, 基数)。显式声明让「本体里有哪些关系」可被枚举。
    LINKS: tuple[tuple[str, str, str, str], ...] = ()

    # ---------- Link 访问器 ----------

    def stops_of_day(self, day: int) -> list[StopObject]:
        """trip →(day)→ stops，按天内顺序。"""
        got = [s for s in self.stops if s.day == day]
        return sorted(got, key=lambda s: (s.order or 0, s.name))

    def expenses_of_day(self, day: int) -> list[ExpenseObject]:
        return [e for e in self.expenses if e.day == day]

    def day_of(self, stop: StopObject) -> DayObject | None:
        return next((d for d in self.days if d.day == stop.day), None)

    def lodging_of_day(self, day: int) -> LodgingObject | None:
        return next((h for h in self.lodgings if h.day == day), None)

    def day_numbers(self) -> list[int]:
        """出现过的天号（stops 与 days 的并集，升序）。"""
        return sorted({s.day for s in self.stops} | {d.day for d in self.days})

    def find_stop(self, stop_oid: str) -> StopObject | None:
        return next((s for s in self.stops if s.oid == stop_oid), None)

    # ---------- 归一 ----------

    def normalized(self) -> TripObject:
        """规范化整张图：逐对象归一 + 天内重排序 + 去重 + 派生根 id。

        去重按 oid：同名同天同类型的地点抽两次也只留一个（长攻略分块抽取时会发生）。
        """
        days = _dedup([d.normalized() for d in self.days])
        stops = _dedup([s.normalized() for s in self.stops if (s.name or "").strip()])
        # 天内按给定 order 重排并重新编号，保证 order 连续（海报直接用它做地图 label）
        renumbered: list[StopObject] = []
        for day in sorted({s.day for s in stops}):
            same = sorted(
                [s for s in stops if s.day == day], key=lambda s: (s.order or 999, s.name)
            )
            renumbered += [s.model_copy(update={"order": i}) for i, s in enumerate(same, 1)]

        expenses = _dedup(
            [e.normalized() for e in self.expenses if (e.name or "").strip() and e.amount > 0]
        )
        dest = (self.destination or "").strip()
        return self.model_copy(
            update={
                "oid": oid("trip", dest, self.title or "", len(renumbered)),
                "schema_version": SCHEMA_VERSION,
                "title": (self.title or "").strip(),
                "subtitle": (self.subtitle or "").strip(),
                "theme": (self.theme or "").strip(),
                "destination": dest,
                "days_count": max(self.days_count or 0, len(set(s.day for s in renumbered))),
                "headcount": max(1, int(self.headcount or 1)),
                "stated_total": max(0.0, round(float(self.stated_total or 0), 2)),
                "days": days,
                "stops": renumbered,
                "expenses": expenses,
                "reservations": _dedup(
                    [r.normalized() for r in self.reservations if (r.name or "").strip()]
                ),
                "lodgings": _dedup(
                    [h.normalized() for h in self.lodgings if (h.name or "").strip()]
                ),
                "foods": _dedup([f.normalized() for f in self.foods if (f.name or "").strip()]),
                "specialties": _dedup(
                    [s.normalized() for s in self.specialties if (s.name or "").strip()]
                ),
                "tips": [t.strip() for t in self.tips if (t or "").strip()],
                "notes": [n.strip() for n in self.notes if (n or "").strip()],
                "lanes": sorted(set(self.lanes)),
            }
        )

    def is_empty(self) -> bool:
        """没有任何可投影内容 —— 调用方据此回退旧路径而不是渲染空面板。"""
        return not (self.stops or self.expenses or self.lodgings or self.foods)


TripObject.LINKS = (
    ("trip_days", "Trip", "Day", "1:N"),
    ("trip_stops", "Trip", "Stop", "1:N"),
    ("day_stops", "Day", "Stop", "1:N"),
    ("trip_expenses", "Trip", "Expense", "1:N"),
    ("day_expenses", "Day", "Expense", "1:N"),
    ("day_lodging", "Day", "Lodging", "1:1"),
    ("trip_reservations", "Trip", "Reservation", "1:N"),
)


def _dedup(items: list) -> list:
    """按 oid 去重，保序保留先出现的。"""
    seen: set[str] = set()
    out = []
    for it in items:
        if it.oid in seen:
            continue
        seen.add(it.oid)
        out.append(it)
    return out
