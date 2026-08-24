"""协同行程的 AI 能力（Phase 35）：串路线（纯几何算法）+ AI 起草 + AI 检查。

设计要点：「不走回头路」是几何问题，交给确定性算法（高德坐标 + 天内最近邻贪心 +
跨天首尾衔接），LLM 不参与排序——弱模型排 TSP 不可靠且费 token。LLM 只做两件事：
自然语言 → 结构化行程草稿（起草）、对算法算好的里程事实做点评（检查）。
距离用 haversine 直线近似（与海报 Phase 13/18 同口径）。
"""

from __future__ import annotations

import asyncio
import logging
import math

from pydantic import BaseModel
from sqlalchemy import select

from app.config import settings

logger = logging.getLogger(__name__)

_AMAP_CONCURRENCY = 3  # 高德 POI 限流（同海报的教训，见 docs/pitfalls/高德静态图marker上限与QPS限流.md）


# ---------- 串路线：纯函数，可离线单测 ----------

def _parse_loc(location: str | None) -> tuple[float, float] | None:
    try:
        lng, lat = (location or "").split(",")
        return float(lng), float(lat)
    except ValueError:
        return None


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """haversine 直线公里数。"""
    lng1, lat1, lng2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def route_km(stops: list[dict]) -> float:
    """按当前顺序的总里程（无坐标条目跳过）。stops 需已按 (day, order_no) 排好。"""
    total = 0.0
    prev: tuple[float, float] | None = None
    for s in stops:
        loc = _parse_loc(s.get("location"))
        if loc is None:
            continue
        if prev is not None:
            total += _km(prev, loc)
        prev = loc
    return total


def order_stops(stops: list[dict]) -> list[dict]:
    """天内最近邻贪心排序 + 跨天首尾衔接（次日从前一天终点最近的点开始）。

    输入/输出均为 [{id, day, order_no, name, location?}, ...]；只重排 order_no，
    不改 day（哪天去哪些地方是人的决定，算法只管天内怎么走不绕路）。
    无坐标的条目排到该天末尾、保持相对顺序。若优化后总里程更差（贪心非最优），
    返回原序——保证「永不劣化」。
    """
    by_day: dict[int, list[dict]] = {}
    for s in stops:
        by_day.setdefault(int(s.get("day") or 1), []).append(s)

    ordered: list[dict] = []
    prev_end: tuple[float, float] | None = None
    for day in sorted(by_day):
        day_stops = sorted(by_day[day], key=lambda s: s.get("order_no") or 0)
        located = [s for s in day_stops if _parse_loc(s.get("location"))]
        unlocated = [s for s in day_stops if not _parse_loc(s.get("location"))]
        seq: list[dict] = []
        if located:
            remaining = located[:]
            if prev_end is not None:  # 跨天衔接：从前一天终点最近的点起步
                cur = min(remaining, key=lambda s: _km(prev_end, _parse_loc(s["location"])))
            else:  # 首日：尊重用户当前的第一个点
                cur = remaining[0]
            remaining.remove(cur)
            seq.append(cur)
            while remaining:
                here = _parse_loc(seq[-1]["location"])
                nxt = min(remaining, key=lambda s: _km(here, _parse_loc(s["location"])))
                remaining.remove(nxt)
                seq.append(nxt)
            prev_end = _parse_loc(seq[-1]["location"])
        ordered.extend(seq + unlocated)

    reordered = [{**s, "order_no": i} for i, s in enumerate(ordered)]
    # 永不劣化：贪心偶尔比人排的差（尤其跨天衔接约束下），差了就保持原序
    original = sorted(stops, key=lambda s: (int(s.get("day") or 1), s.get("order_no") or 0))
    if route_km(reordered) > route_km(original) + 1e-6:
        return [{**s, "order_no": i} for i, s in enumerate(original)]
    return reordered


# ---------- 高德补坐标 ----------

