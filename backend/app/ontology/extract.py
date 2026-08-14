"""攻略 Markdown → 本体对象图（Phase 86）

**全系统唯一**一处从攻略正文抽结构的地方。此前 poster / budget / 行程导入各抽一次：
三次 LLM 调用、三份互不一致的结果、而且都截断（`guide[:5000]` / `guide[:6000]`）——
长攻略后半段的花费和点位直接丢失，用户看到的面板总额远低于正文。

安全：攻略正文源自抓来的网页与小红书笔记（不可信），进 prompt 必须过
`wrap_external` + `EXTERNAL_POLICY`（Phase 69 ④ 已把 extract 类调用全部纳管）。
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence

from app.agent.context_security import EXTERNAL_POLICY, wrap_external
from app.config import settings
from app.ontology.objects import (
    DayObject,
    ExpenseObject,
    FoodObject,
    LodgingObject,
    ReservationObject,
    SpecialtyObject,
    StopObject,
    TripObject,
)
from app.schemas.ontology_schema import (
    TripCostExtraction,
    TripDaysExtraction,
    TripItineraryExtraction,
    TripProfileExtraction,
)

logger = logging.getLogger(__name__)

# 抽取「路」的划分原则：**一路对应一个消费者要的完整数据**，不按概念细分。
#
# 2026-08-13 用两次线上实测把这条原则钉死：
# - 三个消费者合并成一个大 schema 一次抽 → 顶破 8000 token 上限、截断重试，~120s；
# - 按概念拆成 画像/花费/逐日 三路并发 → 海报要跑其中两路，53.8s，比旧的单次 37.9s 更慢。
# 抽取调用有很高的固定开销（含 reasoning tokens），**能一次拿到的绝不拆**，
# 而不同消费者之间才拆——那样每个人只付自己那份，且付过一次就进缓存。
LANE_ITINERARY = "itinerary"  # 画像 + 逐日地点（≈ 旧 PosterData 的覆盖面）
LANE_COST = "cost"            # 逐项开销/预约/人数/口径（≈ 旧 BudgetData 的覆盖面）
ALL_LANES = (LANE_ITINERARY, LANE_COST)

# 各消费者实际需要的路
POSTER_LANES = (LANE_ITINERARY,)            # 海报不需要预算明细
BUDGET_LANES = (LANE_COST,)                 # 预算的人数也在 cost 路里，不必拉上 itinerary
IMPORT_LANES = ALL_LANES                    # 行程板导入要地点 + 预算拆分

EXTRACT_SYSTEM = (
    "你是旅行攻略结构化助手，把攻略正文整理成结构化行程数据。\n"
    "铁律：**只用正文里真实出现的信息**，不要估算、不要编造、不要脑补市场价或地点。"
    "正文没写的字段留空或填 0。\n"
    "- 地点用能在地图上搜到的规范名；同一个地点不要重复出现在多天。\n"
    "- 金额一律按**一个人**计；不要输出「合计」「总预算」这类总计项，总额由系统累加。\n"
    "- 住宿只填正文明确提到的酒店/民宿，正文只说了区域就给空数组。"
) + EXTERNAL_POLICY

# 「合计」行兜底：模型偶尔无视上面的约束，放进明细会让总额翻倍
_TOTAL_WORDS = ("合计", "总计", "总预算", "小计", "共计", "总花费", "总费用", "人均合计")

_DAY_HEADING_RE = re.compile(
    r"(?im)^(?:#{1,6}\s*)?(?:\*{0,2})?Day\s*(\d{1,2})"
    r"(?:\s*[-–—~至]\s*(?:Day\s*)?(\d{1,2}))?[^\n]*$"
)


def _is_total_line(name: str) -> bool:
    return any(w in (name or "") for w in _TOTAL_WORDS)


def split_day_sections(guide: str) -> tuple[str, dict[int, str]]:
    """把攻略按 Day 标题切成 (非逐日部分, {天号: 该天正文})。

    长攻略分块抽取时只把某几天的正文喂给模型，每块都短——比整篇截断到 6000 字准得多，
    也不会因为预算表在结尾就把它切掉。切不出 Day 标题时返回 (整篇, {})，调用方回退整篇抽。
    """
    matches = list(_DAY_HEADING_RE.finditer(guide))
    if not matches:
        return guide, {}
    head = guide[: matches[0].start()]
    sections: dict[int, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(guide)
        body = guide[m.start() : end]
        start_day = int(m.group(1))
        last_day = int(m.group(2) or start_day)
        for d in range(min(start_day, last_day), max(start_day, last_day) + 1):
            sections[d] = sections.get(d, "") + body
    tail = ""
    # 末尾的「预算/美食/住宿/贴士」章节常在最后一个 Day 之后，用 ## 一级章节切回来
    last_body = guide[matches[-1].start() :]
    tail_match = re.search(r"(?m)^##\s+(?!Day)", last_body)
    if tail_match:
        tail = last_body[tail_match.start() :]
        last_day = int(matches[-1].group(2) or matches[-1].group(1))
        if last_day in sections:
            sections[last_day] = sections[last_day][: tail_match.start()]
    return head + tail, sections


def _to_trip(profile, cost, stops, day_meta, failed_days) -> TripObject:
    """抽取结果 → 规范化对象图。归一/去重/重排序都在 TripObject.normalized 里。"""
    return TripObject(
        title=profile.title,
        subtitle=profile.subtitle,
        theme=profile.theme,
        destination=profile.destination,
        days_count=profile.days_count,
        headcount=max(profile.headcount, cost.headcount),
        stated_total=cost.stated_total,
        days=[
            DayObject(
                day=m.day, title=m.title, subtitle=m.subtitle,
                overnight_city=m.overnight_city, type=m.type,
            )
            for m in day_meta
        ],
        stops=[
            StopObject(
                day=s.day, order=s.order, name=s.name, search_name=s.search_name,
                type=s.type, note=s.note, transport=s.transport,
            )
            for s in stops
        ],
        expenses=[
            ExpenseObject(category=e.category, name=e.name, day=e.day, amount=e.amount, note=e.note)
            for e in cost.expenses
            if not _is_total_line(e.name)
        ],
        reservations=[
            ReservationObject(name=r.name, channel=r.channel, advance=r.advance, note=r.note)
            for r in cost.reservations
        ],
        lodgings=[
            LodgingObject(
                name=h.name, city=h.city, area=h.area, price_text=h.price_text,
                price=h.price or None, day=h.day, source=h.source, note=h.note,
            )
            for h in profile.lodgings
        ],
        foods=[FoodObject(name=f.name, note=f.note) for f in profile.foods],
        specialties=[SpecialtyObject(name=s.name, note=s.note) for s in profile.specialties],
        tips=list(profile.tips),
        notes=list(cost.notes),
        failed_days=sorted(failed_days),
    ).normalized()


async def build_trip_object(
    llm, guide: str, *, cid: str = "", destination_hint: str = "",
    lanes: Sequence[str] = ALL_LANES,
) -> TripObject:
    """攻略正文 → TripObject。**按需并发**抽取指定的路：画像 / 花费 / 逐日地点。

    `lanes` 决定跑哪几路：海报只要 `itinerary`，预算只要 `cost`。**按需 + 缓存**
    意味着每个面板只付自己那份，且付过一次之后所有面板都是 0 成本。

    两条 2026-08-13 的线上实测教训（都写进 pitfalls 了）：
    1. 三个消费者合并成一个大 schema 一次抽 → 顶破 `llm.parse` 的输出 token 上限
       （默认 8000，还要与 DeepSeek 的 reasoning tokens 共用），截断后重试再截断，~120s。
       **结构化抽取的硬约束是输出长度，不是输入长度。**
    2. 于是按「概念」拆成 画像/花费/逐日 三路并发 → 海报要跑其中两路，53.8s，
       反而比旧的单次 `PosterData`（37.9s）更慢。抽取调用固定开销很高，
       **能一次拿到的绝不拆；要拆就按消费者拆，不按概念拆。**

    任一路/任一块失败都不作废整份：地点块失败只记 `failed_days`，
    整路失败则该部分留空且**不登记进 `lanes`**，下次调用会重试它。
    """
    from app.agent import cancel

    text = (guide or "").strip()
    if not text:
        return TripObject().normalized()

    hint = f"（目的地：{destination_hint}）\n\n" if destination_hint else ""
    cap = settings.ontology_extract_max_chars
    rest, sections = split_day_sections(text)

    async def _parse(prompt: str, schema, *, model: str = "", max_tokens: int = 0):
        cancel.check(cid)
        # wait_cancellable 让结构化重试期间也能响应停止
        return await cancel.wait_cancellable(
            cid,
            asyncio.to_thread(
                llm.parse, prompt, schema,
                model=model or settings.model_classifier, system=EXTRACT_SYSTEM,
                max_tokens=max_tokens or settings.ontology_lane_max_tokens,
            ),
        )

    async def _cost():
        # 2026-08-13 实测：这一路在 v4-pro@8000 最快（64.3s），
        # 而 v4-flash 无论 8000（133.5s）还是 16000（107.6s）都更慢——
        # 快模型在这类「逐项拆金额」任务上会反复推演，反而拖长。
        #
        # 2026-08-14：上面那组数是在 3-5 天短攻略上量的。**cost 路不分块**（不像
        # itinerary 路天数多会拆），7 天海外攻略的逐项开销在 8000 处 JSON 中途截断
        # → 整路失败 → 预算面板全空。长行程改用更大预算，短行程维持原速。
        long_trip = len(sections) > settings.ontology_cost_long_days
        return await _parse(
            f"{hint}只抽花费与需预约项，不要输出地点清单：\n\n"
            + wrap_external(text[:cap], source="guide"),
            TripCostExtraction,
            model=settings.ontology_cost_model or settings.model_extractor,
            max_tokens=(settings.ontology_cost_long_max_tokens if long_trip
                        else settings.ontology_cost_max_tokens),
        )

    async def _itinerary():
        """画像 + 逐日地点。短行程一次抽完（最快）；天数多才拆，否则会顶破输出上限。"""
        if len(sections) <= settings.ontology_single_call_max_days:
            got = await _parse(
                hint + wrap_external(text[:cap], source="guide"), TripItineraryExtraction
            )
            return got, got.stops, got.day_meta, []

        # —— 长行程：画像一次 + 逐日分块并发（每块只喂当天段落，输出都小）——
        batch = max(1, settings.ontology_day_batch)
        day_nums = sorted(sections)
        chunks = [day_nums[i : i + batch] for i in range(0, len(day_nums), batch)]
        sem = asyncio.Semaphore(max(1, settings.ontology_chunk_concurrency))

        async def one(chunk: list[int]):
            body = "\n\n".join(sections[d] for d in chunk)[:cap]
            async with sem:  # 长行程不会一次打出十几个并发请求
                return await _parse(
                    f"{hint}以下是第 {chunk[0]}-{chunk[-1]} 天的攻略正文，只抽这几天的地点：\n\n"
                    + wrap_external(body, source="guide"),
                    TripDaysExtraction,
                )

        profile_res, *chunk_res = await asyncio.gather(
            _parse(hint + wrap_external(rest[:cap] or text[:cap], source="guide"),
                   TripProfileExtraction),
            *(one(c) for c in chunks),
            return_exceptions=True,
        )
        if isinstance(profile_res, cancel.TurnCancelled):
            raise profile_res
        if isinstance(profile_res, BaseException):
            logger.warning("ontology profile part failed (cid=%s): %s", cid, profile_res)
            profile_res = TripProfileExtraction(title="", destination=destination_hint or "")

        stops, day_meta, failed = [], [], []
        for chunk, res in zip(chunks, chunk_res):
            if isinstance(res, cancel.TurnCancelled):
                raise res
            if isinstance(res, BaseException):
                logger.warning("ontology day chunk %s failed (cid=%s): %s", chunk, cid, res)
                failed += chunk
                continue
            stops += res.stops
            day_meta += res.day_meta
        return profile_res, stops, day_meta, failed

    want = [ln for ln in ALL_LANES if ln in set(lanes)] or list(ALL_LANES)
    runners = {LANE_ITINERARY: _itinerary, LANE_COST: _cost}
    results = await asyncio.gather(*(runners[ln]() for ln in want), return_exceptions=True)
    by_lane = dict(zip(want, results))

    for r in results:
        if isinstance(r, cancel.TurnCancelled):
            raise r

    # 每一路独立降级：某一路挂了只让它对应的字段留空，不影响另一路（也不作废整份）
    itin_r = by_lane.get(LANE_ITINERARY)
    if isinstance(itin_r, BaseException):
        logger.warning("ontology itinerary failed (cid=%s): %s", cid, itin_r)
        itin_r = None
    if itin_r is None:
        profile_r = TripProfileExtraction(title="", destination=destination_hint or "")
        stops, day_meta, failed = [], [], []
    else:
        profile_r, stops, day_meta, failed = itin_r

    cost_r = by_lane.get(LANE_COST)
    if cost_r is None or isinstance(cost_r, BaseException):
        if isinstance(cost_r, BaseException):
            logger.warning("ontology cost failed (cid=%s): %s", cid, cost_r)
        cost_r = TripCostExtraction()

    trip = _to_trip(profile_r, cost_r, stops, day_meta, failed)
    # 只登记**真正跑过且没抛异常**的路：抛异常的路留空，下次调用会重试它
    done = [ln for ln in want if not isinstance(by_lane.get(ln), BaseException)]
    trip = trip.model_copy(update={"lanes": done})
    if not trip.destination and destination_hint:
        trip = trip.model_copy(update={"destination": destination_hint})
    return trip.normalized()
