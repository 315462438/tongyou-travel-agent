"""手账海报生成（Phase 13）

从已生成的攻略正文抽结构化点位（LLM）→ 补坐标+实景图（高德）→ 组装地图 URL
→ 写一条 meta.poster 的 assistant 消息供前端渲染成手账。
"""

import asyncio
import json
import logging
import math
from urllib.parse import quote, urlencode

import httpx
from sqlalchemy import select

from app.agent.context_security import EXTERNAL_POLICY, wrap_external
from app.config import settings
from app.db.models import TravelMessage
from app.db.session import get_session
from app.llm.client import get_llm
from app.schemas.critique_schema import PosterCritique
from app.schemas.poster_schema import PosterData
from app.tools.amap import enabled as amap_enabled
from app.tools.amap import search_poi

logger = logging.getLogger(__name__)

EXTRACT_SYSTEM = (
    "你是旅行手账整理助手，把攻略正文整理成「城市旅行路线图」海报数据。全部内容只用正文里"
    "真实出现的信息，不要编造。字段：\n"
    "- title：8-14 字小红书感标题（含目的地和天数）\n"
    "- theme：顶部主题短语，用·分隔 3 段，如「西湖烟雨·茶香宋韵·运河繁华」\n"
    "- subtitle：一句心情语\n"
    "- destination：目的地城市\n"
    "- stops：按游玩顺序的点位，每个含 day、order、name（能在地图搜到的规范地名）、"
    "type（spot 景点/food 餐馆/checkin 打卡点）、note（15 字内亮点）。每天 4-7 个点。\n"
    "- day_meta：给每天起一个路线名，含 day、title（如「西湖经典线」6 字内）、"
    "subtitle（路线主题，如「湖光山色·人文宋韵」）。\n"
    "- hotels：酒店/住宿推荐 2-4 个，含 name、area（地段）、price（价位，如「¥400/晚」）、note。"
    "正文没提具体酒店就按提到的住宿区域给建议，没有就留空列表。\n"
    "- foods：当地美食推荐 3-6 个，含 name、note（14 字内描述）。\n"
    "- specialties：当地特产/伴手礼 2-4 个，含 name、note。\n"
    "- tips：旅行贴士 2-4 条（最佳季节/交通/注意事项），每条一句话。"
)

POSTER_CRITIQUE_SYSTEM = (
    "你是手账质检员，只挑明显硬伤，默认点位是够的（ok=true）。\n"
    "只有出现明显缺失时才判 ok=false：某天只有 1 个点、或整份全是景点完全没有餐馆/美食。\n"
    "只要每天有 2 个以上点、且大体覆盖玩和吃，就 ok=true。用 add_hints 简述要补什么。"
)


def _img_proxy(url: str) -> str:
    return f"/travel/api/img?u={quote(url, safe='')}"


def _staticmap_url(points: list[dict], size: str = "750*450") -> str:
    """points: [{location, order, day}] → /api/staticmap 相对 URL（不含 key）。"""
    pts = ";".join(p["location"] for p in points)
    labels = ",".join(str(p.get("order") or i + 1) for i, p in enumerate(points))
    days = ",".join(str(p.get("day") or 1) for p in points)
    return "/travel/api/staticmap?" + urlencode(
        {"pts": pts, "labels": labels, "days": days, "size": size}
    )


def _existing_spot_index(cid: str) -> dict:
    """从会话里最近的 amap 来源取已有景点坐标/图，避免重复查高德。"""
    from app.agent.orchestrator import _last_sources_and_dest  # 复用

    idx: dict[str, dict] = {}
    with get_session() as db:
        msgs = db.execute(
            select(TravelMessage)
            .where(TravelMessage.conversation_id == cid, TravelMessage.role == "assistant")
            .order_by(TravelMessage.created_at.desc())
        ).scalars().all()
    for m in msgs:
        if not m.meta_json:
            continue
        for s in (json.loads(m.meta_json).get("sources") or []):
            for img in s.get("images") or []:
                if img.get("name") and img.get("url"):
                    idx.setdefault(img["name"], {"photo": img["url"]})
    return idx


# 高德 key 与铺探共用，QPS 配额低 → 限制海报补全时的并发（配合 amap 内部退避重试）
_AMAP_CONCURRENCY = 4