async def geocode_names(
    names: list[str], city: str, *, force_refresh: bool = False,
) -> dict[str, str]:
    """批量查坐标：国内走高德、海外走全球编码；所有候选均通过地域校验。

    Phase 62 使用 v2 缓存键隔离 provider/country/city，海外绝不读取 Phase 55 的
    ``城市|地点`` 旧缓存。``force_refresh`` 供已有行程坐标修复使用。
    """
    from app.db.models import TravelGeocode
    from app.db.session import get_session
    from app.tools.geocode import (
        city_center_for_name, geocode_cache_key, global_search_poi, overseas_search_name,
        known_place_location, location_near_context, resolve_city_context,
    )

    uniq = list(dict.fromkeys(n for n in names if n and n.strip()))  # 去重去空、保序
    if not uniq:
        return {}

    context = await resolve_city_context(city)
    overseas = bool(context and context.overseas)
    provider = "photon" if overseas else "amap"
    country = context.country_code if context else "unknown"

    # 1. 查缓存（一次 IN 查询）
    key_of = {n: geocode_cache_key(provider, country, city, n) for n in uniq}
    cached: dict[str, str] = {}
    if not force_refresh:
        with get_session() as db:
            rows = db.execute(
                select(TravelGeocode).where(TravelGeocode.key.in_(list(key_of.values())))
            ).scalars().all()
        cached = {r.key: r.location for r in rows}
    result = {
        n: cached[key_of[n]]
        for n in uniq
        if key_of[n] in cached
        and (not overseas or location_near_context(cached[key_of[n]], context))
    }
    misses = [n for n in uniq if n not in result]
    if not misses:
        return result

    # 2. 海外按全球服务严格串行限速；国内高德保留限流并发，但必须校验行政区。
    if overseas:
        fetched = []
        for name in misses:
            try:
                center = city_center_for_name(name, context)
                known_place = known_place_location(name, context)
                fetched.append((
                    name,
                    {"location": center or known_place} if center or known_place else await global_search_poi(
                        overseas_search_name(name), context,
                    ),
                ))
            except Exception:  # noqa: BLE001
                fetched.append((name, None))
    else:
        import httpx

        from app.tools.amap import region_matches, search_poi

        sem = asyncio.Semaphore(_AMAP_CONCURRENCY)

        async def one(client, name):
            async with sem:
                try:
                    info = await search_poi(client, name, city=city)
                    # context 未解析出来时也 fail-closed：行政区不匹配就不采纳。
                    return name, info if region_matches(city, info) else None
                except Exception:  # noqa: BLE001 — 单点失败不拖垮整批
                    return name, None

        async with httpx.AsyncClient(trust_env=False) as client:
            fetched = await asyncio.gather(*[one(client, n) for n in misses])
    new_hits = {n: info["location"] for n, info in fetched if info and info.get("location")}

    # 3. 命中写回缓存（只存有坐标的；merge 幂等，避免并发插入冲突）
    if new_hits:
        try:
            with get_session() as db:
                for n, loc in new_hits.items():
                    db.merge(TravelGeocode(key=key_of[n], location=loc))
                db.commit()
        except Exception:  # noqa: BLE001 — 缓存写失败不影响本次结果
            logger.warning("geocode cache write failed", exc_info=True)
    result.update(new_hits)
    return result


# ---------- AI 起草 ----------

class DraftStop(BaseModel):
    day: int
    name: str
    # 海外中文地点对应的英文/当地官方检索名；只用于编码，界面仍展示 name。
    search_name: str = ""
    note: str = ""
    # 表示「从上一地点到本地点」的交通方式，与 TravelTripStop/segment-times 语义一致。
    transport: str = ""
    # Phase 63：攻略导入时保留时间信息
    start_time: str = ""  # 格式 "HH:MM"
    stay_min: int | None = None  # 停留时长（分钟）
    # 是否是可定位的地点：True=景点/餐厅/酒店等（需 geocode 上地图），
    # False=起床/早餐/退房等日常活动（只留在时间线，不参与 geocode）
    is_place: bool = True


class DraftStay(BaseModel):
    """Phase 51：攻略里明确写出的某晚住宿（酒店/价格/来源），导入落住宿面板。"""

    day: int
    city: str = ""
    hotel: str = ""
    price: float | None = None  # 每晚价格（元）
    source: str = ""  # 来源（如「携程」「攻略作者推荐」）


class DraftDayPlan(BaseModel):
    """攻略导入时的逐日性质，避免用当天最后一个景点反推过夜城市。"""

    day: int
    type: str = "stay"  # stay / transit / return
    overnight_required: bool = True
    overnight_city: str = ""
    day_title: str = ""  # 攻略中的每日标题，如 "Day 1 10.1 南京 → 吉隆坡：双子塔与无边泳池"


class HotelOption(BaseModel):
    """攻略给出的酒店候选；它不是已预订住宿，单独保留供用户选择。"""

    city: str = ""
    hotel: str
    price: float | None = None
    source: str = ""
    note: str = ""


