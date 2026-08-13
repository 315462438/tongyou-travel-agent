"""本体对象存储（Phase 86）

对象图**抽一次、存起来、所有下游共用**。`ensure_trip_object` 是唯一入口：
命中缓存直接返回，未命中才调一次 LLM 抽取。

失效判定两条：
- `source_hash` 变了 → 攻略正文被多轮修改重写过，旧对象图配不上新正文；
- `schema_version` 变了 → 对象结构升级，旧 payload 语义不保证。
"""

from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy import select

from app.db.models import TravelGuideObject, TravelMessage
from app.db.session import get_session
from app.ontology.objects import SCHEMA_VERSION, TripObject

logger = logging.getLogger(__name__)


def source_hash(guide: str) -> str:
    return hashlib.sha1((guide or "").encode("utf-8")).hexdigest()


def load_trip_object(message_id: str, guide: str) -> TripObject | None:
    """读缓存的对象图；正文变了或结构版本对不上都当未命中。"""
    want = source_hash(guide)
    try:
        with get_session() as db:
            row = db.execute(
                select(TravelGuideObject).where(TravelGuideObject.message_id == message_id)
            ).scalar_one_or_none()
            if row is None:
                return None
            if row.schema_version != SCHEMA_VERSION or row.source_hash != want:
                return None
            return TripObject.model_validate(json.loads(row.payload_json))
    except Exception:  # noqa: BLE001 — 缓存读失败退化为重新抽取，不能挡住功能
        logger.warning("load trip object failed msg=%s", message_id, exc_info=True)
        return None


def save_trip_object(
    trip: TripObject, *, message_id: str, conversation_id: str, guide: str, user_id: str = ""
) -> None:
    """落库（同 message_id 覆盖）。写失败只 warn——对象图能重建，不能因此挡住出图。"""
    payload = json.dumps(trip.model_dump(), ensure_ascii=False)
    try:
        with get_session() as db:
            row = db.execute(
                select(TravelGuideObject).where(TravelGuideObject.message_id == message_id)
            ).scalar_one_or_none()
            if row is None:
                row = TravelGuideObject(message_id=message_id, conversation_id=conversation_id)
                db.add(row)
            row.conversation_id = conversation_id
            row.user_id = user_id or row.user_id or ""
            row.schema_version = SCHEMA_VERSION
            row.source_hash = source_hash(guide)
            row.destination = (trip.destination or "")[:64]
            row.days_count = trip.days_count
            row.payload_json = payload
            db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("save trip object failed msg=%s", message_id, exc_info=True)


def guide_text(message_id: str) -> tuple[str, str]:
    """取攻略消息正文与所属会话；找不到返回 ("", "")。"""
    with get_session() as db:
        m = db.get(TravelMessage, message_id)
        if m is None:
            return "", ""
        return (m.content or ""), m.conversation_id


def merge_trips(base: TripObject, add: TripObject) -> TripObject:
    """把新抽的路并进已有对象图（按路取字段，互不覆盖）。

    每个字段只由**产出它的那一路**负责，所以合并没有冲突可言：
    profile → 标题/主题/目的地/人数/住宿/美食/特产/贴士；cost → 开销/预约/口径/自报合计；
    days → 逐日与地点。已有的路不会被重跑，也就不会被覆盖。
    """
    from app.ontology.extract import LANE_COST, LANE_ITINERARY

    update: dict = {}
    added = set(add.lanes)
    if LANE_ITINERARY in added:
        update.update(
            title=add.title, subtitle=add.subtitle, theme=add.theme,
            destination=add.destination or base.destination,
            days_count=add.days_count or base.days_count,
            lodgings=add.lodgings, foods=add.foods, specialties=add.specialties, tips=add.tips,
            days=add.days, stops=add.stops, failed_days=add.failed_days,
        )
    if LANE_COST in added:
        update.update(
            expenses=add.expenses, reservations=add.reservations,
            notes=add.notes, stated_total=add.stated_total,
        )
    # headcount 两路都可能给（itinerary 从正文人数、cost 从预算口径），取大的那个
    update["headcount"] = max(base.headcount, add.headcount)
    update["lanes"] = sorted(set(base.lanes) | added)
    return base.model_copy(update=update).normalized()


async def ensure_trip_object(
    cid: str, message_id: str, *, llm=None, user_id: str = "", destination_hint: str = "",
    need: tuple[str, ...] | None = None,
) -> TripObject | None:
    """拿到这条攻略消息的对象图，**只抽调用方要的那几路**，已有的路复用缓存。

    `need` 缺省为全部三路。海报传 `POSTER_LANES`、预算传 `BUDGET_LANES`——
    这样点海报不会为预算数据买单，点预算时 profile 已在缓存里、只补 cost 一路。

    返回 None 表示这份攻略抽不出任何可用结构（调用方据此给友好提示，而不是渲染空面板）。
    """
    from app.llm.client import get_llm
    from app.ontology.extract import ALL_LANES, build_trip_object

    want = tuple(need or ALL_LANES)
    guide, conv_id = guide_text(message_id)
    if not guide.strip():
        return None

    cached = load_trip_object(message_id, guide)
    have = set(cached.lanes) if cached is not None else set()
    missing = tuple(ln for ln in want if ln not in have)
    if cached is not None and not missing:
        return None if cached.is_empty() else cached

    fresh = await build_trip_object(
        llm or get_llm(), guide, cid=cid, destination_hint=destination_hint,
        lanes=missing or want,
    )
    trip = merge_trips(cached, fresh) if cached is not None else fresh
    # 空图也存：避免每次点按钮都重抽一遍同一份抽不出东西的攻略
    save_trip_object(
        trip, message_id=message_id, conversation_id=conv_id or cid,
        guide=guide, user_id=user_id,
    )
    return None if trip.is_empty() else trip


def invalidate(message_id: str) -> None:
    """显式失效（攻略被就地重写时用）。正常路径靠 source_hash 自动判定，无需调用。"""
    try:
        with get_session() as db:
            row = db.execute(
                select(TravelGuideObject).where(TravelGuideObject.message_id == message_id)
            ).scalar_one_or_none()
            if row is not None:
                db.delete(row)
                db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("invalidate trip object failed msg=%s", message_id, exc_info=True)
