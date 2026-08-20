"""协同行程 API（Phase 35）：多人路线规划板。

协同方式：轮询（板打开时前端 2.5s 拉详情，updated_at 变化即刷新）；
冲突策略：条目级 last-write-wins（v1 明确不做锁/CRDT）。
权限：所有端点需登录；行程内操作需成员（owner/editor），邀请/删除仅 owner。
AI：起草与检查走 BackgroundTasks（trip.ai_status 标记进行中，轮询看结果）；
串路线是同步端点（补坐标 + 纯几何排序，秒级）。
"""

import asyncio
import json
import logging
import re
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import settings
from app.db.models import (
    TravelNotification, TravelTrip, TravelTripChatMessage, TravelTripComment, TravelTripEvent,
    TravelTripMember, TravelTripStop, TravelTripSuggestion, TravelUser,
)
from app.db.session import get_db, get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trips", tags=["trips"])

MAX_TRIP_DAYS = 30
IMPORT_DAYS_PER_CHUNK = 1


def _clamp_trip_days(days: int) -> int:
    return max(1, min(MAX_TRIP_DAYS, days))


def _member(db: Session, trip_id: str, user: TravelUser) -> TravelTrip:
    """成员校验：非成员一律 404（不泄露行程存在性）。"""
    trip = db.get(TravelTrip, trip_id)
    if trip is None:
        raise HTTPException(404, "行程不存在")
    row = db.get(TravelTripMember, (trip_id, user.id))
    if row is None or row.status != "accepted":  # 35b：待接受的邀请不可见内容
        raise HTTPException(404, "行程不存在")
    return trip


def _touch(db: Session, trip: TravelTrip) -> None:
    from app.db.models import _now

    trip.updated_at = _now()


def _log_event(db: Session, trip_id: str, user: TravelUser, action: str) -> None:
    """修改记录（Phase 38）：轻量留痕，随主操作一起提交。"""
    db.add(TravelTripEvent(trip_id=trip_id, user_id=user.id, action=action[:250]))


def _stop_dict(s: TravelTripStop) -> dict:
    from app.agent.nav_links import build_nav_links

    return {"id": s.id, "day": s.day, "order_no": s.order_no,
            "name": s.name, "note": s.note or "", "location": s.location or "",
            "start_time": s.start_time or "", "stay_min": s.stay_min,
            "transport": s.transport or "", "ticket_price": s.ticket_price,
            "tags": [t for t in (s.tags or "").split(",") if t],
            # Phase 100：导航 deep link 在**后端**算。坐标系分流（境内 GCJ→WGS 才给苹果）
            # 只有这一处实现，不让前端重算——两端各写一份必然漂移。无坐标时为 None。
            "nav": build_nav_links(s.location, s.name)}


def _looks_like_lnglat(text: str) -> bool:
    return bool(re.fullmatch(r"\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*", text or ""))


def _with_no_location_tag(tags: list[str] | None, enabled: bool) -> str | None:
    values = [t.strip() for t in (tags or []) if t.strip() and t.strip() != "no_location"]
    if enabled:
        values.append("no_location")
    return ",".join(dict.fromkeys(values))[:128] or None


def _now_ts():
    from app.db.models import _now

    return _now().replace(tzinfo=None)


def _load_day_plans(trip: TravelTrip) -> list[dict]:
    """解析 trip.day_plan_json → list（坏 JSON/空 → []）。检查中心与 day-cities 共用。"""
    if not trip.day_plan_json:
        return []
    import json as _json

    try:
        plans = _json.loads(trip.day_plan_json)
    except ValueError:
        return []
    return plans if isinstance(plans, list) else []


# 「西安至兰州」「合肥→武汉」这类是**路线描述**不是城市名，split_cities 拆不开它们
# （分隔符只认顿号/逗号/斜杠/空格），当成单城拿去查 POI 必然全军覆没。
_ROUTE_DESC_MARKERS = ("至", "到", "→", "->", "—", "~", "－")


def _is_single_city(destination: str, dest_cities: list[str]) -> bool:
    """destination 是否是**一个干净的城市名**（可作为全程 POI 检索城市）。纯函数。"""
    if len(dest_cities) != 1:
        return False
    name = dest_cities[0]
    return bool(name) and len(name) <= 10 and not any(m in name for m in _ROUTE_DESC_MARKERS)


def _trip_city_for_day(trip: TravelTrip, day: int) -> str:
    """数据库中的逐日计划 → 该天 POI 检索城市；缺天沿用相邻明确城市。

    2026-08-01：单城行程一律用行程目的地。`overnight_city` 是「当晚睡哪」，
    中途停留/转移日里它是**到达城**，拿它查当天景点会整城查错
    （六安一日游 + 当晚到武汉过夜 → 五个六安地点全按武汉查）。
    这里是「重新定位」按钮和手动加地点走的路径，与导入路径 `_geocode_stops_by_city`
    必须同规则，否则修完导入、点重新定位又被打回去。
    """
    from app.agent.site_router import split_cities

    dest_cities = split_cities(trip.destination or "")
    if _is_single_city(trip.destination or "", dest_cities):
        return dest_cities[0]
    plans = _load_day_plans(trip)
    explicit: dict[int, str] = {}
    for plan in plans:
        try:
            plan_day = int(plan.get("day"))
        except (AttributeError, TypeError, ValueError):
            continue
        city = str(plan.get("overnight_city") or "").strip()
        if city:
            explicit[plan_day] = city
    if day in explicit:
        return explicit[day]
    previous = next((explicit[d] for d in range(day - 1, 0, -1) if d in explicit), "")
    following = next((explicit[d] for d in range(day + 1, trip.days + 1) if d in explicit), "")
    return previous or following or trip.destination


def _trip_detail(db: Session, trip: TravelTrip) -> dict:
    stops = db.execute(
        select(TravelTripStop).where(TravelTripStop.trip_id == trip.id)
        .order_by(TravelTripStop.day, TravelTripStop.order_no)
    ).scalars().all()
    members = db.execute(
        select(TravelTripMember, TravelUser)
        .join(TravelUser, TravelUser.id == TravelTripMember.user_id)
        .where(TravelTripMember.trip_id == trip.id, TravelTripMember.status == "accepted")
    ).all()
    import json as _json

    breakdown: dict = {}
    hotel_recommendations: list = []
    day_titles: dict = {}
    day_plans = _load_day_plans(trip)
    if trip.budget_breakdown_json:
        try:
            breakdown = _json.loads(trip.budget_breakdown_json)
        except ValueError:
            breakdown = {}
    if trip.hotel_recommendations_json:
        try:
            hotel_recommendations = _json.loads(trip.hotel_recommendations_json)
        except ValueError:
            hotel_recommendations = []
    if trip.day_titles_json:
        try:
            day_titles = _json.loads(trip.day_titles_json)
        except ValueError:
            day_titles = {}
    return {
        "id": trip.id, "title": trip.title, "destination": trip.destination,
        "days": trip.days, "budget": trip.budget, "budget_breakdown": breakdown,
        "day_plans": day_plans, "hotel_recommendations": hotel_recommendations,
        "day_titles": day_titles,
        "start_date": trip.start_date or "",
        "source_conversation_id": trip.source_conversation_id or "",
        "ai_status": trip.ai_status, "ai_review": trip.ai_review or "",
        "updated_at": trip.updated_at.isoformat() if trip.updated_at else "",
        "members": [{
            "username": u.username, "role": m.role,
            "online": bool(m.last_seen and (_now_ts() - m.last_seen.replace(tzinfo=None)).total_seconds() < 8),
            "editing_day": m.editing_day,
        } for m, u in members],
        "stops": [_stop_dict(s) for s in stops],
    }


# ---------- 行程 CRUD ----------

class TripCreate(BaseModel):
    title: str = "新行程"
    destination: str = ""
    days: int = 2