class BudgetItem(BaseModel):
    """Phase 51：预算拆分一项。category 归一到住宿/交通/餐饮/门票/大交通/其他。"""

    category: str
    amount: float


class DraftFood(BaseModel):
    """攻略导入时的美食推荐。"""

    name: str
    day: int | None = None
    meal_type: str = "待定"
    category: str = "正餐"  # 小吃/正餐/甜点
    city: str = ""
    address: str = ""
    price: float | None = None  # 人均参考价
    rating: float | None = None
    business_hours: str = ""
    recommend_food: list[str] = []
    note: str = ""


class DraftTip(BaseModel):
    """攻略导入时的避坑提示。"""

    level: str = "notice"  # important(红)/notice(橙)
    content: str


class TripImportSummary(BaseModel):
    """攻略导入的全局小对象；与逐日地点分开抽取，避免长行程 JSON 超限。"""

    title: str
    destination: str
    days: int
    hotel_options: list[HotelOption] = []
    budget_items: list[BudgetItem] = []
    foods: list[DraftFood] = []
    tips: list[DraftTip] = []


class TripImportDays(BaseModel):
    """攻略导入的逐日分块，只承载少量天数的地点和住宿。"""

    stops: list[DraftStop] = []
    stays: list[DraftStay] = []
    day_plans: list[DraftDayPlan] = []


# 计划预算的规范类别（导入时把模型给的类别归一到这几类，未知归「其他」）
BUDGET_CATEGORIES = ["住宿", "交通", "餐饮", "门票", "大交通", "其他"]


def normalize_budget_category(raw: str) -> str:
    """把模型/攻略里的预算类别归一到 BUDGET_CATEGORIES 之一。"""
    s = (raw or "").strip()
    if s in BUDGET_CATEGORIES:
        return s
    # 常见同义词归并（大交通=城际机票/火车；交通=市内通勤）
    if any(k in s for k in ("机票", "飞机", "高铁", "火车", "城际", "大交通", "往返")):
        return "大交通"
    if any(k in s for k in ("交通", "地铁", "公交", "打车", "包车", "租车", "通勤")):
        return "交通"
    if any(k in s for k in ("住", "酒店", "民宿", "住宿")):
        return "住宿"
    if any(k in s for k in ("餐", "吃", "美食", "饮食")):
        return "餐饮"
    if any(k in s for k in ("门票", "景点", "游玩", "娱乐", "演出")):
        return "门票"
    return "其他"


class TripDraft(BaseModel):
    title: str
    destination: str
    days: int
    stops: list[DraftStop]
    # Phase 51 选填：seed 起草链路不填，仅攻略导入抽取时用
    stays: list[DraftStay] = []
    day_plans: list[DraftDayPlan] = []
    hotel_options: list[HotelOption] = []
    budget_items: list[BudgetItem] = []
    # 攻略导入时提取的美食推荐和避坑贴士（落对应面板）
    foods: list[DraftFood] = []
    tips: list[DraftTip] = []
    # 2026-07-31：逐天抽取时失败的天。非空 = 部分成功，调用方据此写「部分导入」状态并
    # 提供只重跑这些天的入口（此前一天失败会连同已成功的天一起作废）。
    failed_days: list[int] = []


SEED_SYSTEM = (
    "你是旅行路线规划师。根据用户需求起草一份行程草稿：\n"
    "- days 为天数；每天安排 3-6 个真实存在的地点（景点/街区/标志性餐饮），"
    "地点 name 用用户阅读的规范名称（如「开封府景区」而非「开封府附近」）；"
    "海外地点必须另填英文或当地官方 search_name（如双子塔→Petronas Towers）；\n"
    "- note 一句话说明看点或建议时段；同一天的地点尽量在相近区域；\n"
    "- 多城市/海外行程必须填写 day_plans，每天写准确 overnight_city，便于按城市定位地点；\n"
    "- 不编造不存在的地点。"
)


async def seed_draft(llm, prompt: str) -> TripDraft:
    """自然语言 → 结构化行程草稿（LLM 只出地点清单，排序交给 order_stops）。"""
    return await asyncio.to_thread(
        llm.parse, f"用户需求：{prompt}", TripDraft, system=SEED_SYSTEM,
    )


# ---------- AI 检查 ----------