async def _enrich(stops: list, destination: str, spot_idx: dict) -> list[dict]:
    """给每个 stop 补坐标 + 实景图。限流并发查高德，按名去重。"""
    out: list[dict] = []
    sem = asyncio.Semaphore(_AMAP_CONCURRENCY)
    async with httpx.AsyncClient(trust_env=False) as client:
        async def resolve(stop):
            async with sem:
                info = await search_poi(client, stop.name, city=destination)
            return stop, info

        results = await asyncio.gather(*[resolve(s) for s in stops])
    for stop, info in results:
        if not info:
            continue
        photo = info.get("photo") or ""
        if not photo:  # 高德无图时回退会话里已有的同名图
            for k, v in spot_idx.items():
                if stop.name in k or k in stop.name:
                    photo = v.get("photo", "")
                    break
        out.append({
            "day": stop.day, "order": stop.order or (len(out) + 1),
            "name": stop.name, "type": stop.type, "note": stop.note,
            "location": info["location"],
            "photo": _img_proxy(photo) if photo else "",
        })
    return out


async def _enrich_photos(names: list[str], destination: str, spot_idx: dict) -> dict:
    """给一批名字并发补高德实景图，返回 {name: photo_proxy_url}。缺图留空串。"""
    out: dict[str, str] = {}
    if not names:
        return out
    sem = asyncio.Semaphore(_AMAP_CONCURRENCY)

    async def one(client, n):
        async with sem:
            return await search_poi(client, n, city=destination)

    async with httpx.AsyncClient(trust_env=False) as client:
        results = await asyncio.gather(
            *[one(client, n) for n in names], return_exceptions=True
        )
    for name, info in zip(names, results):
        photo = ""
        if isinstance(info, dict):
            photo = info.get("photo") or ""
        if not photo:  # 回退会话来源里的同名图
            for k, v in spot_idx.items():
                if name in k or k in name:
                    photo = v.get("photo", "")
                    break
        out[name] = _img_proxy(photo) if photo else ""
    return out


def _haversine_km(a: str, b: str) -> float:
    """两个 'lng,lat' 点的球面距离（公里）。"""
    try:
        lng1, lat1 = (float(x) for x in a.split(","))
        lng2, lat2 = (float(x) for x in b.split(","))
    except (ValueError, AttributeError):
        return 0.0
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _route_distance(stops: list[dict]) -> float:
    """按顺序把相邻点位距离累加（估算路线长度，公里）。"""
    locs = [s["location"] for s in stops if s.get("location")]
    return sum(_haversine_km(locs[i], locs[i + 1]) for i in range(len(locs) - 1))


def _build_poster_payload(
    data: PosterData, enriched: list[dict],
    hotel_photos: dict, food_photos: dict,
) -> dict:
    """组装前端 meta.poster：整体地图 + 按天分区。"""
    if not enriched:
        return {}
    meta_by_day = {m.day: m for m in data.day_meta}
    # 按天分组、天内按 order
    by_day: dict[int, list[dict]] = {}
    for s in enriched:
        by_day.setdefault(s["day"], []).append(s)
    days_out = []
    for day in sorted(by_day):
        stops = sorted(by_day[day], key=lambda x: x["order"])
        for i, s in enumerate(stops, 1):  # 当天重新编号
            s["order"] = i
        dist = _route_distance(stops)
        dm = meta_by_day.get(day)
        days_out.append({
            "day": day,
            "title": (dm.title if dm else "") or f"Day {day} 路线",
            "subtitle": dm.subtitle if dm else "",
            "distance": f"约{round(dist)}公里" if dist >= 1 else "",
            "duration": "建议整日游" if len(stops) >= 5 else "建议半日游",
            # 每天一张路线小图（高德静态图 marker 上限约 10，逐天出图天然安全）
            "map": _staticmap_url([{**s, "day": day} for s in stops[:10]], size="500*400")
            if len(stops) >= 1 else "",
            "stops": [{"name": s["name"], "type": s["type"], "note": s["note"],
                       "photo": s["photo"], "order": s["order"]} for s in stops],
        })
    # 全程图仅在点位不超过高德上限时才出，否则留空（前端改用逐天小图）
    overall = _staticmap_url(enriched, size="560*620") if 2 <= len(enriched) <= 10 else ""
    hotels = [
        {"name": h.name, "area": h.area, "price": h.price, "note": h.note,
         "photo": hotel_photos.get(h.name, "")}
        for h in data.hotels
    ]
    foods = [
        {"name": f.name, "note": f.note, "photo": food_photos.get(f.name, "")}
        for f in data.foods
    ]
    specialties = [{"name": s.name, "note": s.note} for s in data.specialties]
    return {
        "title": data.title,
        "subtitle": data.subtitle,
        "theme": data.theme,
        "destination": data.destination,
        "overall_map": overall,
        "days": days_out,
        "hotels": hotels,
        "foods": foods,
        "specialties": specialties,
        "tips": list(data.tips),
    }