@router.post("")
def create_trip(body: TripCreate, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    trip = TravelTrip(owner_id=user.id, title=body.title.strip() or "新行程",
                      destination=body.destination.strip(), days=_clamp_trip_days(body.days))
    db.add(trip)
    db.flush()
    db.add(TravelTripMember(trip_id=trip.id, user_id=user.id, role="owner"))
    db.commit()
    return {"id": trip.id}


@router.get("")
def list_trips(db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    rows = db.execute(
        select(TravelTrip, TravelTripMember.role)
        .join(TravelTripMember, TravelTripMember.trip_id == TravelTrip.id)
        .where(TravelTripMember.user_id == user.id, TravelTripMember.status == "accepted")
        .order_by(TravelTrip.updated_at.desc())
    ).all()
    return [{"id": t.id, "title": t.title, "destination": t.destination, "days": t.days,
             "role": role, "updated_at": t.updated_at.isoformat() if t.updated_at else ""}
            for t, role in rows]


@router.get("/{trip_id}")
def get_trip(trip_id: str, editing_day: int | None = None,
             db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    # Phase 38 presence：轮询顺带上报「我在线、正在看第几天」（不 touch trip.updated_at）
    from app.db.models import _now

    me = db.get(TravelTripMember, (trip_id, user.id))
    if me is not None:
        me.last_seen = _now()
        me.editing_day = editing_day
        db.commit()
    return _trip_detail(db, trip)


@router.get("/{trip_id}/source-guide")
def get_source_guide(
    trip_id: str,
    db: Session = Depends(get_db),
    user: TravelUser = Depends(get_current_user),
):
    """行程成员只读查看被导入的原攻略，不授予来源私人会话的访问权。"""
    from app.db.models import TravelMessage
    import json as _json

    trip = _member(db, trip_id, user)
    if not trip.source_message_id:
        raise HTTPException(404, "这份行程没有关联的原攻略")
    message = db.get(TravelMessage, trip.source_message_id)
    if (
        message is None
        or message.role != "assistant"
        or message.conversation_id != trip.source_conversation_id
        or not (message.content or "").strip()
    ):
        raise HTTPException(404, "原攻略已不存在")
    meta = {}
    if message.meta_json:
        try:
            meta = _json.loads(message.meta_json)
        except (TypeError, ValueError):
            meta = {}
    sources = []
    for source in meta.get("sources") or []:
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or "").strip()
        url = str(source.get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            sources.append({"title": title or url, "url": url})
    is_owner = trip.owner_id == user.id
    return {
        "title": trip.title,
        "content": message.content,
        "sources": sources,
        "can_open_conversation": is_owner,
        "conversation_id": trip.source_conversation_id if is_owner else "",
    }


@router.delete("/{trip_id}")
def delete_trip(trip_id: str, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    if trip.owner_id != user.id:
        raise HTTPException(403, "只有创建者能删除行程")
    for s in db.execute(select(TravelTripStop).where(TravelTripStop.trip_id == trip_id)).scalars():
        db.delete(s)
    for m in db.execute(select(TravelTripMember).where(TravelTripMember.trip_id == trip_id)).scalars():
        db.delete(m)
    for message in db.execute(
        select(TravelTripChatMessage).where(TravelTripChatMessage.trip_id == trip_id)
    ).scalars():
        db.delete(message)
    # Phase 97：行程没了，指向它的群聊通知也要撤销，否则点开通知跳到一个 404 的行程
    from app.api.notification_api import delete_target_notifications

    delete_target_notifications(db, "trip", trip_id)
    db.delete(trip)
    db.commit()
    return {"ok": True}


class InviteBody(BaseModel):
    username: str


@router.post("/{trip_id}/invite")
def invite_member(trip_id: str, body: InviteBody,
                  db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    if trip.owner_id != user.id:
        raise HTTPException(403, "只有创建者能邀请成员")
    target = db.execute(
        select(TravelUser).where(TravelUser.username == body.username.strip())
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(404, "用户不存在，请确认对方已注册")
    existing = db.get(TravelTripMember, (trip_id, target.id))
    if existing is not None:
        raise HTTPException(409, "已是成员" if existing.status == "accepted" else "已邀请，等待对方接受")
    db.add(TravelTripMember(trip_id=trip_id, user_id=target.id, role="editor", status="pending"))
    _touch(db, trip)
    db.commit()
    return {"ok": True}


# ---------- 条目 CRUD ----------

class StopCreate(BaseModel):
    day: int = 1
    name: str
    note: str = ""
    location: str = ""  # Phase 46：已知坐标（如高德酒店）直接带入，跳过地理编码
    transport: str = ""
    start_time: str = ""
    stay_min: int | None = None
    ticket_price: float | None = None
    tags: list[str] = []
    no_location: bool = False


class StopPatch(BaseModel):
    name: str | None = None
    note: str | None = None
    location: str | None = None
    no_location: bool | None = None
    day: int | None = None
    order_no: int | None = None
    start_time: str | None = None  # "HH:MM"，空串=清除
    stay_min: int | None = None
    transport: str | None = None
    ticket_price: float | None = None
    tags: list[str] | None = None


@router.post("/{trip_id}/stops")
async def add_stop(trip_id: str, body: StopCreate,
                   db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "地点名不能为空")
    from app.agent.trip_planner import geocode_names

    loc_text = (body.location or "").strip()
    loc = loc_text if _looks_like_lnglat(loc_text) else ""
    if body.no_location:
        loc = ""
    elif not loc:
        try:  # 高德补坐标失败不阻塞添加（无坐标条目串路线时跳过）
            city = _trip_city_for_day(trip, _clamp_trip_days(body.day))
            query = loc_text or name
            loc = (await geocode_names([query], city)).get(query, "")
        except Exception:  # noqa: BLE001
            logger.warning("geocode failed for %s", name, exc_info=True)
    max_no = max([s.order_no for s in db.execute(
        select(TravelTripStop).where(TravelTripStop.trip_id == trip_id)
    ).scalars()] or [-1])
    stop = TravelTripStop(trip_id=trip_id, day=_clamp_trip_days(body.day), order_no=max_no + 1,
                          name=name, note=body.note.strip() or None, location=loc or None,
                          transport=body.transport.strip()[:16] or None,
                          start_time=body.start_time.strip() or None,
                          stay_min=max(0, body.stay_min or 0) or None,
                          tags=_with_no_location_tag(body.tags, body.no_location),
                          ticket_price=body.ticket_price if body.ticket_price and body.ticket_price > 0 else None)
    db.add(stop)
    _log_event(db, trip_id, user, f"添加了「{name}」(Day{stop.day})")
    _touch(db, trip)
    db.commit()
    return _stop_dict(stop)


@router.patch("/{trip_id}/stops/{stop_id}")
async def patch_stop(trip_id: str, stop_id: str, body: StopPatch,
                     db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    stop = db.get(TravelTripStop, stop_id)
    if stop is None or stop.trip_id != trip_id:
        raise HTTPException(404, "条目不存在")
    name_changed = False
    if body.name is not None and body.name.strip():
        name_changed = body.name.strip() != stop.name
        stop.name = body.name.strip()
        if name_changed and body.location is None and body.no_location is None:
            stop.location = None  # 改名后坐标失效；未提供定位关键词时下次串路线再补
    current_tags = [t for t in (stop.tags or "").split(",") if t]
    if body.no_location is True:
        stop.location = None
        stop.tags = _with_no_location_tag(body.tags if body.tags is not None else current_tags, True)
    elif body.no_location is False:
        from app.agent.trip_planner import geocode_names

        stop.tags = _with_no_location_tag(body.tags if body.tags is not None else current_tags, False)
        loc_text = (body.location or stop.name).strip()
        if not loc_text:
            stop.location = None
        elif _looks_like_lnglat(loc_text):
            stop.location = loc_text
        else:
            try:
                city = _trip_city_for_day(trip, stop.day)
                stop.location = (await geocode_names([loc_text], city)).get(loc_text, "") or None
            except Exception:  # noqa: BLE001
                logger.warning("geocode failed for %s", loc_text, exc_info=True)
                stop.location = None
    elif body.location is not None:
        from app.agent.trip_planner import geocode_names

        loc_text = body.location.strip()
        if not loc_text:
            stop.location = None
        elif _looks_like_lnglat(loc_text):
            stop.location = loc_text
        else:
            try:
                city = _trip_city_for_day(trip, stop.day)
                stop.location = (await geocode_names([loc_text], city)).get(loc_text, "") or None
            except Exception:  # noqa: BLE001
                logger.warning("geocode failed for %s", loc_text, exc_info=True)
                stop.location = None
    if body.note is not None:
        stop.note = body.note.strip() or None
    if body.day is not None:
        stop.day = _clamp_trip_days(body.day)
    if body.order_no is not None:
        stop.order_no = body.order_no
    if body.start_time is not None:
        stop.start_time = body.start_time.strip() or None
    if body.stay_min is not None:
        stop.stay_min = max(0, body.stay_min) or None
    if body.transport is not None:
        stop.transport = body.transport.strip() or None
    if body.ticket_price is not None:
        stop.ticket_price = body.ticket_price if body.ticket_price > 0 else None
    if body.tags is not None and body.no_location is None:
        stop.tags = _with_no_location_tag(body.tags, "no_location" in current_tags)
    if body.name is not None or body.note is not None or body.start_time is not None:
        _log_event(db, trip_id, user, f"编辑了「{stop.name}」")
    elif body.day is not None:
        _log_event(db, trip_id, user, f"把「{stop.name}」移到 Day{stop.day}")
    _touch(db, trip)
    db.commit()
    return _stop_dict(stop)


@router.delete("/{trip_id}/stops/{stop_id}")
def delete_stop(trip_id: str, stop_id: str,
                db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    stop = db.get(TravelTripStop, stop_id)
    if stop is None or stop.trip_id != trip_id:
        raise HTTPException(404, "条目不存在")
    _log_event(db, trip_id, user, f"删除了「{stop.name}」")
    db.delete(stop)
    _touch(db, trip)
    db.commit()
    return {"ok": True}


# ---------- AI 三件套 ----------

@router.post("/{trip_id}/ai/order")
async def ai_order(trip_id: str, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """一键串路线：先给缺坐标的条目补坐标，再纯几何排序（同步，秒级）。"""
    trip = _member(db, trip_id, user)
    stops = db.execute(
        select(TravelTripStop).where(TravelTripStop.trip_id == trip_id)
    ).scalars().all()
    if not stops:
        raise HTTPException(400, "行程还没有地点")
    from app.agent.trip_planner import geocode_names, order_stops, route_km

    missing_by_city: dict[str, list[TravelTripStop]] = {}
    for stop in stops:
        if not stop.location:
            missing_by_city.setdefault(_trip_city_for_day(trip, stop.day), []).append(stop)
    for city, rows in missing_by_city.items():
        try:
            located = await geocode_names([s.name for s in rows], city)
            for stop in rows:
                if stop.name in located:
                    stop.location = located[stop.name]
        except Exception:  # noqa: BLE001
            logger.warning("geocode batch failed for %s", city, exc_info=True)
    dicts = [_stop_dict(s) for s in stops]
    before = route_km(sorted(dicts, key=lambda s: (s["day"], s["order_no"])))
    ordered = order_stops(dicts)
    by_id = {s["id"]: s["order_no"] for s in ordered}
    for s in stops:
        s.order_no = by_id.get(s.id, s.order_no)
    _log_event(db, trip_id, user, "执行了一键串路线")
    _touch(db, trip)
    db.commit()
    return {"ok": True, "km_before": round(before, 1), "km_after": round(route_km(ordered), 1),
            "unlocated": [s["name"] for s in ordered if not s["location"]]}


@router.post("/{trip_id}/geocode/repair")
async def repair_trip_geocode(
    trip_id: str, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user),
):
    """按逐日城市强制重定位；新结果缺失时仅清除明显远离城市锚点的旧坐标。"""
    trip = _member(db, trip_id, user)
    stops = db.execute(
        select(TravelTripStop).where(TravelTripStop.trip_id == trip_id)
    ).scalars().all()
    if not stops:
        raise HTTPException(400, "行程还没有地点")

    from app.agent.trip_planner import geocode_names
    from app.tools.geocode import location_near_context, resolve_city_context

    groups: dict[str, list[TravelTripStop]] = {}
    for stop in stops:
        groups.setdefault(_trip_city_for_day(trip, stop.day), []).append(stop)

    contexts = {
        city: await resolve_city_context(city)
        for city in groups
    }
    resolved: dict[str, str] = {}
    primary_city: dict[str, str] = {}
    for city, rows in groups.items():
        for stop in rows:
            primary_city[stop.id] = city
        try:
            found = await geocode_names(
                [stop.name.replace("🏨", "").strip() for stop in rows],
                city,
                force_refresh=True,
            )
        except Exception:  # noqa: BLE001
            logger.warning("repair geocode failed for %s", city, exc_info=True)
            found = {}
        for stop in rows:
            query = stop.name.replace("🏨", "").strip()
            if query in found:
                resolved[stop.id] = found[query]

    # 一天可跨城（例如上午吉隆坡、下午飞仙本那）：主城市未命中时，在本行程其他城市
    # 中受 country+120km 约束重试。只收首个合法结果，绝不扩大到全国/全球猜同名点。
    route_cities = list(dict.fromkeys(
        [_trip_city_for_day(trip, day) for day in range(1, trip.days + 1)]
        + list(groups)
    ))
    for city in route_cities:
        pending = [
            stop for stop in stops
            if stop.id not in resolved and primary_city.get(stop.id) != city
        ]
        if not pending:
            continue
        try:
            found = await geocode_names(
                [stop.name.replace("🏨", "").strip() for stop in pending],
                city,
                force_refresh=True,
            )
        except Exception:  # noqa: BLE001
            logger.warning("repair fallback geocode failed for %s", city, exc_info=True)
            found = {}
        for stop in pending:
            query = stop.name.replace("🏨", "").strip()
            if query in found:
                resolved[stop.id] = found[query]

    updated = cleared = 0
    unresolved: list[str] = []
    valid_contexts = [ctx for ctx in contexts.values() if ctx]
    for stop in stops:
        if stop.id in resolved:
            if stop.location != resolved[stop.id]:
                stop.location = resolved[stop.id]
                updated += 1
            continue
        unresolved.append(stop.name)
        # 只有旧点远离本行程所有城市才清除；跨城日中落在另一目的地城市的旧点可保留。
        if stop.location and valid_contexts and not any(
            location_near_context(stop.location, ctx) for ctx in valid_contexts
        ):
            stop.location = None
            cleared += 1

    _log_event(db, trip_id, user, f"重新定位了全部地点（更新{updated}，清除错误{cleared}）")
    _touch(db, trip)
    db.commit()
    return {
        "ok": True,
        "updated": updated,
        "cleared": cleared,
        "unresolved": unresolved,
    }


class SeedBody(BaseModel):
    prompt: str


@router.post("/{trip_id}/ai/seed")
def ai_seed(trip_id: str, body: SeedBody, background: BackgroundTasks,
            db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """AI 起草：清空现有条目、按需求生成一版可编辑的路线（后台跑，轮询看 ai_status）。"""
    trip = _member(db, trip_id, user)
    if trip.ai_status in ("seeding", "reviewing", "copilot"):
        raise HTTPException(409, "AI 正在处理中")
    has_stops = db.execute(
        select(TravelTripStop).where(TravelTripStop.trip_id == trip_id).limit(1)
    ).scalar_one_or_none() is not None
    if has_stops:  # Phase 37：非空行程不直接覆盖，走 Copilot 提案（AI 永不直接改）
        trip.ai_status = "copilot"
        db.commit()
        background.add_task(_run_copilot_task, trip_id, user.id,
                            f"请重新起草整个行程：{body.prompt.strip()}（用增删改表达对现有条目的调整）")
        return {"ok": True, "proposal": True}
    trip.ai_status = "seeding"
    trip.ai_review = "AI 起草中…"
    db.commit()
    background.add_task(_run_seed, trip_id, body.prompt.strip())
    return {"ok": True}


def _run_seed(trip_id: str, prompt: str) -> None:
    from app.agent.trip_planner import geocode_names, order_stops, seed_draft
    from app.llm.client import get_llm

    async def _go():
        draft = await seed_draft(get_llm(), prompt)
        located = await _geocode_stops_by_city(
            draft.stops, draft.day_plans, draft.destination, geocode_names,
        )
        return draft, located

    try:
        draft, located = asyncio.run(_go())
        with get_session() as db:
            trip = db.get(TravelTrip, trip_id)
            if trip is None:
                return
            for old in db.execute(
                select(TravelTripStop).where(TravelTripStop.trip_id == trip_id)
            ).scalars():
                db.delete(old)
            db.flush()
            rows = [{"id": f"tmp{i}", "day": s.day, "order_no": i, "name": s.name,
                     "note": s.note, "location": located.get((s.day, s.name), "")}
                    for i, s in enumerate(draft.stops)]
            from app.agent.trip_planner import order_stops as _order

            for r in _order(rows):
                db.add(TravelTripStop(trip_id=trip_id, day=r["day"], order_no=r["order_no"],
                                      name=r["name"], note=r["note"] or None,
                                      location=r["location"] or None))
            trip.title = draft.title[:200] or trip.title
            trip.destination = draft.destination[:60] or trip.destination
            trip.days = _clamp_trip_days(draft.days)
            if draft.day_plans:
                import json as _json

                trip.day_plan_json = _json.dumps([
                    {
                        "day": p.day,
                        "type": p.type if p.type in ("stay", "transit", "return") else "stay",
                        "overnight_required": p.overnight_required,
                        "overnight_city": p.overnight_city.strip(),
                    }
                    for p in draft.day_plans if 1 <= p.day <= trip.days
                ], ensure_ascii=False)
            trip.ai_status = None
            trip.ai_review = ""
            from app.db.models import _now

            trip.updated_at = _now()
            db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("trip seed failed for %s", trip_id, exc_info=True)
        with get_session() as db:
            trip = db.get(TravelTrip, trip_id)
            if trip is not None:
                trip.ai_status = "failed"
                trip.ai_review = "行程起草失败，请稍后重试。"
                db.commit()


@router.post("/{trip_id}/ai/review")
def ai_review(trip_id: str, background: BackgroundTasks,
              db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """AI 检查：算法算里程事实 + LLM 点评（后台跑，结果写 trip.ai_review）。"""
    trip = _member(db, trip_id, user)
    if trip.ai_status in ("seeding", "reviewing"):
        raise HTTPException(409, "AI 正在处理中")
    trip.ai_status = "reviewing"
    db.commit()
    background.add_task(_run_review, trip_id)
    return {"ok": True}


def _run_review(trip_id: str) -> None:
    from app.agent.trip_planner import review_trip
    from app.llm.client import get_llm

    try:
        with get_session() as db:
            trip = db.get(TravelTrip, trip_id)
            if trip is None:
                return
            stops = [_stop_dict(s) for s in db.execute(
                select(TravelTripStop).where(TravelTripStop.trip_id == trip_id)
            ).scalars()]
            title, destination = trip.title, trip.destination
        text = asyncio.run(review_trip(get_llm(), title, destination, stops))
        with get_session() as db:
            trip = db.get(TravelTrip, trip_id)
            if trip is not None:
                trip.ai_review = text[:4000]
                trip.ai_status = None
                from app.db.models import _now

                trip.updated_at = _now()
                db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("trip review failed for %s", trip_id, exc_info=True)
        with get_session() as db:
            trip = db.get(TravelTrip, trip_id)
            if trip is not None:
                trip.ai_status = "failed"
                db.commit()


# ---------- 邀请确认流（Phase 35b） ----------

@router.get("/invites/pending")
def my_invites(db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """我的待接受邀请（前端全局轮询弹卡）。"""
    rows = db.execute(
        select(TravelTripMember, TravelTrip, TravelUser)
        .join(TravelTrip, TravelTrip.id == TravelTripMember.trip_id)
        .join(TravelUser, TravelUser.id == TravelTrip.owner_id)
        .where(TravelTripMember.user_id == user.id, TravelTripMember.status == "pending")
    ).all()
    return [{"trip_id": t.id, "title": t.title, "destination": t.destination,
             "inviter": owner.username} for _m, t, owner in rows]


class RespondBody(BaseModel):
    accept: bool


@router.post("/{trip_id}/invites/respond")
def respond_invite(trip_id: str, body: RespondBody,
                   db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    row = db.get(TravelTripMember, (trip_id, user.id))
    if row is None or row.status != "pending":
        raise HTTPException(404, "邀请不存在或已处理")
    if body.accept:
        row.status = "accepted"
        _log_event(db, trip_id, user, "接受邀请加入了行程")
    else:
        db.delete(row)  # 拒绝即删除，owner 可再次邀请
    trip = db.get(TravelTrip, trip_id)
    if trip is not None:
        _touch(db, trip)
    db.commit()
    return {"ok": True, "accepted": body.accept}


# ---------- 主对话攻略一键导入（Phase 35b） ----------

class ImportBody(BaseModel):
    conversation_id: str
    message_id: str


IMPORT_SUMMARY_SYSTEM = (
    "从旅行攻略 Markdown 中只提取全局信息，不要输出逐日地点：\n"
    "- title 用攻略主题；destination 用能概括路线的目的地/区域；days 为攻略完整天数；\n"
    "- hotel_options：住宿推荐章节出现的具体候选酒店全部提取为 "
    "{city,hotel,price,source,note}；它们是备选，不等于已入住。没有具体酒店名就留空。\n"
    "- budget_items：若攻略明确写出预算/花费拆分，逐项填 {category, amount 金额数字}，"
    "category 用 住宿/交通/餐饮/门票/大交通/其他（大交通=城际机票火车，交通=市内通勤）；"
    "攻略没写预算就留空数组，不要估算编造。\n"
    "- foods：若攻略有美食推荐/必吃清单章节，提取每个美食项为 {name,category,city,price,note}。"
    "category 只能是 小吃/正餐/甜点 之一，price 是人均价格（元），note 是简短描述（最多30字）。"
    "**最多提取 15 项**，挑最值得吃的；没有美食章节就留空数组。\n"
    "- tips：若攻略有避坑提示/注意事项章节，提取每条提示为 {level,content}。"
    "level 根据重要性填 important（重要警告，如安全/诈骗/健康）或 notice（一般提醒）；"
    "content 是提示内容（最多80字）。**最多提取 12 条**；没有避坑章节就留空数组。"
)

IMPORT_DAYS_SYSTEM = (
    "从下面给定的少量 Day 攻略 Markdown 中只提取逐日行程：\n"
    "- stops：提取攻略中**明确出现**的活动和地点。优先级：\n"
    "  1）所有具体地点（景点/街区/餐厅/酒店/机场），必须全部提取；\n"
    "  2）重要的非地点活动（退房、值机、登机、过安检），必须保留；\n"
    "  3）常规活动（起床、早餐、午餐、晚餐、休息）可以合并简化或省略。\n"
    "  **每天最多 10 条**，优先保留地点和关键活动，避免输出过长导致截断。"
    "  地点类的 name 用规范名称，非地点类用简洁描述；"
    "  海外地点必须另填英文或当地官方 search_name，国内地点和非地点类事件 search_name 留空；\n"
    "- 按攻略的 Day 划分 day；若标题是 Day 11–12 这种范围，必须拆到对应每一天；"
    "必须检查本段列出的全部 Day，不要只提取前半段；\n"
    "- note 从攻略中摘一句该活动的要点（时段/看点/提示/方式），**note 最多 50 个汉字**；\n"
    "- start_time：若攻略明确写出该活动的开始时间（如 05:30、15:00），则填写为 HH:MM 格式，"
    "没有明确时间就留空；stay_min：若攻略写出停留时长，则填写分钟数，否则留空；\n"
    "- is_place：该条是否是地图上可定位的具体地点。景点/街区/餐厅/酒店/机场/车站填 true；"
    "起床、早餐、午餐、晚餐、休息、退房、值机、登机、过安检等日常活动填 false；\n"
    "- 不要把攻略末尾的美食清单、酒店候选、预算、避坑或参考来源当成逐日地点；\n"
    "- stops.transport 表示从上一地点到该地点的交通方式，只能填攻略明确写出的步行/公交/地铁/"
    "打车/驾车/骑行/包车/拼车/大巴/火车/飞机，没写留空；\n"
    "- day_plans：必须为本段出现的每一天各填一项 {day,type,overnight_required,overnight_city,day_title}。"
    "day_title 必须完整提取攻略中的 Day 标题（如 'Day 1 10.1 南京 吉隆坡：双子塔与无边泳池'），"
    "包括日期、城市、主题等所有信息；若攻略标题太简单只有 'Day 1'，则用 overnight_city 组成标题。"
    "type 只能是 stay、transit、return："
    "transit 仅用于**整天都在城际赶路/坐火车、当天没有正经游玩**的日子；"
    "**只要当天有像样的游玩（哪怕上午抵达、下午逛景点，或市内游 + 短途往返），一律标 stay，不要标 transit**；"
    "return 为最后返程回家那天。火车上过夜则 overnight_required=false、overnight_city留空；"
    "当天往返景点（如拉萨往返羊湖）应填实际回去住宿的城市而不是景点所在行政区；return 无需住宿。\n"
    "- stays：若攻略**明确写出**某天/某晚住哪（酒店或民宿名），逐项填 "
    "{day, city 过夜城市, hotel 酒店名, price 每晚价格数字(没写留空), source 来源如「携程」}；"
    "攻略没写已选住宿就留空数组，**不要把多个备选酒店都当成已预订住宿**。"
)

_IMPORT_DAY_RE = re.compile(
    r"(?im)^(?:#{1,6}\s*)?(?:\*{0,2})?Day\s*(\d{1,2})"
    r"(?:\s*[-–—~至]\s*(?:Day\s*)?(\d{1,2}))?[^\n]*"
)
_IMPORT_GLOBAL_SECTION_RE = re.compile(
    r"(?im)^#{1,3}\s*(?:⚠️\s*)?"
    r"(?:必吃|美食清单|住宿推荐|酒店推荐|预算|费用|需按日期|避坑|参考来源)"
)


def _detected_guide_days(guide_md: str) -> int:
    """从 Day 标题确定攻略最大天数，完全不依赖 LLM。"""
    found = [
        max(int(m.group(1)), int(m.group(2) or m.group(1)))
        for m in _IMPORT_DAY_RE.finditer(guide_md)
    ]
    return _clamp_trip_days(max(found)) if found else 0


def _guide_day_titles(guide_md: str) -> dict[int, str]:
    """从原攻略保留 Day 标题，防止模型把每天标题统一改成目的地。"""
    titles: dict[int, str] = {}
    for match in _IMPORT_DAY_RE.finditer(guide_md):
        lo = int(match.group(1))
        hi = int(match.group(2) or lo)
        line = match.group(0).strip()
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = line.strip(" *\t\r\n")
        if not line:
            continue
        for day in range(min(lo, hi), max(lo, hi) + 1):
            titles.setdefault(day, line[:200])
    return titles


def _guide_summary_excerpt(guide_md: str) -> str:
    """全局抽取保留标题、Day 索引和尾部住宿/预算，避免把 2 万字全塞给模型。"""
    if len(guide_md) <= 14000:
        return guide_md
    headings = "\n".join(m.group(0).strip() for m in _IMPORT_DAY_RE.finditer(guide_md))
    return (
        f"{guide_md[:3500]}\n\n"
        f"[全部 Day 标题]\n{headings}\n\n"
        f"[攻略结尾（住宿、预算、提醒通常位于此处）]\n{guide_md[-8500:]}"
    )


def _split_guide_day_chunks(guide_md: str) -> list[tuple[int, int, str]]:
    """按 Day 标题切成每个 Day 一块，返回 (起始日, 结束日, Markdown)。"""
    matches = list(_IMPORT_DAY_RE.finditer(guide_md))
    if not matches:
        return [(1, MAX_TRIP_DAYS, guide_md[:10000])]
    sections: list[tuple[int, int, str]] = []
    for i, match in enumerate(matches):
        start = int(match.group(1))
        end = int(match.group(2) or start)
        lo, hi = min(start, end), max(start, end)
        next_pos = matches[i + 1].start() if i + 1 < len(matches) else len(guide_md)
        section_text = guide_md[match.start():next_pos]
        # 最后一个 Day 后常紧跟全局美食/酒店/预算/来源章节；这些由 summary 单独抽取，
        # 留在逐日块会被误当成大量 stops，导致 JSON 再次超限。
        global_match = _IMPORT_GLOBAL_SECTION_RE.search(section_text)
        if global_match:
            section_text = section_text[:global_match.start()]
        sections.append((lo, hi, section_text))

    chunks: list[tuple[int, int, str]] = []
    group: list[tuple[int, int, str]] = []
    covered = 0
    chars = 0
    for section in sections:
        span = section[1] - section[0] + 1
        if group and (covered + span > IMPORT_DAYS_PER_CHUNK or chars + len(section[2]) > 10000):
            chunks.append((
                min(x[0] for x in group),
                max(x[1] for x in group),
                "\n\n".join(x[2] for x in group)[:10000],
            ))
            group, covered, chars = [], 0, 0
        group.append(section)
        covered += span
        chars += len(section[2])
    if group:
        chunks.append((
            min(x[0] for x in group),
            max(x[1] for x in group),
            "\n\n".join(x[2] for x in group)[:10000],
        ))
    return chunks


async def _extract_import_draft(
    llm, guide_md: str, only_days: set[int] | None = None, on_progress=None,
):
    """全局信息 + 逐日小块并发抽取，合并为现有 TripDraft。

    2026-07-31 可靠性重构（用户实测：6 天攻略连续两次导入失败）：
    - **部分成功必须留下**：原来用 `asyncio.gather` 快速失败，一天炸掉，其余已解析好的
      天全部丢弃；现在 `return_exceptions=True`，失败的天记进 `draft.failed_days`。
    - `only_days` 非空时只解析这些天（失败重试用，不重跑已成功的天）。
    - `on_progress(done, total)` 逐天回调，让板上能显示「已完成 3/6 天」而不是干等。
    """
    from app.agent.trip_planner import (
        DraftDayPlan, TripDraft, TripImportDays, TripImportSummary,
    )

    detected_days = _detected_guide_days(guide_md)
    summary = await asyncio.to_thread(
        llm.parse,
        f"攻略摘要材料：\n{_guide_summary_excerpt(guide_md)}",
        TripImportSummary,
        system=IMPORT_SUMMARY_SYSTEM,
        # summary 现在还带美食/避坑清单，4000 会被截断（实测），提到 8000
        max_tokens=8000,
    )
    total_days = _clamp_trip_days(max(detected_days, summary.days))
    chunks = [
        c for c in _split_guide_day_chunks(guide_md)
        if only_days is None or any(d in only_days for d in range(c[0], c[1] + 1))
    ]
    sem = asyncio.Semaphore(4)
    done = 0
    total_chunks = len(chunks)

    async def extract_chunk(lo: int, hi: int, text: str):
        nonlocal done
        async with sem:
            try:
                parsed = await asyncio.to_thread(
                    llm.parse,
                    f"本段只允许提取 Day {lo}–{hi}：\n{text}",
                    TripImportDays,
                    model=settings.model_classifier,
                    system=IMPORT_DAYS_SYSTEM,
                    max_tokens=settings.trip_import_chunk_max_tokens,
                )
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"Day {lo}–{hi} 分段抽取失败：{exc}") from exc
            finally:
                done += 1
                if on_progress is not None:
                    try:
                        on_progress(done, total_chunks)
                    except Exception:  # noqa: BLE001 — 进度回调绝不能影响抽取
                        pass
            return lo, hi, parsed

    results = await asyncio.gather(
        *(extract_chunk(*chunk) for chunk in chunks), return_exceptions=True
    )
    failed_days: list[int] = []
    parsed_chunks = []
    for chunk, res in zip(chunks, results):
        if isinstance(res, BaseException):
            failed_days.extend(range(chunk[0], chunk[1] + 1))
            logger.warning("import chunk Day %s-%s failed: %s", chunk[0], chunk[1], res)
            continue
        parsed_chunks.append(res)
    stops, stays, day_plans = [], [], []
    for lo, hi, parsed in parsed_chunks:
        stops.extend(s for s in parsed.stops if lo <= s.day <= hi and s.day <= total_days)
        stays.extend(s for s in parsed.stays if lo <= s.day <= hi and s.day <= total_days)
        day_plans.extend(p for p in parsed.day_plans if lo <= p.day <= hi and p.day <= total_days)

    # 分块边界或模型重复时，以 (day, name/hotel) 去重；day_plan 每天只保留一条。
    unique_stops = list({(s.day, s.name.strip()): s for s in stops if s.name.strip()}.values())
    unique_stays = list({
        (s.day, (s.hotel or s.city).strip()): s
        for s in stays if (s.hotel or s.city).strip()
    }.values())
    plans_by_day = {p.day: p for p in day_plans}
    for day, title in _guide_day_titles(guide_md).items():
        if day > total_days:
            continue
        if day in plans_by_day:
            plans_by_day[day].day_title = title
        else:
            plans_by_day[day] = DraftDayPlan(day=day, type="stay", day_title=title)
    unique_plans = list(plans_by_day.values())
    return TripDraft(
        title=summary.title,
        destination=summary.destination,
        days=total_days,
        stops=sorted(unique_stops, key=lambda x: x.day),
        stays=sorted(unique_stays, key=lambda x: x.day),
        day_plans=sorted(unique_plans, key=lambda x: x.day),
        hotel_options=summary.hotel_options,
        budget_items=summary.budget_items,
        foods=summary.foods,
        tips=summary.tips,
        failed_days=sorted(set(failed_days)),
    )


async def _geocode_with_cooldown(names: list[str], city: str, geocode_fn) -> dict[str, str]:
    """大批量导入首轮遇到共享 QPS 限流时，冷却后只重试缺失项。"""
    result = await geocode_fn(names, city)
    missing = [n for n in dict.fromkeys(names) if n and n not in result]
    if missing:
        await asyncio.sleep(2)
        result.update(await geocode_fn(missing, city))
    return result


def _day_city_hints(day_plans, total_days: int) -> dict[int, str]:
    """逐日过夜城市转 POI 检索城市；返程/火车过夜日沿用最近的有效城市。"""
    explicit = {
        p.day: (p.overnight_city or "").strip()
        for p in day_plans if 1 <= p.day <= total_days and (p.overnight_city or "").strip()
    }
    hints: dict[int, str] = {}
    for day in range(1, total_days + 1):
        if day in explicit:
            hints[day] = explicit[day]
            continue
        previous = next((explicit[d] for d in range(day - 1, 0, -1) if d in explicit), "")
        following = next((explicit[d] for d in range(day + 1, total_days + 1) if d in explicit), "")
        hints[day] = previous or following
    return hints


async def _geocode_stops_by_city(stops, day_plans, destination: str, geocode_fn):
    """多城市长行程先按当天城市查，未命中再在本行程其他城市受限重试。"""
    from app.agent.site_router import split_cities

    total_days = max([s.day for s in stops] + [p.day for p in day_plans] + [1])
    hints = _day_city_hints(day_plans, total_days)
    dest_cities = split_cities(destination)
    # 2026-08-01 线上事故：六安一日游（当晚坐高铁到武汉过夜）的 day_plan 里
    # overnight_city=武汉，于是当天**六安的景点**全按武汉查——「中央公园」匹配到了
    # 汉阳中央公园（行政区校验还通过了，因为武汉真有同名公园），另外三个六安地点查不到，
    # 地图整体飘到武汉、路线画不出来。
    # overnight_city 表达的是「当晚睡哪」，中途停留/转移日里它是**到达城**，
    # 不能用来查当天的景点。单城行程直接以行程目的地为准。
    if _is_single_city(destination, dest_cities):
        hints = {day: dest_cities[0] for day in range(1, total_days + 1)}
    groups: dict[str, list] = {}
    for stop in stops:
        # 非地点类事件（起床/早餐/退房等）不参与 geocode，避免无谓的查询+冷却重试拖慢导入
        if not getattr(stop, "is_place", True):
            continue
        groups.setdefault(hints.get(stop.day) or destination, []).append(stop)
    sem = asyncio.Semaphore(4)

    async def one(city: str, grouped_stops):
        query_of = {
            id(stop): ((getattr(stop, "search_name", "") or "").strip() or stop.name)
            for stop in grouped_stops
        }
        async with sem:
            found = await _geocode_with_cooldown(
                [query_of[id(s)] for s in grouped_stops], city, geocode_fn,
            )
        return {
            (s.day, s.name): found[query_of[id(s)]]
            for s in grouped_stops if query_of[id(s)] in found
        }

    resolved: dict[tuple[int, str], str] = {}
    for chunk in await asyncio.gather(*(one(city, rows) for city, rows in groups.items())):
        resolved.update(chunk)

    # 转移日常同时包含出发城和到达城；overnight_city 只能代表到达城，不能让上午地点失联。
    # dest_cities 必须在候选里：原来只用 hints + groups，六安那次 hints 全是「武汉」，
    # 于是重试也只在武汉里打转，行程自己的目的地反而从没被试过。
    route_cities = list(dict.fromkeys(
        [hints[day] for day in sorted(hints) if hints.get(day)]
        + list(groups)
        + dest_cities
        + [p.overnight_city.strip() for p in day_plans if (p.overnight_city or "").strip()]
    ))
    for city in route_cities:
        pending = [
            stop for stop in stops
            if (stop.day, stop.name) not in resolved
            and (hints.get(stop.day) or destination) != city
        ]
        if not pending:
            continue
        query_of = {
            id(stop): ((getattr(stop, "search_name", "") or "").strip() or stop.name)
            for stop in pending
        }
        try:
            found = await geocode_fn([query_of[id(stop)] for stop in pending], city)
        except Exception:  # noqa: BLE001
            found = {}
        for stop in pending:
            query = query_of[id(stop)]
            if query in found:
                resolved[(stop.day, stop.name)] = found[query]
    return resolved


@router.post("/import")
def import_from_chat(body: ImportBody, background: BackgroundTasks,
                     db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """把主对话里的攻略消息一键导入为协同行程（后台 LLM 提取 + 补坐标 + 串路线）。"""
    from app.db.models import TravelConversation, TravelMessage

    conv = db.get(TravelConversation, body.conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "会话不存在")
    msg = db.get(TravelMessage, body.message_id)
    if msg is None or msg.conversation_id != conv.id or msg.role != "assistant" or not (msg.content or "").strip():
        raise HTTPException(400, "该消息不是可导入的攻略")

    # 幂等（2026-07-31）：同一条攻略消息对同一用户永远只有一条行程。
    # 此前每次 POST 都新建，用户在失败后点「重试」就多一条 6 天 0 地点的空行程。
    # 2026-08：修复删除后无法重新导入的问题 - 使用 db.get() 确保对象存在
    existing_id = db.execute(
        select(TravelTrip.id).where(
            TravelTrip.owner_id == user.id, TravelTrip.source_message_id == msg.id
        ).order_by(TravelTrip.created_at.desc()).limit(1)
    ).scalar_one_or_none()

    existing = None
    if existing_id:
        existing = db.get(TravelTrip, existing_id)

    if existing is not None:
        if existing.ai_status in ("failed", "partial"):  # 失败的草稿 → 原地重跑，不新建
            existing.ai_status = "seeding"
            existing.ai_review = "正在重新解析攻略…"
            db.commit()
            background.add_task(_run_import, existing.id, msg.content)
        return {"id": existing.id, "reused": True}

    detected_days = _detected_guide_days(msg.content)
    trip = TravelTrip(owner_id=user.id, title=(conv.title or "导入的行程")[:200],
                      destination="", days=detected_days or 2, ai_status="seeding",
                      ai_review=(f"正在分段解析 {detected_days} 天攻略…"
                                 if detected_days else "正在解析攻略…"),
                      source_conversation_id=conv.id, source_message_id=msg.id)  # Phase 36 联动
    db.add(trip)
    db.flush()
    db.add(TravelTripMember(trip_id=trip.id, user_id=user.id, role="owner", status="accepted"))
    # 对话侧联动：来源消息标记已导入（前端据此把「导入」按钮换成「打开协同行程」）
    import json as _json

    meta = {}
    if msg.meta_json:
        try:
            meta = _json.loads(msg.meta_json)
        except ValueError:
            meta = {}
    meta["imported_trip_id"] = trip.id
    msg.meta_json = _json.dumps(meta, ensure_ascii=False)
    db.commit()
    background.add_task(_run_import, trip.id, msg.content)
    return {"id": trip.id}


def _draft_from_ontology(trip_id: str, guide_md: str):
    """本体快路径（Phase 86）：这条攻略已经有对象图就直接投影成 TripDraft，跳过整段 LLM 抽取。

    只用**已缓存**的对象图，不在这里触发抽取——下面 `_extract_import_draft` 那条路更成熟
    （逐天进度回调、按天重试 `only_days`、分块并发），没缓存时应当走它而不是被这里取代。
    有缓存时（用户先点过手账海报或预算明细）导入几乎瞬时完成，且与那两个面板同源。

    任何异常都返回 None 退回原路径——导入是用户已经等着的操作，不能因为快路径出问题就失败。
    """
    from app.config import settings

    if not settings.ontology_enabled:
        return None
    try:
        with get_session() as db:
            trip = db.get(TravelTrip, trip_id)
            msg_id = trip.source_message_id if trip else None
        if not msg_id:
            return None

        from app.ontology.extract import IMPORT_LANES
        from app.ontology.projections import to_trip_draft
        from app.ontology.store import load_trip_object

        obj = load_trip_object(msg_id, guide_md)
        # failed_days 非空 = 对象图本身就是部分成功的，别把缺口带进行程板；
        # 三路没齐（用户只点过海报，cost 还没抽）也退回原路径——导入要预算拆分。
        if obj is None or not obj.stops or obj.failed_days:
            return None
        if not set(IMPORT_LANES) <= set(obj.lanes):
            return None
        draft = to_trip_draft(obj)
        draft.days = _clamp_trip_days(max(_detected_guide_days(guide_md), draft.days))
        draft.stops = [s for s in draft.stops if s.day <= draft.days]
        draft.stays = [s for s in draft.stays if s.day <= draft.days]
        draft.day_plans = [p for p in draft.day_plans if p.day <= draft.days]
        return draft if draft.stops else None
    except Exception:  # noqa: BLE001
        logger.warning("ontology import fast path failed trip=%s", trip_id, exc_info=True)
        return None


def _run_import(trip_id: str, guide_md: str, only_days: set[int] | None = None) -> None:
    """后台：攻略 Markdown → TripDraft → 补坐标 → 串路线 → 落条目（复用起草的落库逻辑）。

    Phase 51：额外抽住宿（落 🏨 stop 进住宿面板）+ 预算拆分（落 budget_breakdown_json）。
    2026-07-31：`only_days` 非空 = 只重跑这些天（失败重试），已成功的天原样保留。
    """
    import json as _json

    from app.agent.trip_planner import geocode_names, normalize_budget_category
    from app.llm.client import get_llm

    def _progress(done: int, total: int) -> None:
        """逐天写真实进度——原来只有一句「正在分段解析 6 天攻略」，等两分钟都不知道到哪了。"""
        try:
            with get_session() as db:
                t = db.get(TravelTrip, trip_id)
                if t is not None and t.ai_status == "seeding":
                    t.ai_review = f"正在解析攻略：已完成 {done}/{total} 天…"
                    db.commit()
        except Exception:  # noqa: BLE001
            logger.warning("import progress update failed", exc_info=True)

    async def _go():
        # only_days 非空 = 按天重试，必须走原路径（对象图是整份的，没有「只重跑某几天」语义）
        draft = None if only_days else _draft_from_ontology(trip_id, guide_md)
        if draft is None:
            draft = await _extract_import_draft(
                get_llm(), guide_md, only_days=only_days, on_progress=_progress,
            )
        located = await _geocode_stops_by_city(
            draft.stops, draft.day_plans, draft.destination, geocode_names,
        )
        # 住宿：按「城市」geocode（拿到城市中心坐标即可，用于住宿面板/地图）
        stay_cities = list(dict.fromkeys(s.city.strip() for s in draft.stays if s.city.strip()))
        stay_loc: dict[str, str] = {}
        # 多城海外行程不能用整个 destination 约束所有住宿；每个住宿城市解析自己的中心点。
        for city in stay_cities:
            stay_loc.update(await _geocode_with_cooldown([city], city, geocode_names))
        return draft, located, stay_loc

    try:
        draft, located, stay_loc = asyncio.run(_go())
        with get_session() as db:
            trip = db.get(TravelTrip, trip_id)
            if trip is None:
                return
            if only_days:  # 重试：先清掉这几天的旧条目，避免与新解析结果重复
                for old in db.execute(
                    select(TravelTripStop).where(
                        TravelTripStop.trip_id == trip_id, TravelTripStop.day.in_(only_days)
                    )
                ).scalars().all():
                    db.delete(old)
            # 先建原始 rows（保留模型给的天内相对顺序作为无时间项的兜底次序）
            raw_rows = [{"day": s.day, "name": s.name,
                         "note": s.note, "location": located.get((s.day, s.name), ""),
                         "transport": s.transport, "start_time": s.start_time,
                         "stay_min": s.stay_min}
                        for s in draft.stops]

            # 按天分组，天内按 start_time 排序（用户要求「按时间段顺序」）：
            # 有时间的按 HH:MM 升序在前，无时间的保持模型原始相对顺序排在后面；
            # order_no 每天从 0 连续重编，避免重试导致的跨天 order_no 错乱。
            def _clock_key(t: str) -> int:
                m = re.match(r"^\s*(\d{1,2})[:：](\d{2})", t or "")
                return int(m.group(1)) * 60 + int(m.group(2)) if m else 10**9

            optimized: list[dict] = []
            by_day: dict[int, list[dict]] = {}
            for r in raw_rows:
                by_day.setdefault(r["day"], []).append(r)
            for day in sorted(by_day):
                # 稳定排序：有时间的按时间；无时间的 key 相同，保持原始相对顺序落在末尾
                day_rows = sorted(by_day[day], key=lambda r: _clock_key(r["start_time"]))
                for idx, r in enumerate(day_rows):
                    r["id"] = f"tmp{day}_{idx}"
                    r["order_no"] = idx
                    optimized.append(r)

            for r in optimized:
                db.add(TravelTripStop(trip_id=trip_id, day=r["day"], order_no=r["order_no"],
                                      name=r["name"], note=r["note"] or None,
                                      location=r["location"] or None,
                                      transport=(r.get("transport") or "")[:16] or None,
                                      start_time=r.get("start_time") or None,
                                      stay_min=r.get("stay_min")))
            # 住宿 → 🏨 stop（排当天景点之后 order_no=90+，住宿面板 isStay 识别）
            for s in draft.stays:
                hotel = (s.hotel or s.city or "").strip()
                if not hotel:
                    continue
                note_bits = ["住宿"]
                if s.source.strip():
                    note_bits.append(s.source.strip())
                db.add(TravelTripStop(
                    trip_id=trip_id, day=s.day, order_no=90,
                    name=f"🏨 {hotel}"[:128], note=" · ".join(note_bits),
                    location=stay_loc.get(s.city, "") or None,
                    ticket_price=s.price if (s.price and s.price > 0) else None,
                ))
            # 预算拆分 → 归一聚合 → budget_breakdown_json；总额未设则填聚合总额
            breakdown: dict[str, float] = {}
            for it in draft.budget_items:
                if it.amount and it.amount > 0:
                    cat = normalize_budget_category(it.category)
                    breakdown[cat] = round(breakdown.get(cat, 0.0) + it.amount, 2)
            if breakdown:
                trip.budget_breakdown_json = _json.dumps(breakdown, ensure_ascii=False)
                if not trip.budget:
                    trip.budget = round(sum(breakdown.values()), 2)
            # 逐日性质/过夜城市：只保留合法天数和类型；缺天由 day-cities 旧逻辑兜底。
            n_days = _clamp_trip_days(draft.days)
            day_plans: list[dict] = []
            day_titles: dict[str, str] = {}
            seen_days: set[int] = set()
            for p in sorted(draft.day_plans, key=lambda x: x.day):
                if p.day in seen_days or not (1 <= p.day <= n_days):
                    continue
                seen_days.add(p.day)
                ptype = p.type if p.type in ("stay", "transit", "return") else "stay"
                day_plans.append({
                    "day": p.day, "type": ptype,
                    "overnight_required": bool(p.overnight_required),
                    "overnight_city": (p.overnight_city or "").strip()[:60],
                })
                # 保存每天的标题
                if p.day_title and p.day_title.strip():
                    day_titles[str(p.day)] = p.day_title.strip()[:200]
            if day_plans:
                trip.day_plan_json = _json.dumps(day_plans, ensure_ascii=False)
            if day_titles:
                trip.day_titles_json = _json.dumps(day_titles, ensure_ascii=False)
            hotels: list[dict] = []
            seen_hotels: set[str] = set()
            for h in draft.hotel_options:
                name = (h.hotel or "").strip()
                if not name or name in seen_hotels:
                    continue
                seen_hotels.add(name)
                hotels.append({
                    "city": (h.city or draft.destination or "").strip()[:60],
                    "hotel": name[:128],
                    "price": h.price if h.price and h.price > 0 else None,
                    "source": (h.source or "").strip()[:80],
                    "note": (h.note or "").strip()[:250],
                })
            if hotels:
                trip.hotel_recommendations_json = _json.dumps(hotels, ensure_ascii=False)

            # 美食清单导入
            from app.db.models import TravelTripFood
            db.query(TravelTripFood).filter_by(trip_id=trip_id).delete()
            for food in draft.foods:
                name = (food.name or "").strip()
                if not name:
                    continue
                category = food.category if food.category in ("小吃", "正餐", "甜点") else "正餐"
                db.add(TravelTripFood(
                    trip_id=trip_id,
                    name=name[:128],
                    category=category,
                    city=(food.city or draft.destination or "").strip()[:64],
                    price=food.price if food.price and food.price > 0 else None,
                    note=(food.note or "").strip()[:200],
                    created_by="import",
                ))

            # 避坑贴士导入
            from app.db.models import TravelTripTip
            db.query(TravelTripTip).filter_by(trip_id=trip_id).delete()
            for tip in draft.tips:
                content = (tip.content or "").strip()
                if not content:
                    continue
                level = tip.level if tip.level in ("important", "notice") else "notice"
                db.add(TravelTripTip(
                    trip_id=trip_id,
                    level=level,
                    content=content[:300],
                    created_by="import",
                ))

            trip.title = draft.title[:200] or trip.title
            # destination/title 来自 summary 那一步，它跟逐天抽取是独立的——哪怕有天失败
            # 也要落盘，否则板上显示「未定目的地」（线上真实反馈：大理、丽江都识别不出来）
            trip.destination = draft.destination[:60] or trip.destination
            trip.days = n_days
            # 失败的天并进已有的失败集合（重试成功的天要从里面摘掉）
            still_failed = sorted(set(draft.failed_days) | (_failed_days_of(trip) - (only_days or set())))
            if still_failed:
                trip.ai_status = "partial"
                trip.ai_review = (
                    f"部分导入成功：第 {_fmt_days(still_failed)} 天解析失败"
                    f"（其余 {n_days - len(still_failed)} 天已导入）。"
                    "可以点「继续重试」只重跑这几天，或删除这份草稿重来。"
                )
            else:
                trip.ai_status = None
                trip.ai_review = ""
            from app.db.models import _now

            trip.updated_at = _now()
            db.commit()
    except Exception as exc:  # noqa: BLE001
        # 走到这里说明是整体性失败（summary 抽取/地理编码炸了），逐天失败不会到这
        logger.warning("trip import failed for %s", trip_id, exc_info=True)
        detail = str(exc)
        review = (
            ("导入失败：攻略结构化解析没能完成（模型输出被截断）。"
             if ("截断" in detail or "EOF" in detail or "结构化输出" in detail)
             else "导入失败，请稍后重试。")
            + "可以点「继续重试」，或删除这份草稿。"
        )
        # 把状态落成 failed；数据库可能暂时断连（隧道重连中），重试几次避免永远卡在 seeding
        for attempt in range(3):
            try:
                with get_session() as db:
                    trip = db.get(TravelTrip, trip_id)
                    if trip is not None:
                        trip.ai_status = "failed"
                        trip.ai_review = review
                        db.commit()
                break
            except Exception:  # noqa: BLE001
                logger.warning("mark trip failed retry %d for %s", attempt + 1, trip_id, exc_info=True)
                time.sleep(3)


@router.post("/{trip_id}/import/retry")
def retry_import(trip_id: str, background: BackgroundTasks,
                 db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """只重跑解析失败的那几天（2026-07-31）。

    此前失败后唯一的「重试」路径是回对话再点一次导入 —— 那会**新建**一条行程，
    于是账号里堆出多条 6 天 0 地点的空行程。这里在原行程上原地重试，天然幂等。
    """
    from app.db.models import TravelMessage

    trip = _member(db, trip_id, user)
    if trip.owner_id != user.id:
        raise HTTPException(403, "只有创建者能重试导入")
    if trip.ai_status not in ("failed", "partial"):
        raise HTTPException(400, "这份行程没有需要重试的导入任务")
    msg = db.get(TravelMessage, trip.source_message_id) if trip.source_message_id else None
    if msg is None or not (msg.content or "").strip():
        raise HTTPException(400, "找不到原始攻略内容，无法重试")

    only_days = _failed_days_of(trip) or None  # failed 状态没有逐天信息 → 整篇重跑
    trip.ai_status = "seeding"
    trip.ai_review = (
        f"正在重试第 {_fmt_days(sorted(only_days))} 天…" if only_days else "正在重新解析攻略…"
    )
    db.commit()
    background.add_task(_run_import, trip.id, msg.content, only_days)
    return {"ok": True, "retry_days": sorted(only_days) if only_days else []}


def _failed_days_of(trip) -> set[int]:
    """从 ai_review 文案里回读上次失败的天（无独立字段时的轻量做法）。"""
    if trip.ai_status != "partial" or not trip.ai_review:
        return set()
    m = re.search(r"第 ([\d、]+) 天解析失败", trip.ai_review)
    return {int(x) for x in m.group(1).split("、") if x.isdigit()} if m else set()


def _fmt_days(days: list[int]) -> str:
    return "、".join(str(d) for d in days)


# ---------- Phase 36：行程属性编辑 + 检查中心 ----------

class TripPatch(BaseModel):
    title: str | None = None
    destination: str | None = None
    days: int | None = None
    budget: float | None = None
    start_date: str | None = None  # "YYYY-MM-DD"，空串=清除
    day_titles: dict[str, str] | None = None  # {"1": "南京-吉隆坡", "2": "吉隆坡-仙本那"}


@router.patch("/{trip_id}")
def patch_trip(trip_id: str, body: TripPatch,
               db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    if body.title is not None and body.title.strip():
        trip.title = body.title.strip()[:200]
    if body.destination is not None:
        trip.destination = body.destination.strip()[:60]
    if body.days is not None:
        trip.days = _clamp_trip_days(body.days)
    if body.budget is not None:
        trip.budget = body.budget if body.budget > 0 else None
        # 清零预算时必须一并清掉按类别拆分——否则「总预算未设置」下面还挂着一串
        # 类别金额和合计，用户以为没清干净（线上反馈）。
        if trip.budget is None:
            trip.budget_breakdown_json = None
    if body.start_date is not None:
        trip.start_date = body.start_date.strip()[:10] or None
    if body.day_titles is not None:
        import json as _json
        trip.day_titles_json = _json.dumps(body.day_titles, ensure_ascii=False)
    _touch(db, trip)
    db.commit()
    return {"ok": True}


@router.get("/{trip_id}/issues")
async def trip_issues(trip_id: str, db: Session = Depends(get_db),
                      user: TravelUser = Depends(get_current_user)):
    """检查中心（Phase 36）：纯算法即时计算（几何/时间/预算），设了出发日期再查一次天气。"""
    trip = _member(db, trip_id, user)
    stops = [_stop_dict(s) for s in db.execute(
        select(TravelTripStop).where(TravelTripStop.trip_id == trip_id)
    ).scalars()]
    from app.agent.trip_planner import build_issues, is_lodging_stop

    forecast: list[dict] = []
    if trip.start_date and trip.destination:
        try:
            from app.tools.amap import weather_forecast

            forecast = await weather_forecast(trip.destination)
        except Exception:  # noqa: BLE001 — 天气拿不到就跳过该类检查
            logger.warning("weather forecast failed", exc_info=True)
    # Phase 54.1：把攻略导入的逐日计划一并喂给检查中心，日分类与「每晚住哪」一致
    day_plans = _load_day_plans(trip)
    return {"issues": build_issues(
        stops, budget=trip.budget, start_date=trip.start_date, forecast=forecast,
        total_days=trip.days, day_plans=day_plans,
    ), "ticket_total": sum(float(s.get("ticket_price") or 0) for s in stops if not is_lodging_stop(s))}


# ---------- Phase 37：Copilot 提案 ----------

class CopilotBody(BaseModel):
    prompt: str


def _suggestion_dict(sg: TravelTripSuggestion) -> dict:
    import json as _json

    return {"id": sg.id, "prompt": sg.prompt, "reply": sg.reply, "status": sg.status,
            "changes": _json.loads(sg.diff_json) if sg.diff_json else [],
            "created_at": sg.created_at.isoformat() if sg.created_at else ""}


@router.post("/{trip_id}/ai/copilot")
def ai_copilot(trip_id: str, body: CopilotBody, background: BackgroundTasks,
               db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    if trip.ai_status in ("seeding", "reviewing", "copilot"):
        raise HTTPException(409, "AI 正在处理中")
    if not body.prompt.strip():
        raise HTTPException(400, "指令不能为空")
    trip.ai_status = "copilot"
    db.commit()
    background.add_task(_run_copilot_task, trip_id, user.id, body.prompt.strip())
    return {"ok": True}


def _run_copilot_task(trip_id: str, user_id: str, prompt: str) -> None:
    import json as _json

    from app.agent.trip_planner import run_copilot, trip_json_for_llm
    from app.llm.client import get_llm

    try:
        with get_session() as db:
            trip = db.get(TravelTrip, trip_id)
            if trip is None:
                return
            stops = [_stop_dict(s) for s in db.execute(
                select(TravelTripStop).where(TravelTripStop.trip_id == trip_id)
            ).scalars()]
            snapshot = trip_json_for_llm(trip.title, trip.destination, trip.days, trip.budget, stops)
        result = asyncio.run(run_copilot(get_llm(), snapshot, prompt))
        # 上限放宽到 40：结构性大改（如 15 天缩短到 7 天）本就需要多条增删，8 条会截断成半成品
        changes = [c.model_dump() for c in result.changes][:40]
        with get_session() as db:
            trip = db.get(TravelTrip, trip_id)
            if trip is None:
                return
            db.add(TravelTripSuggestion(
                trip_id=trip_id, user_id=user_id, prompt=prompt,
                reply=(result.reply or "").strip()[:2000],
                diff_json=_json.dumps(changes, ensure_ascii=False) if changes else None,
                status="pending" if changes else "answered",
            ))
            trip.ai_status = None
            from app.db.models import _now

            trip.updated_at = _now()
            db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("copilot failed for %s", trip_id, exc_info=True)
        # 优雅降级：解析失败（常见于把「整体重规划」发给增量编辑器 → 输出被截断成非法 JSON）
        # 不留「上次 AI 任务失败」死状态，而是写一条可操作的回复，指引用户拆小指令或回主对话重规划。
        try:
            with get_session() as db:
                trip = db.get(TravelTrip, trip_id)
                if trip is None:
                    return
                db.add(TravelTripSuggestion(
                    trip_id=trip_id, user_id=user_id, prompt=prompt,
                    reply="这次的改动太大或太复杂，我没能把它整理成可一键套用的结构化改动。"
                          "可以把指令拆小一点分步来（比如「Day2 减少步行」「把纳木错单独放一天」），"
                          "或回主对话让我重新生成完整攻略后再导入协同板。",
                    status="answered",
                ))
                trip.ai_status = None
                from app.db.models import _now

                trip.updated_at = _now()
                db.commit()
        except Exception:  # noqa: BLE001 — 连降级消息都写不进去，才回落失败状态
            logger.error("copilot graceful fallback failed for %s", trip_id, exc_info=True)
            with get_session() as db:
                trip = db.get(TravelTrip, trip_id)
                if trip is not None:
                    trip.ai_status = "failed"
                    db.commit()


@router.get("/{trip_id}/suggestions")
def list_suggestions(trip_id: str, db: Session = Depends(get_db),
                     user: TravelUser = Depends(get_current_user)):
    _member(db, trip_id, user)
    rows = db.execute(
        select(TravelTripSuggestion).where(TravelTripSuggestion.trip_id == trip_id)
        .order_by(TravelTripSuggestion.created_at.desc()).limit(20)
    ).scalars().all()
    return [_suggestion_dict(r) for r in rows]


@router.post("/{trip_id}/suggestions/{sid}/apply")
async def apply_suggestion(trip_id: str, sid: str, db: Session = Depends(get_db),
                           user: TravelUser = Depends(get_current_user)):
    """采纳提案：先存快照（回滚依据），add 自动补坐标，逐条应用。"""
    import json as _json

    trip = _member(db, trip_id, user)
    sg = db.get(TravelTripSuggestion, sid)
    if sg is None or sg.trip_id != trip_id or sg.status != "pending":
        raise HTTPException(404, "提案不存在或已处理")
    changes = _json.loads(sg.diff_json or "[]")
    stops = {s.id: s for s in db.execute(
        select(TravelTripStop).where(TravelTripStop.trip_id == trip_id)
    ).scalars()}
    sg.snapshot_json = _json.dumps([_stop_dict(s) for s in stops.values()], ensure_ascii=False)

    from app.agent.trip_planner import geocode_names

    add_names = [c["name"] for c in changes if c.get("op") == "add" and c.get("name")]
    located: dict[str, str] = {}
    if add_names:
        try:
            located = await geocode_names(add_names, trip.destination)
        except Exception:  # noqa: BLE001
            logger.warning("geocode for suggestion failed", exc_info=True)

    max_no = max([s.order_no for s in stops.values()] or [-1])
    for c in changes:
        op = c.get("op")
        if op == "add" and c.get("name"):
            max_no += 1
            db.add(TravelTripStop(
                trip_id=trip_id, day=max(1, int(c.get("day") or 1)), order_no=max_no,
                name=c["name"][:120], note=(c.get("note") or "")[:500] or None,
                location=located.get(c["name"]) or None,
                start_time=(c.get("start_time") or "")[:5] or None,
                stay_min=int(c.get("stay_min") or 0) or None,
                transport=(c.get("transport") or "")[:16] or None,
                ticket_price=float(c.get("ticket_price") or 0) or None,
            ))
        elif op == "update" and c.get("stop_id") in stops:
            st = stops[c["stop_id"]]
            if c.get("name"):
                st.name = c["name"][:120]
            if c.get("note"):
                st.note = c["note"][:500]
            if c.get("day"):
                st.day = max(1, int(c["day"]))
            if c.get("start_time"):
                st.start_time = c["start_time"][:5]
            if c.get("stay_min"):
                st.stay_min = int(c["stay_min"])
            if c.get("transport"):
                st.transport = c["transport"][:16]
            if c.get("ticket_price"):
                st.ticket_price = float(c["ticket_price"])
        elif op == "delete" and c.get("stop_id") in stops:
            db.delete(stops[c["stop_id"]])
    sg.status = "applied"
    _log_event(db, trip_id, user, f"采纳了 AI 提案（{len(changes)} 处改动）")
    _touch(db, trip)
    db.commit()
    return {"ok": True}


@router.post("/{trip_id}/suggestions/{sid}/reject")
def reject_suggestion(trip_id: str, sid: str, db: Session = Depends(get_db),
                      user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    sg = db.get(TravelTripSuggestion, sid)
    if sg is None or sg.trip_id != trip_id or sg.status != "pending":
        raise HTTPException(404, "提案不存在或已处理")
    sg.status = "rejected"
    _log_event(db, trip_id, user, "拒绝了 AI 提案")
    _touch(db, trip)
    db.commit()
    return {"ok": True}


@router.post("/{trip_id}/suggestions/{sid}/revert")
def revert_suggestion(trip_id: str, sid: str, db: Session = Depends(get_db),
                      user: TravelUser = Depends(get_current_user)):
    """恢复：用 apply 前的快照整体重建条目（轻量 time travel）。"""
    import json as _json

    trip = _member(db, trip_id, user)
    sg = db.get(TravelTripSuggestion, sid)
    if sg is None or sg.trip_id != trip_id or sg.status != "applied" or not sg.snapshot_json:
        raise HTTPException(404, "该提案不可恢复")
    for s in db.execute(select(TravelTripStop).where(TravelTripStop.trip_id == trip_id)).scalars():
        db.delete(s)
    db.flush()
    for r in _json.loads(sg.snapshot_json):
        db.add(TravelTripStop(
            trip_id=trip_id, day=r["day"], order_no=r["order_no"], name=r["name"],
            note=r.get("note") or None, location=r.get("location") or None,
            start_time=r.get("start_time") or None, stay_min=r.get("stay_min"),
            transport=r.get("transport") or None, ticket_price=r.get("ticket_price"),
            tags=",".join(r.get("tags") or []) or None,
        ))
    sg.status = "reverted"
    _log_event(db, trip_id, user, "恢复了 AI 提案前的行程")
    _touch(db, trip)
    db.commit()
    return {"ok": True}


# ---------- Phase 38：评论 + 修改记录 ----------

class CommentBody(BaseModel):
    content: str


@router.get("/{trip_id}/comments")
def list_comments(trip_id: str, db: Session = Depends(get_db),
                  user: TravelUser = Depends(get_current_user)):
    _member(db, trip_id, user)
    rows = db.execute(
        select(TravelTripComment, TravelUser)
        .join(TravelUser, TravelUser.id == TravelTripComment.user_id)
        .where(TravelTripComment.trip_id == trip_id)
        .order_by(TravelTripComment.created_at)
    ).all()
    return [{"id": c.id, "stop_id": c.stop_id, "username": u.username, "content": c.content,
             "mine": c.user_id == user.id,
             "created_at": c.created_at.isoformat() if c.created_at else ""} for c, u in rows]


@router.post("/{trip_id}/stops/{stop_id}/comments")
def add_comment(trip_id: str, stop_id: str, body: CommentBody,
                db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    stop = db.get(TravelTripStop, stop_id)
    if stop is None or stop.trip_id != trip_id:
        raise HTTPException(404, "条目不存在")
    if not body.content.strip():
        raise HTTPException(400, "评论不能为空")
    db.add(TravelTripComment(trip_id=trip_id, stop_id=stop_id, user_id=user.id,
                             content=body.content.strip()[:500]))
    _touch(db, trip)
    db.commit()
    return {"ok": True}


@router.delete("/{trip_id}/comments/{comment_id}")
def delete_comment(trip_id: str, comment_id: str,
                   db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    c = db.get(TravelTripComment, comment_id)
    if c is None or c.trip_id != trip_id:
        raise HTTPException(404, "评论不存在")
    if c.user_id != user.id:
        raise HTTPException(403, "只能删除自己的评论")
    db.delete(c)
    _touch(db, trip)
    db.commit()
    return {"ok": True}


# ---------- Phase 61：行程群聊 ----------

class ChatMessageBody(BaseModel):
    content: str


def _chat_dict(message: TravelTripChatMessage, author: TravelUser, user_id: str) -> dict:
    return {
        "id": message.id,
        "username": author.username,
        "content": message.content,
        "mine": message.user_id == user_id,
        "created_at": message.created_at.isoformat() if message.created_at else "",
    }


@router.get("/{trip_id}/chat")
def list_chat_messages(trip_id: str, after: str = "",
                       db: Session = Depends(get_db),
                       user: TravelUser = Depends(get_current_user)):
    """最近 100 条或指定消息之后的增量。"""
    _member(db, trip_id, user)
    stmt = (
        select(TravelTripChatMessage, TravelUser)
        .join(TravelUser, TravelUser.id == TravelTripChatMessage.user_id)
        .where(TravelTripChatMessage.trip_id == trip_id)
    )
    if after:
        anchor = db.get(TravelTripChatMessage, after)
        if anchor is None or anchor.trip_id != trip_id:
            raise HTTPException(400, "无效的消息游标")
        stmt = stmt.where(or_(
            TravelTripChatMessage.created_at > anchor.created_at,
            and_(
                TravelTripChatMessage.created_at == anchor.created_at,
                TravelTripChatMessage.id > anchor.id,
            ),
        )).order_by(TravelTripChatMessage.created_at, TravelTripChatMessage.id).limit(100)
        rows = db.execute(stmt).all()
    else:
        rows = db.execute(
            stmt.order_by(
                TravelTripChatMessage.created_at.desc(),
                TravelTripChatMessage.id.desc(),
            ).limit(100)
        ).all()
        rows.reverse()
    return [_chat_dict(message, author, user.id) for message, author in rows]


def _chat_dedupe_key(trip_id: str, user_id: str) -> str:
    """(行程, 接收者) 唯一。一个行程刷 20 条消息，每人只有一条通知在刷新，不会冲爆铃铛。"""
    return f"trip-chat:{trip_id}:{user_id}"


def _notify_chat_members(db: Session, trip: TravelTrip, sender: TravelUser, content: str) -> int:
    """给除发送者外的每个 accepted 成员写/刷新一条群聊通知（Phase 97）。返回通知人数。

    **必须与消息写入同事务**（本函数只 flush，由调用方 commit）——消息成功了通知没落，
    或反过来，都比两者一起失败更难查。见 `docs/pitfalls/事件通知必须与业务同事务且按事件去重.md`。
    """
    from app.api.notification_api import upsert_notification

    members = db.execute(
        select(TravelTripMember).where(
            TravelTripMember.trip_id == trip.id,
            TravelTripMember.status == "accepted",
            TravelTripMember.user_id != sender.id,
        )
    ).scalars().all()
    if not members:
        return 0

    actor_name = (sender.display_name or sender.username or "同行者").strip()
    trip_title = (trip.title or "协同行程").strip()
    excerpt = " ".join(content.split())[:80]
    for member in members:
        key = _chat_dedupe_key(trip.id, member.user_id)
        # upsert 会把行覆盖成未读，`meta.count` 因此永远是 1 —— 先读一次才能累计。
        # 已读过的（read_at 非空）说明用户已经看过上一批，这是新一轮未读的开始。
        prev = db.execute(select(TravelNotification).where(
            TravelNotification.dedupe_key == key,
        )).scalar_one_or_none()
        count = 1
        if prev is not None and prev.read_at is None:
            try:
                count = int((json.loads(prev.meta_json or "{}") or {}).get("count", 0)) + 1
            except Exception:  # noqa: BLE001 — meta 脏了不能影响发消息
                count = 1
        upsert_notification(
            db,
            user_id=member.user_id,
            actor_id=sender.id,
            type="trip_chat",
            title=f"{actor_name} 在「{trip_title}」发了消息",
            body=excerpt,
            target_kind="trip",
            target_id=trip.id,
            dedupe_key=key,
            meta={"trip_id": trip.id, "trip_title": trip_title, "count": count},
        )
    return len(members)


@router.post("/{trip_id}/chat")
def add_chat_message(trip_id: str, body: ChatMessageBody,
                     db: Session = Depends(get_db),
                     user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    content = body.content.strip()
    if not content:
        raise HTTPException(400, "消息不能为空")
    message = TravelTripChatMessage(
        trip_id=trip_id,
        user_id=user.id,
        content=content[:1000],
    )
    db.add(message)
    # Phase 97：同事务写通知，让同行者在**主页铃铛**上就能看到，而不是必须进这个页面
    _notify_chat_members(db, trip, user, message.content)
    db.commit()
    db.refresh(message)
    return _chat_dict(message, user, user.id)


@router.post("/{trip_id}/chat/read")
def mark_chat_read(trip_id: str, db: Session = Depends(get_db),
                   user: TravelUser = Depends(get_current_user)):
    """打开群聊时把自己那条群聊通知置为已读（Phase 97）。

    **刻意做成显式端点**而不是在 `GET /chat` 里顺手改状态：前端关着面板时也在轮询
    检查未读，GET 带副作用会让它自己把自己标成已读。
    """
    _member(db, trip_id, user)
    row = db.execute(select(TravelNotification).where(
        TravelNotification.dedupe_key == _chat_dedupe_key(trip_id, user.id),
    )).scalar_one_or_none()
    if row is not None and row.read_at is None:
        from app.db.models import _now

        row.read_at = _now()
        db.commit()
    return {"ok": True}


@router.delete("/{trip_id}/chat/{message_id}")
def delete_chat_message(trip_id: str, message_id: str,
                        db: Session = Depends(get_db),
                        user: TravelUser = Depends(get_current_user)):
    _member(db, trip_id, user)
    message = db.get(TravelTripChatMessage, message_id)
    if message is None or message.trip_id != trip_id:
        raise HTTPException(404, "消息不存在")
    if message.user_id != user.id:
        raise HTTPException(403, "只能删除自己的消息")
    db.delete(message)
    db.commit()
    return {"ok": True}


@router.get("/{trip_id}/events")
def list_events(trip_id: str, db: Session = Depends(get_db),
                user: TravelUser = Depends(get_current_user)):
    _member(db, trip_id, user)
    rows = db.execute(
        select(TravelTripEvent, TravelUser)
        .join(TravelUser, TravelUser.id == TravelTripEvent.user_id)
        .where(TravelTripEvent.trip_id == trip_id)
        .order_by(TravelTripEvent.created_at.desc()).limit(40)
    ).all()
    return [{"username": u.username, "action": e.action,
             "created_at": e.created_at.isoformat() if e.created_at else ""} for e, u in rows]


# ---------- Phase 39：真实交通时间 ----------

@router.get("/{trip_id}/segment-times")
async def segment_times(trip_id: str, day: int = 1,
                        db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """国内返回高德真实路线；海外透明回退为直线距离估算。"""
    trip = _member(db, trip_id, user)
    stops = sorted(
        [_stop_dict(s) for s in db.execute(
            select(TravelTripStop).where(TravelTripStop.trip_id == trip_id, TravelTripStop.day == day)
        ).scalars()],
        key=lambda s: s["order_no"],
    )
    located = [s for s in stops if s["location"]]
    if len(located) < 2:
        return {"segments": []}

    import httpx

    from app.agent.trip_planner import estimate_leg_time, infer_leg_transport
    from app.tools.amap import route_time
    from app.tools.geocode import coordinates_probably_overseas, known_overseas_city

    use_amap_route = not (
        known_overseas_city(_trip_city_for_day(trip, day))
        or coordinates_probably_overseas([s["location"] for s in located])
    )

    sem = asyncio.Semaphore(3)

    async def one(client, a, b):
        mode = infer_leg_transport(a, b)
        r = None
        if use_amap_route:
            async with sem:
                try:
                    r = await route_time(client, a["location"], b["location"], mode)
                except Exception:  # noqa: BLE001
                    r = None
        result = r or estimate_leg_time(a, b, mode)
        return {
            "from_id": a["id"], "to_id": b["id"],
            **(result or {"minutes": None, "km": None, "mode": mode, "estimated": True}),
        }

    async with httpx.AsyncClient(trust_env=False) as client:
        segments = await asyncio.gather(*[one(client, a, b) for a, b in zip(located, located[1:])])
    return {"segments": list(segments)}


# ---------- Phase 40：批量重排（拖拽落点，单请求替代 N 次 PATCH） ----------

class ReorderBody(BaseModel):
    day: int
    ordered_ids: list[str]


@router.post("/{trip_id}/stops/reorder")
def reorder_stops(trip_id: str, body: ReorderBody,
                  db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """把 ordered_ids 里的条目归入 day 并按给定顺序重赋 order_no（拖拽排序落点）。
    不在列表里的其他天条目不受影响；非法/他程 id 忽略。"""
    trip = _member(db, trip_id, user)
    stops = {s.id: s for s in db.execute(
        select(TravelTripStop).where(TravelTripStop.trip_id == trip_id)
    ).scalars()}
    base = max([s.order_no for s in stops.values()] or [0]) + 1  # 避开现有序号区间
    moved = 0
    for i, sid in enumerate(body.ordered_ids):
        s = stops.get(sid)
        if s is None:
            continue
        s.day = _clamp_trip_days(body.day)
        s.order_no = base + i
        moved += 1
    if moved:
        _log_event(db, trip_id, user, f"拖拽调整了 Day{body.day} 的顺序")
        _touch(db, trip)
    db.commit()
    return {"ok": True, "moved": moved}


# ---------- Phase 41：多人记账本 ----------

class ExpenseBody(BaseModel):
    amount: float
    title: str
    category: str = "其他"
    participant_usernames: list[str] = []  # 空 = 全体已接受成员
    payer: str = ""       # 垫付人用户名；空 = 自己（常见的是「帮别人记一笔」）
    spent_at: str = ""    # 花费日期 YYYY-MM-DD；空 = 不填，展示回落记账时间


def _trip_users(db: Session, trip_id: str) -> dict[str, str]:
    """已接受成员 {user_id: username}。"""
    rows = db.execute(
        select(TravelTripMember, TravelUser)
        .join(TravelUser, TravelUser.id == TravelTripMember.user_id)
        .where(TravelTripMember.trip_id == trip_id, TravelTripMember.status == "accepted")
    ).all()
    return {m.user_id: u.username for m, u in rows}


@router.get("/{trip_id}/expenses")
def list_expenses(trip_id: str, db: Session = Depends(get_db),
                  user: TravelUser = Depends(get_current_user)):
    import json as _json

    from app.db.models import TravelTripExpense

    _member(db, trip_id, user)
    users = _trip_users(db, trip_id)
    rows = db.execute(
        select(TravelTripExpense).where(TravelTripExpense.trip_id == trip_id)
        .order_by(TravelTripExpense.created_at.desc())
    ).scalars().all()
    return [{
        "id": e.id, "amount": e.amount, "title": e.title, "category": e.category,
        "payer": users.get(e.payer_user_id, "已退出成员"),
        "participants": [users.get(p, "?") for p in _json.loads(e.participants_json)],
        "mine": e.payer_user_id == user.id,
        "spent_at": e.spent_at or "",
        "created_at": e.created_at.isoformat() if e.created_at else "",
    } for e in rows]


@router.post("/{trip_id}/expenses")
def add_expense(trip_id: str, body: ExpenseBody,
                db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    import json as _json

    from app.agent.trip_planner import EXPENSE_CATEGORIES
    from app.db.models import TravelTripExpense

    trip = _member(db, trip_id, user)
    if body.amount <= 0:
        raise HTTPException(400, "金额必须大于 0")
    if not body.title.strip():
        raise HTTPException(400, "写一下这笔花在哪了")
    users = _trip_users(db, trip_id)
    name_to_id = {v: k for k, v in users.items()}
    if body.participant_usernames:
        participants = [name_to_id[n] for n in body.participant_usernames if n in name_to_id]
        if not participants:
            raise HTTPException(400, "参与人无效")
    else:
        participants = list(users.keys())  # 默认全员分摊
    payer_id = user.id
    if body.payer.strip():
        payer_id = name_to_id.get(body.payer.strip(), "")
        if not payer_id:
            raise HTTPException(400, "垫付人不在本行程里")
    e = TravelTripExpense(
        trip_id=trip_id, payer_user_id=payer_id, amount=round(body.amount, 2),
        spent_at=(body.spent_at or "").strip()[:10],
        title=body.title.strip()[:120],
        category=body.category if body.category in EXPENSE_CATEGORIES else "其他",
        participants_json=_json.dumps(participants), created_by=user.id,
    )
    db.add(e)
    _log_event(db, trip_id, user, f"记了一笔「{e.title}」¥{e.amount:.0f}")
    _touch(db, trip)
    db.commit()
    return {"id": e.id}


@router.delete("/{trip_id}/expenses/{expense_id}")
def delete_expense(trip_id: str, expense_id: str,
                   db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    from app.db.models import TravelTripExpense

    trip = _member(db, trip_id, user)
    e = db.get(TravelTripExpense, expense_id)
    if e is None or e.trip_id != trip_id:
        raise HTTPException(404, "账目不存在")
    # 协同场景：记错的账谁都可能发现，限制成「只能删自己记的」会让错账留在账本上
    # 没人能动（线上反馈）。行程成员本来就能编辑行程本身，账目同理。
    _log_event(db, trip_id, user, f"删除了账目「{e.title}」")
    db.delete(e)
    _touch(db, trip)
    db.commit()
    return {"ok": True}


@router.patch("/{trip_id}/expenses/{expense_id}")
def update_expense(trip_id: str, expense_id: str, body: ExpenseBody,
                   db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """修改一笔账（金额/事项/类别/垫付人/日期/分摊人）。

    与删除同理：**任何成员都能改**。协同记账里记错的账往往是别人先发现的，
    限制成「只能改自己记的」会让错账挂在账本上没人能动。改动落动态时间线。
    """
    import json as _json

    from app.agent.trip_planner import EXPENSE_CATEGORIES
    from app.db.models import TravelTripExpense

    trip = _member(db, trip_id, user)
    e = db.get(TravelTripExpense, expense_id)
    if e is None or e.trip_id != trip_id:
        raise HTTPException(404, "账目不存在")
    if body.amount <= 0:
        raise HTTPException(400, "金额必须大于 0")
    if not body.title.strip():
        raise HTTPException(400, "写一下这笔花在哪了")

    users = _trip_users(db, trip_id)
    name_to_id = {v: k for k, v in users.items()}
    if body.payer.strip():
        payer_id = name_to_id.get(body.payer.strip(), "")
        if not payer_id:
            raise HTTPException(400, "垫付人不在本行程里")
        e.payer_user_id = payer_id
    if body.participant_usernames:
        parts = [name_to_id[n] for n in body.participant_usernames if n in name_to_id]
        if not parts:
            raise HTTPException(400, "参与人无效")
        e.participants_json = _json.dumps(parts)
    e.amount = round(body.amount, 2)
    e.title = body.title.strip()[:120]
    e.category = body.category if body.category in EXPENSE_CATEGORIES else "其他"
    e.spent_at = (body.spent_at or "").strip()[:10]
    _log_event(db, trip_id, user, f"修改了账目「{e.title}」")
    _touch(db, trip)
    db.commit()
    return {"ok": True}


@router.get("/{trip_id}/expenses/summary")
def expenses_summary(trip_id: str, db: Session = Depends(get_db),
                     user: TravelUser = Depends(get_current_user)):
    """一键结算：谁出了多少、每人应摊、谁给谁转多少 + 可复制文字账单。"""
    import json as _json

    from app.agent.trip_planner import settle_expenses
    from app.db.models import TravelTripExpense

    trip = _member(db, trip_id, user)
    users = _trip_users(db, trip_id)
    rows = db.execute(
        select(TravelTripExpense).where(TravelTripExpense.trip_id == trip_id)
    ).scalars().all()
    result = settle_expenses([{
        "payer_user_id": e.payer_user_id, "amount": e.amount, "category": e.category,
        "participants": _json.loads(e.participants_json),
    } for e in rows])

    def name(uid: str) -> str:
        return users.get(uid, "已退出成员")

    per_person = [{**p, "username": name(p["user_id"])} for p in result["per_person"]]
    transfers = [{"from": name(t["from_user"]), "to": name(t["to_user"]), "amount": t["amount"]}
                 for t in result["transfers"]]
    lines = [f"🧾 「{trip.title}」结算（共 {len(rows)} 笔，合计 ¥{result['total']:.2f}）", ""]
    for p in sorted(per_person, key=lambda x: -x["paid"]):
        lines.append(f"{p['username']}：垫付 ¥{p['paid']:.2f}｜应摊 ¥{p['share']:.2f}"
                     f"｜{'应收' if p['balance'] >= 0 else '应付'} ¥{abs(p['balance']):.2f}")
    if transfers:
        lines.append("")
        lines.append("转账建议：")
        lines += [f"· {t['from']} → {t['to']}  ¥{t['amount']:.2f}" for t in transfers]
    else:
        lines.append("")
        lines.append("已两清，无需转账 🎉")
    return {"total": result["total"], "count": len(rows), "by_category": result["by_category"],
            "per_person": per_person, "transfers": transfers, "text": "\n".join(lines)}


# ---------- Phase 42：分享链接加入 ----------

_TRIP_MEMBER_CAP = 20  # 防滥用：分享链接可自助加入，封个上限


class ShareBody(BaseModel):
    reset: bool = False


@router.post("/{trip_id}/share")
def create_share(trip_id: str, body: ShareBody,
                 db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """开启/重置分享链接（仅 owner）。重置后旧链接立即失效。"""
    import uuid

    trip = _member(db, trip_id, user)
    if trip.owner_id != user.id:
        raise HTTPException(403, "只有创建者能管理分享链接")
    if trip.invite_token is None or body.reset:
        for _ in range(5):  # 短码 = token 前 8 位，生成时保证全局唯一（Phase 42.1 短链）
            candidate = uuid.uuid4().hex
            clash = db.execute(
                select(TravelTrip).where(TravelTrip.invite_token.like(f"{candidate[:8]}%"))
            ).scalar_one_or_none()
            if clash is None:
                trip.invite_token = candidate
                break
        _log_event(db, trip_id, user, "重置了分享链接" if body.reset else "开启了链接分享")
        db.commit()
    return {"token": trip.invite_token, "short_code": trip.invite_token[:8]}


@router.delete("/{trip_id}/share")
def disable_share(trip_id: str, db: Session = Depends(get_db),
                  user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    if trip.owner_id != user.id:
        raise HTTPException(403, "只有创建者能管理分享链接")
    trip.invite_token = None
    _log_event(db, trip_id, user, "关闭了链接分享")
    db.commit()
    return {"ok": True}


@router.get("/shared/{token}")
def shared_preview(token: str, db: Session = Depends(get_db)):
    """免登录预览：给分享落地页「XX 邀请你加入…」用，只回最小信息不泄露行程内容。"""
    trip = db.execute(
        select(TravelTrip).where(TravelTrip.invite_token == token)
    ).scalar_one_or_none()
    if trip is None:
        raise HTTPException(404, "链接无效或已被关闭")
    owner = db.get(TravelUser, trip.owner_id)
    count = len(db.execute(
        select(TravelTripMember).where(TravelTripMember.trip_id == trip.id,
                                       TravelTripMember.status == "accepted")
    ).scalars().all())
    return {"title": trip.title, "destination": trip.destination,
            "inviter": owner.username if owner else "", "member_count": count}


class JoinBody(BaseModel):
    token: str


@router.post("/join")
def join_by_token(body: JoinBody, db: Session = Depends(get_db),
                  user: TravelUser = Depends(get_current_user)):
    """凭分享链接 token 直接加入（accepted）。幂等：已是成员直接返回。"""
    trip = db.execute(
        select(TravelTrip).where(TravelTrip.invite_token == body.token.strip())
    ).scalar_one_or_none()
    if trip is None:
        raise HTTPException(404, "链接无效或已被关闭")
    existing = db.get(TravelTripMember, (trip.id, user.id))
    if existing is not None:
        if existing.status != "accepted":  # 之前被邀请未接受，链接进来视为接受
            existing.status = "accepted"
            db.commit()
        return {"trip_id": trip.id}
    members = db.execute(
        select(TravelTripMember).where(TravelTripMember.trip_id == trip.id)
    ).scalars().all()
    if len(members) >= _TRIP_MEMBER_CAP:
        raise HTTPException(409, "该行程成员已满")
    db.add(TravelTripMember(trip_id=trip.id, user_id=user.id, role="editor", status="accepted"))
    _log_event(db, trip.id, user, "通过分享链接加入了行程")
    _touch(db, trip)
    db.commit()
    return {"trip_id": trip.id}


@router.get("/t/{code}")
def short_link(code: str, db: Session = Depends(get_db)):
    """短链跳转（Phase 42.1）：/t/{8位码} → /travel/?join={完整token}。免登录，纯 302。"""
    from fastapi.responses import RedirectResponse

    code = code.strip().lower()
    if not (6 <= len(code) <= 32):
        raise HTTPException(404, "链接无效")
    trip = db.execute(
        select(TravelTrip).where(TravelTrip.invite_token.like(f"{code}%"))
    ).scalar_one_or_none()
    if trip is None or not trip.invite_token:
        raise HTTPException(404, "链接无效或已被关闭")
    return RedirectResponse(f"/travel/?join={trip.invite_token}", status_code=302)


# ---------- Phase 46：目的地酒店推荐（高德为主） ----------

@router.get("/{trip_id}/hotels")
async def trip_hotels(trip_id: str, city: str = "",
                      db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """高德酒店推荐（秒级、无登录墙）。默认查 trip.destination，可传 city 覆盖（多城行程按城查）。
    实时价格/房态请走「携程实价」（对话流水线），此处不含。"""
    trip = _member(db, trip_id, user)
    target = (city or trip.destination or "").strip()
    if not target:
        raise HTTPException(400, "行程还没有目的地，指定一个城市再查酒店")
    from app.tools.amap import search_hotels
    from app.tools.geocode import known_overseas_city

    overseas = known_overseas_city(target)
    try:
        hotels = [] if overseas else await search_hotels(target)
    except Exception:  # noqa: BLE001
        logger.warning("search_hotels failed for %s", target, exc_info=True)
        hotels = []
    return {"city": target, "hotels": hotels,
            "notice": "海外酒店暂不使用高德国内数据，请从来源攻略或携程选择。" if overseas else ""}


@router.get("/{trip_id}/day-cities")
async def trip_day_cities(trip_id: str, db: Session = Depends(get_db),
                          user: TravelUser = Depends(get_current_user)):
    """每天的过夜城市（Phase 48）：取该天最后一个有坐标的地点逆地理编码；无坐标回退目的地。
    供「每晚住哪」按天订房——点某天直接搜该城酒店。"""
    import asyncio

    trip = _member(db, trip_id, user)
    stops = sorted(
        [_stop_dict(s) for s in db.execute(
            select(TravelTripStop).where(TravelTripStop.trip_id == trip_id)
        ).scalars()],
        key=lambda s: (s["day"], s["order_no"]),
    )
    last_loc: dict[int, str] = {}
    for s in stops:
        if s["location"]:
            last_loc[s["day"]] = s["location"]  # 同天靠后覆盖 → 最后一个有坐标的点

    from app.tools.amap import regeo

    sem = asyncio.Semaphore(3)

    def _norm(name: str) -> str:
        # 命名统一：去尾部「市」，避免「拉萨」「拉萨市」并存看着对不上（Phase 48.1）
        name = (name or "").strip()
        return name[:-1] if len(name) > 2 and name.endswith("市") else name

    async def one(day: int, loc: str):
        async with sem:
            try:
                return day, _norm((await regeo(loc)) or trip.destination)
            except Exception:  # noqa: BLE001
                return day, _norm(trip.destination)

    pairs = await asyncio.gather(*[one(d, loc) for d, loc in last_loc.items()])
    cities = {str(d): c for d, c in pairs}

    # Phase 54.1：每天定性与检查中心共用 resolve_day_classes（几何兜底 + 攻略 LLM 计划覆盖），
    # 解决火车过夜无地点、当天往返景点行政区误判；返程/无需过夜的天不再提示订房。
    from app.agent.trip_planner import resolve_day_classes

    dclass = resolve_day_classes(stops, trip.days, _load_day_plans(trip))
    day_types = {str(d): v["type"] for d, v in dclass.items()}
    overnight = {str(d): v["overnight_required"] for d, v in dclass.items()}
    for d, v in dclass.items():
        key = str(d)
        city = _norm(v.get("overnight_city") or "")
        if city:  # 攻略明确的过夜城市优先
            cities[key] = city
        elif v["overnight_required"] is False:  # 返程/无需过夜 → 不给订房城市
            cities.pop(key, None)
    return {"cities": cities, "default": _norm(trip.destination or ""),
            "day_types": day_types, "overnight": overnight}