REVIEW_SYSTEM = (
    "你是行程审校员。基于给出的**算法计算事实**（各天里程、优化空间）和条目清单，"
    "给多人协作中的行程提出简洁建议，Markdown 输出，只写有价值的点：\n"
    "1. 路线顺序：若「可优化里程」显著（>2km 或 >20%），点名建议调整哪几个点（或直接建议点『一键串路线』）\n"
    "2. 节奏：某天条目过多/过少、类型扎堆（连着三个博物馆）\n"
    "3. 缺口：没安排吃饭/住宿参考、无坐标的条目提醒核实名称\n"
    "4. 备注润色：对空备注的关键地点给一句可直接采用的看点提示\n"
    "总长 300 字内，友好直接，不要空话。"
)


def build_review_facts(stops: list[dict]) -> str:
    """把算法事实拼成给 LLM 的输入（LLM 不算几何，只点评）。"""
    lines = []
    by_day: dict[int, list[dict]] = {}
    for s in sorted(stops, key=lambda s: (int(s.get("day") or 1), s.get("order_no") or 0)):
        by_day.setdefault(int(s.get("day") or 1), []).append(s)
    optimized = order_stops(stops)
    for day in sorted(by_day):
        cur = [s for s in sorted(by_day[day], key=lambda x: x.get("order_no") or 0)]
        opt = [s for s in optimized if int(s.get("day") or 1) == day]
        cur_km, opt_km = route_km(cur), route_km(opt)
        names = " → ".join(s["name"] for s in cur)
        no_loc = [s["name"] for s in cur if not _parse_loc(s.get("location"))]
        lines.append(f"Day{day}：{names}｜当前约 {cur_km:.1f}km，最优排列约 {opt_km:.1f}km"
                     + (f"｜无坐标：{('、'.join(no_loc))}" if no_loc else ""))
        for s in cur:
            if not (s.get("note") or "").strip():
                lines.append(f"  - 「{s['name']}」备注为空")
    return "\n".join(lines) or "（行程为空）"


async def review_trip(llm, title: str, destination: str, stops: list[dict]) -> str:
    facts = build_review_facts(stops)
    text = await asyncio.to_thread(
        llm.generate,
        f"行程「{title}」（目的地：{destination or '未填'}）\n\n算法计算事实：\n{facts}",
        system=REVIEW_SYSTEM, model=settings.model_planner, max_tokens=1000,
    )
    return text


# ---------- 检查中心（Phase 36）：纯算法 issues，即时计算不花 LLM ----------

_WALK_WARN_KM = 8.0  # 一天步行超过此里程给告警
_OPT_SAVE_MIN_KM = 2.0  # 串路线可节省超过此值（或 20%）提示优化
_RAIN_WORDS = ("雨", "雪", "冰雹")
_ROAD_FACTOR = 1.4  # 直线→道路里程经验系数（检查中心零成本估算；精确值看 segment-times 实拉高德）
_INTERCITY_KM = 60.0  # 一天首末点直线超过此值 → 视为城际转移日（transit）


def _day_legs(cur: list[dict]) -> list[tuple[str, str, float]]:
    """按当前顺序算相邻带坐标条目的道路估算里程（直线×_ROAD_FACTOR）。
    返回 [(from_name, to_name, road_km), ...]，供检查中心告警「附计算依据」。"""
    legs: list[tuple[str, str, float]] = []
    prev: dict | None = None
    for s in cur:
        if _parse_loc(s.get("location")) is None:
            continue
        if prev is not None:
            km = _km(_parse_loc(prev["location"]), _parse_loc(s["location"])) * _ROAD_FACTOR
            legs.append((prev.get("name") or "?", s.get("name") or "?", round(km, 1)))
        prev = s
    return legs


_MOTOR_WORDS = (
    "驾车", "打车", "出租", "网约车", "公交", "地铁", "包车", "拼车", "大巴",
    "火车", "飞机", "船", "快艇", "轮渡", "城际交通",
)


def infer_leg_transport(a: dict, b: dict) -> str:
    """统一逐腿交通口径：目标条目的 transport 优先，否则按直线距离启发。

    `transport` 的语义一直是「从上一地点到当前地点」。检查中心和 segment-times 必须共同
    使用该函数，否则会出现地图显示驾车、检查中心却把同一段算成步行。
    """
    raw = (b.get("transport") or "").strip()
    pa, pb = _parse_loc(a.get("location")), _parse_loc(b.get("location"))
    distance = _km(pa, pb) if pa is not None and pb is not None else None
    names = f"{a.get('name') or ''} {b.get('name') or ''}"
    # 攻略常漏写中间的航班/接驳：跨国/跨海超长腿不能照抄“拼车/步行”。
    if distance is not None and distance > 300:
        return "飞机" if "机场" in names else "城际交通"
    if raw:
        if "步行" in raw and distance is not None and distance > 15:
            return "打车" if "机场" in names else "驾车"
        if any(k in raw for k in _MOTOR_WORDS):
            return raw
        if "骑行" in raw:
            return "骑行"
        if "步行" in raw:
            return "步行"
    if pa is None or pb is None:
        return raw or "步行"
    return "驾车" if _km(pa, pb) > 3 else "步行"