def generate_poster(cid: str, message_id: str) -> None:
    """BackgroundTasks 入口：从某条攻略消息生成手账海报消息。

    先占一条流式占位消息（让 _is_running 判为处理中，前端持续轮询到海报出现），
    结束时把它终稿为海报/错误提示。
    """
    from app.agent.cancel import TurnCancelled, clear_cancel

    msg_id = _add_streaming(cid)
    try:
        asyncio.run(_run(cid, message_id, msg_id))
    except TurnCancelled:
        _finalize(msg_id, "已停止本次海报生成。", None)
    except Exception:  # noqa: BLE001
        logger.error("poster generation failed for %s", cid, exc_info=True)
        _finalize(msg_id, "抱歉，海报生成失败了，请重试。", None)
    finally:
        clear_cancel(cid)  # 残留标记会误杀下一轮消息（同 budget，2026-07-31）


async def _run(cid: str, message_id: str, msg_id: str) -> None:
    # 终稿必须在 _run 内部做：asyncio.run 退出会 join 默认线程池（等孤儿 LLM 线程），
    # 外层 generate_poster 的兜底 finalize 会被拖到分钟级之后（同 budget，2026-07-31）。
    from app.agent.cancel import TurnCancelled, clear_cancel

    try:
        await _run_inner(cid, message_id, msg_id)
    except TurnCancelled:
        _finalize(msg_id, "已停止本次海报生成。", None)
        clear_cancel(cid)


async def _run_inner(cid: str, message_id: str, msg_id: str) -> None:
    with get_session() as db:
        src_msg = db.get(TravelMessage, message_id)
        guide = src_msg.content if src_msg else ""
    if not guide:
        _finalize(msg_id, "找不到要做海报的攻略内容。", None)
        return
    if not amap_enabled():
        _finalize(msg_id, "手账海报需要地图服务，当前未配置。", None)
        return

    from app.agent import cancel

    _progress(cid, "正在整理手账海报…")
    llm = get_llm()
    cancel.check(cid)
    data = await _poster_data(cid, message_id, guide, llm)
    if data is None:
        _finalize(msg_id, "海报要点提取失败了，请重试。", None)
        return
    if not data.stops:
        _finalize(msg_id, "这份攻略里没找到可上图的地点。", None)
        return

    _progress(cid, "正在在地图上定位景点、餐馆、打卡点…")
    cancel.check(cid)
    spot_idx = _existing_spot_index(cid)
    enriched = await _enrich(data.stops, data.destination, spot_idx)

    # 反思循环（Phase 14）：点位明显不够才补一轮（自检静默、用快模型，避免拖慢）
    rounds = 0
    while settings.reflection_enabled and rounds < settings.graph_max_poster_rounds:
        cancel.check(cid)
        crit = _critique_poster(enriched)
        if crit is None or crit.ok:
            break
        rounds += 1
        _progress(cid, f"手账点位不够丰富，正在补充…")
        more = _extract_more_stops(llm, guide, data, enriched, crit.add_hints)
        if not more:
            break
        extra = await _enrich(more, data.destination, spot_idx)
        have = {(s["day"], s["name"]) for s in enriched}
        enriched += [s for s in extra if (s["day"], s["name"]) not in have]

    # 酒店、美食并发补实景图（右栏卡片用）
    hotel_photos = await _enrich_photos([h.name for h in data.hotels], data.destination, spot_idx)
    food_photos = await _enrich_photos([f.name for f in data.foods], data.destination, spot_idx)

    payload = _build_poster_payload(data, enriched, hotel_photos, food_photos)
    if not payload:
        _finalize(msg_id, "没能给这些地点定位到坐标，无法出图，请重试。", None)
        return
    _finalize(msg_id, data.title, {"poster": payload})