def estimate_leg_time(a: dict, b: dict, mode: str) -> dict | None:
    """海外/无高德路径能力时的透明估算；结果必须由调用方标记 estimated。"""
    pa, pb = _parse_loc(a.get("location")), _parse_loc(b.get("location"))
    if pa is None or pb is None:
        return None
    straight = _km(pa, pb)
    if "飞机" in mode:
        km, speed, overhead = straight, 650, 120
    elif "火车" in mode:
        km, speed, overhead = straight * 1.15, 120, 30
    elif any(k in mode for k in ("船", "快艇", "轮渡")):
        km, speed, overhead = straight * 1.1, 32, 15
    elif "城际交通" in mode:
        km, speed, overhead = straight * 1.2, 80, 30
    elif "步行" in mode:
        km, speed, overhead = straight * 1.25, 4.5, 0
    elif "骑行" in mode:
        km, speed, overhead = straight * 1.25, 15, 0
    elif any(k in mode for k in ("公交", "地铁")):
        km, speed, overhead = straight * _ROAD_FACTOR, 22, 10
    else:
        km, speed, overhead = straight * _ROAD_FACTOR, 35, 5
    return {
        "minutes": max(1, round(km / speed * 60 + overhead)),
        "km": round(km, 1),
        "mode": mode,
        "estimated": True,
        "note": "海外路段按直线距离与交通方式估算",
    }


def _day_leg_details(cur: list[dict]) -> list[dict]:
    """逐腿道路估算 + 交通方式，供检查中心生成与地图一致的解释。"""
    located = [s for s in cur if _parse_loc(s.get("location")) is not None]
    details: list[dict] = []
    for a, b in zip(located, located[1:]):
        km = _km(_parse_loc(a["location"]), _parse_loc(b["location"])) * _ROAD_FACTOR
        mode = infer_leg_transport(a, b)
        details.append({"from": a.get("name") or "?", "to": b.get("name") or "?",
                        "km": round(km, 1), "mode": mode})
    return details


def classify_days(stops: list[dict], total_days: int) -> dict[int, dict]:
    """给每天定性（Phase 51 批4）：type=stay/transit/return + overnight_required + span_km。

    - return：最后一天（当晚返程，不过夜）→ overnight_required=False；
    - transit：首末带坐标点直线 ≥ _INTERCITY_KM（城际赶路日，如川藏线开车转移）；
    - stay：普通游玩日。
    仅几何 + 是否末日，零成本、可测；供「每晚住哪」跳过返程日、检查中心避免误报步行。
    """
    max_day = max([int(s.get("day") or 1) for s in stops], default=1)
    n = max(1, total_days, max_day)
    by_day: dict[int, list[dict]] = {}
    for s in sorted(stops, key=lambda s: (int(s.get("day") or 1), s.get("order_no") or 0)):
        by_day.setdefault(int(s.get("day") or 1), []).append(s)
    out: dict[int, dict] = {}
    for day in range(1, n + 1):
        located = [s for s in by_day.get(day, []) if _parse_loc(s.get("location"))]
        span = 0.0
        if len(located) >= 2:
            span = _km(_parse_loc(located[0]["location"]), _parse_loc(located[-1]["location"]))
        is_last = day == n
        dtype = "return" if is_last else ("transit" if span >= _INTERCITY_KM else "stay")
        out[day] = {"type": dtype, "span_km": round(span, 1),
                    "overnight_required": not is_last}
    return out


def resolve_day_classes(
    stops: list[dict], total_days: int, day_plans: list[dict] | None = None
) -> dict[int, dict]:
    """几何 classify_days 为基线，攻略导入的 LLM day_plans（若有）覆盖 type/overnight/城市。

    检查中心（build_issues）与「每晚住哪」（day-cities）共用本函数，保证两处对
    「哪天是转移/返程、当晚是否过夜、过夜城市」判定完全一致（Phase 54.1 统一）。
    day_plans 项形如 {day, type, overnight_required, overnight_city}。
    """
    base = classify_days(stops, total_days)
    for p in day_plans or []:
        try:
            day = int(p.get("day"))
        except (TypeError, ValueError):
            continue
        if day not in base:
            continue
        ptype = p.get("type")
        if ptype in ("stay", "transit", "return"):
            base[day]["type"] = ptype
        if isinstance(p.get("overnight_required"), bool):
            base[day]["overnight_required"] = p["overnight_required"]
        city = (p.get("overnight_city") or "").strip()
        if city:
            base[day]["overnight_city"] = city
    return base


def _parse_hhmm(t: str | None) -> int | None:
    try:
        h, m = (t or "").split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def is_lodging_stop(stop: dict) -> bool:
    """住宿沿用 stop 存储，但价格不是景点门票，预算/检查必须排除。"""
    return (stop.get("name") or "").startswith("🏨") or "住宿" in (stop.get("note") or "")


def build_issues(
    stops: list[dict], *, budget: float | None = None,
    start_date: str | None = None, forecast: list[dict] | None = None,
    total_days: int | None = None, day_plans: list[dict] | None = None,
) -> list[dict]:
    """结构化检查 issues：[{level: warn|info, kind, day?, stop_id?, text, detail?}]。

    只做确定性检查（几何/时间/预算/天气事实），LLM 点评另走 ai/review——
    检查中心要的是「即时、可点击定位、零成本」，与 IDE 问题面板同定位。
    Phase 51 批4：里程按 day_type 分类判定（城际转移/返程日不误报步行），
    步行/转移告警「附计算依据」（逐腿道路估算），detail 字段给出计算过程。
    """
    issues: list[dict] = []
    by_day: dict[int, list[dict]] = {}
    for s in sorted(stops, key=lambda s: (int(s.get("day") or 1), s.get("order_no") or 0)):
        by_day.setdefault(int(s.get("day") or 1), []).append(s)
    optimized = order_stops(stops)
    # Phase 54.1：与「每晚住哪」共用合并后的日分类（LLM 计划优先、几何兜底），避免两处判定打架
    day_types = resolve_day_classes(stops, total_days or max(by_day, default=1), day_plans)

    for day in sorted(by_day):
        cur = by_day[day]
        cur_km = route_km(cur)
        opt_km = route_km([s for s in optimized if int(s.get("day") or 1) == day])
        dtype = day_types.get(day, {}).get("type", "stay")
        span = day_types.get(day, {}).get("span_km", 0)
        located = [s for s in cur if _parse_loc(s.get("location"))]
        # 「真城际转移日」判定：几何首末跨度够大（≥60km），或 LLM 标了转移但当天坐标不足以度量
        # （<2 个有坐标点，如过夜火车整天在途）。几何能度量时**以几何为准**——避免把市内/短途日
        # （导入时 LLM 常过度标 transit）误报成城际转移。
        is_transit = span >= _INTERCITY_KM or (dtype == "transit" and len(located) < 2)
        is_return = dtype == "return"
        leg_details = _day_leg_details(cur)
        road_km = round(sum(leg["km"] for leg in leg_details), 1)
        walking_km = round(sum(leg["km"] for leg in leg_details if leg["mode"] == "步行"), 1)
        far_legs = [leg for leg in leg_details if leg["km"] >= 250]
        coordinates_suspect = (
            len(far_legs) >= 2
            or any(
                leg["km"] >= 800 and leg["mode"] in ("步行", "骑行")
                for leg in leg_details
            )
        )
        leg_detail = (
            "计算依据：" + "、".join(
                f"{leg['from']}→{leg['to']} {leg['mode']} {leg['km']}km" for leg in leg_details
            ) + "（里程为直线×1.4估算）"
        ) if leg_details else ""
        if coordinates_suspect:
            suspicious = "、".join(
                f"{leg['from']}→{leg['to']} {leg['km']}km" for leg in far_legs[:4]
            )
            issues.append({
                "level": "warn", "kind": "geocode", "day": day,
                "action": "repair_geocode",
                "text": f"Day{day} 出现多段异常跨城跳点，地点可能被定位到错误国家或城市",
                "detail": f"{suspicious}。点击此项可重新定位全部地点。",
            })
        # 步行过长——转移日/返程日大里程属预期，不误报；其余日才判
        if not coordinates_suspect and not is_transit and not is_return and walking_km > _WALK_WARN_KM:
            issues.append({"level": "warn", "kind": "walk", "day": day,
                           "text": f"Day{day} 步行约 {walking_km:.1f}km（道路估算）偏多，考虑中途打车或删减点位",
                           "detail": leg_detail})
        elif not coordinates_suspect and is_transit:
            # 只有几何跨度够大才报「首末约 Nkm」；措辞信息化、不劝退（川藏线转移日本就沿途看景）
            span_txt = f"（首末约 {span:.0f}km）" if span >= _INTERCITY_KM else ""
            issues.append({"level": "info", "kind": "transit", "day": day,
                           "text": f"Day{day} 含长途城际转移{span_txt}，确认交通方式与总耗时是否留足"
                                   "（沿途景点会拉长在途时间）",
                           "detail": leg_detail})
        # 可优化
        save = cur_km - opt_km
        if not coordinates_suspect and save > max(_OPT_SAVE_MIN_KM, cur_km * 0.2):
            issues.append({"level": "info", "kind": "order", "day": day,
                           "text": f"Day{day} 顺序有优化空间（约省 {save:.1f}km），点「一键串路线」"})
        # 时间冲突
        timed = [s for s in cur if _parse_hhmm(s.get("start_time")) is not None]
        for a, b in zip(timed, timed[1:]):
            end_a = _parse_hhmm(a["start_time"]) + int(a.get("stay_min") or 0)
            if end_a > _parse_hhmm(b["start_time"]):
                issues.append({"level": "warn", "kind": "time", "day": day, "stop_id": b.get("id"),
                               "text": f"Day{day}「{a['name']}」结束时间晚于「{b['name']}」开始时间，安排冲突"})
        # 无坐标
        for s in cur:
            if not _parse_loc(s.get("location")):
                issues.append({"level": "info", "kind": "noloc", "day": day, "stop_id": s.get("id"),
                               "text": f"「{s['name']}」没查到坐标，请核实名称（串路线时会跳过它）"})

    # 预算
    total_ticket = sum(float(s.get("ticket_price") or 0) for s in stops if not is_lodging_stop(s))
    if budget and total_ticket > budget:
        issues.append({"level": "warn", "kind": "budget",
                       "text": f"门票合计 ¥{total_ticket:.0f} 已超预算 ¥{budget:.0f}"})

    # 天气（有出发日期 + 预报数据才查）
    if start_date and forecast:
        from datetime import date, timedelta

        try:
            d0 = date.fromisoformat(start_date)
        except ValueError:
            d0 = None
        if d0:
            cast_by_date = {c.get("date"): c for c in forecast}
            for day in sorted(by_day):
                cast = cast_by_date.get(str(d0 + timedelta(days=day - 1)))
                weather = (cast or {}).get("dayweather") or ""
                if any(w in weather for w in _RAIN_WORDS):
                    issues.append({"level": "warn", "kind": "weather", "day": day,
                                   "text": f"Day{day}（{cast['date']}）预报{weather}，考虑调整为室内行程或备雨具"})
    return issues