async def _poster_data(cid: str, message_id: str, guide: str, llm) -> PosterData | None:
    """拿海报视图数据：优先从本体对象图投影（零 LLM 调用），失败回退旧的直接抽取。

    Phase 86：对象图由「攻略 → TripObject」一次抽取产出并缓存，预算面板共用同一份。
    此前这里和 budget.py 各抽一次，同一份行程被解析两遍且结果常对不上。
    """
    from app.agent import cancel

    if settings.ontology_enabled:
        try:
            from app.ontology.extract import POSTER_LANES
            from app.ontology.projections import to_poster_data
            from app.ontology.store import ensure_trip_object

            # 只抽海报要的两路（画像 + 逐日地点），不为预算面板的数据买单
            trip = await ensure_trip_object(cid, message_id, llm=llm, need=POSTER_LANES)
            if trip is not None and trip.stops:
                return to_poster_data(trip)
            if trip is not None:
                logger.info("ontology trip has no stops, falling back (cid=%s)", cid)
        except cancel.TurnCancelled:
            raise
        except Exception:  # noqa: BLE001 — 本体层出问题不能让海报功能整个不可用
            logger.warning("ontology poster projection failed, falling back", exc_info=True)

    # 回退：直接从正文抽（Phase 13 旧路径）。截断上限保留原值，它只在本体层不可用时生效。
    try:
        # 从已生成的攻略里抽点位是结构化任务，用快模型（v4-flash）即可，明显更快。
        # to_thread + wait_cancellable：原来直接同步调用会阻塞事件循环，且抽取因
        # 结构化重试拖长时停止只能干等（线上实测 3 分钟）；现在等待期间每秒响应停止。
        return await cancel.wait_cancellable(cid, asyncio.to_thread(
            llm.parse, wrap_external(guide[:6000], source="guide"), PosterData,
            model=settings.model_classifier, system=EXTRACT_SYSTEM + EXTERNAL_POLICY,
        ))
    except cancel.TurnCancelled:
        raise
    except Exception:  # noqa: BLE001
        logger.warning("poster extract failed", exc_info=True)
        return None


def _critique_poster(enriched: list[dict]) -> PosterCritique | None:
    """自检点位是否够详细。失败返回 None（当作达标）。"""
    brief = "\n".join(
        f"Day{s['day']} [{s['type']}] {s['name']}（note:{s['note'] or '无'}）" for s in enriched
    )
    try:
        return get_llm().parse(brief, PosterCritique, model=settings.model_classifier,
                               system=POSTER_CRITIQUE_SYSTEM)
    except Exception:  # noqa: BLE001
        logger.warning("poster critique failed", exc_info=True)
        return None


def _extract_more_stops(llm, guide: str, data: PosterData, enriched: list[dict], hints: list[str]):
    """按自检提示再抽一批点位（返回 PosterStop 列表；失败返回 []）。"""
    have = "、".join(s["name"] for s in enriched)
    prompt = (
        f"攻略正文：\n{guide[:5000]}\n\n已有点位：{have}\n\n"
        f"需要补充的方向：{'；'.join(hints)}\n请只输出新增的点位（不要重复已有的）。"
    )
    try:
        # 补点用快模型（v4-flash）：只是加几个点，不必占用大模型时间
        more = llm.parse(prompt, PosterData, model=settings.model_classifier, system=EXTRACT_SYSTEM)
        return more.stops
    except Exception:  # noqa: BLE001
        logger.warning("poster extract_more failed", exc_info=True)
        return []


# ---------- 消息落库 ----------

def _add_streaming(cid: str) -> str:
    """占一条流式 assistant 消息（生成期间 running=true，前端持续轮询）。"""
    with get_session() as db:
        m = TravelMessage(
            conversation_id=cid, role="assistant", content="",
            meta_json=json.dumps({"streaming": True}),
        )
        db.add(m)
        db.commit()
        return m.id


def _finalize(msg_id: str, content: str, meta: dict | None) -> None:
    """把占位消息终稿为海报/提示（去掉 streaming 标记），并清掉海报生成时的临时进度。"""
    cid = None
    with get_session() as db:
        m = db.get(TravelMessage, msg_id)
        if m is None:
            return
        cid = m.conversation_id
        m.content = content
        m.meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
        db.commit()
    if cid:
        from app.agent.orchestrator import clear_plain_progress

        clear_plain_progress(cid)


def _progress(cid: str, text: str) -> None:
    with get_session() as db:
        db.add(TravelMessage(conversation_id=cid, role="progress", content=text))
        db.commit()