# ---------- Copilot（Phase 37）：结构化提案，AI 永不直接改 ----------

class ChangeOp(BaseModel):
    op: str  # add / update / delete
    stop_id: str = ""  # update/delete 必填（用行程 JSON 里给出的 id）
    day: int = 0
    name: str = ""
    note: str = ""
    start_time: str = ""
    stay_min: int = 0
    transport: str = ""
    ticket_price: float = 0
    reason: str = ""  # AI Explain：为什么这么改


class CopilotResult(BaseModel):
    reply: str
    changes: list[ChangeOp] = []


COPILOT_SYSTEM = (
    "你是协同行程板的 AI 助手。输入是行程 JSON（含每个条目的 id）和用户指令。\n"
    "- 纯咨询/解释类问题：reply 里简洁作答，changes 留空；\n"
    "- 要求修改行程（减少步行/降预算/亲子化/增删地点/调时间…）：changes 列出改动，"
    "reply 一句话总述方案；\n"
    "- changes 规则：update/delete 必须用行程里已有的 stop_id；add 给 day+name"
    "（真实存在、高德可搜的规范名）；每条必须写 reason（为什么这么改，如"
    "「减少步行1.4km」「亲子友好」）；空字段/0 表示不改动该字段；\n"
    "- 保守改动：用户没要求的不要动；每条 reason 不超过 20 字，越精简越好。\n"
    "- 复杂/结构性请求（如把 15 天缩短到 7 天、换目的地、整体重排多天）也要**尽力完成**："
    "如实列出所有必要的增删改（删掉多余天的地点、把保留的重新分配到目标天数、按就近原则排序），"
    "reply 一句话总述方案；能合并的改动就合并，别写冗长解释——保持 JSON 紧凑。"
)


def trip_json_for_llm(title: str, destination: str, days: int, budget, stops: list[dict]) -> str:
    """给 LLM 的行程快照（含 id 供 update/delete 引用）。"""
    import json

    return json.dumps({
        "title": title, "destination": destination, "days": days, "budget": budget,
        "stops": [{k: s.get(k) for k in
                   ("id", "day", "order_no", "name", "note", "start_time",
                    "stay_min", "transport", "ticket_price")} for s in
                  sorted(stops, key=lambda x: (x.get("day") or 1, x.get("order_no") or 0))],
    }, ensure_ascii=False)


async def run_copilot(llm, trip_snapshot: str, prompt: str) -> CopilotResult:
    """行程编辑/问答的结构化提案。

    复杂请求（缩短天数、整体重排）会让规划模型产生很长的思考链 + 大量改动，
    reasoning + JSON 一起挤爆默认 token 预算 → 输出被截断成非法 JSON。故两级策略：
    ① 规划模型（v4-pro，质量好）配大 max_tokens，让思考和结构化输出都放得下；
    ② 仍失败则回退快模型（v4-flash 几乎不烧 reasoning 预算，8000 token 足以输出完整 JSON），
    最大化复杂请求的成功率——而不是一遇到大改就失败/劝退。
    """
    user = f"行程 JSON：\n{trip_snapshot}\n\n用户指令：{prompt}"
    try:
        return await asyncio.to_thread(
            llm.parse, user, CopilotResult, system=COPILOT_SYSTEM, max_tokens=16000,
        )
    except Exception:  # noqa: BLE001 — 截断/超限/非法 JSON 都回退快模型再试
        logger.warning("copilot planner attempt failed, retrying with fast model", exc_info=True)
        return await asyncio.to_thread(
            llm.parse, user, CopilotResult, system=COPILOT_SYSTEM,
            model=settings.model_classifier, max_tokens=8000,
        )


# ---------- 记账结算（Phase 41）：纯函数，最小转账次数 ----------

EXPENSE_CATEGORIES = ("餐饮", "交通", "门票", "住宿", "购物", "其他")


def settle_expenses(expenses: list[dict]) -> dict:
    """AA 结算。输入 [{payer_user_id, amount, category, participants: [user_id,...]}]。

    返回 {total, by_category, per_person: [{user_id, paid, share, balance}],
    transfers: [{from_user, to_user, amount}]}。balance>0 = 别人欠他。
    转账清单用贪心（最大债务配最大债权）逼近最小转账次数；<0.01 的零头不生成转账。
    """
    from collections import defaultdict

    paid: dict[str, float] = defaultdict(float)
    share: dict[str, float] = defaultdict(float)
    by_category: dict[str, float] = defaultdict(float)
    total = 0.0
    for e in expenses:
        amount = float(e.get("amount") or 0)
        parts = [p for p in (e.get("participants") or []) if p]
        if amount <= 0 or not parts:
            continue
        total += amount
        paid[e["payer_user_id"]] += amount
        by_category[e.get("category") or "其他"] += amount
        per = amount / len(parts)
        for p in parts:
            share[p] += per

    users = sorted(set(paid) | set(share))
    per_person = [{
        "user_id": u, "paid": round(paid[u], 2), "share": round(share[u], 2),
        "balance": round(paid[u] - share[u], 2),
    } for u in users]

    creditors = sorted([[p["user_id"], p["balance"]] for p in per_person if p["balance"] > 0.01],
                       key=lambda x: -x[1])
    debtors = sorted([[p["user_id"], -p["balance"]] for p in per_person if p["balance"] < -0.01],
                     key=lambda x: -x[1])
    transfers: list[dict] = []
    ci = di = 0
    while ci < len(creditors) and di < len(debtors):
        give = min(creditors[ci][1], debtors[di][1])
        if give > 0.01:
            transfers.append({"from_user": debtors[di][0], "to_user": creditors[ci][0],
                              "amount": round(give, 2)})
        creditors[ci][1] -= give
        debtors[di][1] -= give
        if creditors[ci][1] <= 0.01:
            ci += 1
        if debtors[di][1] <= 0.01:
            di += 1
    return {"total": round(total, 2),
            "by_category": {k: round(v, 2) for k, v in by_category.items()},
            "per_person": per_person, "transfers": transfers}
