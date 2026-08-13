"""新用户空状态数据（Phase 75）。

背景：08-04 那批新用户 12 个里 4 个（33%）注册后一个字没问就走了。
提问的 8 个全部拿到了完整攻略，所以问题不在产出质量，在**第一步的门槛**——
首页示例写死成都，而用户全是合肥/武汉的；空输入框又要求他们一次说清完整需求。

这里只提供「让人敢开口」的素材，不碰生成链路。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import TravelConversation, TravelMemory, TravelUser
from app.db.session import get_db
from app.tools.amap import enabled as amap_enabled, search_destination_cover

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])
logger = logging.getLogger(__name__)

# 这些账号的会话是内部测试/评估跑出来的，必须排除：
# evalbot 一个人就能把「成都」刷成第一名，热门榜会彻底失真。
INTERNAL_USERNAMES = {"admin", "evalbot", "test", "testyuan", "tester_lulu", "codex_trip_0731"}
TRENDING_LIMIT = 6
TRENDING_DAYS = 30
COVER_LIMIT = 5  # 热门前 4 + Phase 79 天堂寨实境入口封面
COVER_SUCCESS_TTL_S = 24 * 60 * 60
COVER_EMPTY_TTL_S = 60 * 60
_cover_cache: dict[str, tuple[float, str]] = {}


def first_city(destination: str) -> str:
    """多城目的地取首城。

    `destination` 可能是「武汉,开封,洛阳,西安」这种整串，直接当 chip 会出现
    一张念不出来的卡片。取首城既短又仍然是真实需求。
    """
    if not destination:
        return ""
    for sep in (",", "，", "、", "-", "→"):
        if sep in destination:
            destination = destination.split(sep)[0]
    return destination.strip()[:12]


def trending_destinations(db: Session, limit: int = TRENDING_LIMIT) -> list[str]:
    """平台最近在被规划的目的地。任何异常都返回空 —— 空状态自会回退静态示例。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=TRENDING_DAYS)
    try:
        rows = db.execute(
            select(TravelConversation.destination, func.count().label("n"))
            .join(TravelUser, TravelUser.id == TravelConversation.user_id)
            .where(
                TravelConversation.destination.is_not(None),
                TravelConversation.destination != "",
                TravelUser.username.not_in(INTERNAL_USERNAMES),
                TravelConversation.updated_at >= cutoff,
            )
            .group_by(TravelConversation.destination)
            .order_by(func.count().desc())
            .limit(limit * 4)  # 多取一些，拆首城后会有重复
        ).all()
    except Exception:  # noqa: BLE001
        logger.warning("热门目的地查询失败（忽略）", exc_info=True)
        return []

    out: list[str] = []
    for destination, _n in rows:
        city = first_city(destination or "")
        if not city:
            continue
        # 包含去重：真实数据里同时存在「平潭岛」和「福建平潭岛」、「黄山」和「黄山市」，
        # 两张 chip 并排出现会直接穿帮。命中包含关系时保留**更短**的那个（更像地名本身）。
        dup = next((x for x in out if x in city or city in x), None)
        if dup is not None:
            if len(city) < len(dup):
                out[out.index(dup)] = city
            continue
        out.append(city)
        if len(out) >= limit:
            break
    return out


def home_city_of(db: Session, user_id: str) -> str:
    """用户常驻城市（记忆里的 fact）。没有就返回空串，前端不带出发地。"""
    try:
        row = db.execute(
            select(TravelMemory.content)
            .where(TravelMemory.user_id == user_id, TravelMemory.key == "常驻城市")
            .order_by(TravelMemory.updated_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    except Exception:  # noqa: BLE001
        return ""
    if not row:
        return ""
    # 记忆是自然语言（「常驻城市：合肥」/「用户常驻合肥」），这里只要城市名
    text = str(row)
    for sep in ("：", ":", "是", "在"):
        if sep in text:
            text = text.split(sep)[-1]
    return text.strip().strip("。.，,")[:12]


def clean_cover_destinations(values: list[str], limit: int = COVER_LIMIT) -> list[str]:
    """清洗封面查询，避免把任意长文本和重复值送进第三方 API。"""
    out: list[str] = []
    for raw in values:
        city = first_city(str(raw or ""))
        if not city or city in out:
            continue
        out.append(city)
        if len(out) >= limit:
            break
    return out


@router.get("")
def onboarding(db: Session = Depends(get_db),
               user: TravelUser = Depends(get_current_user)):
    has_history = bool(db.execute(
        select(func.count()).select_from(TravelConversation)
        .where(TravelConversation.user_id == user.id)
    ).scalar_one())
    return {
        "home_city": home_city_of(db, user.id),
        "trending": trending_destinations(db),
        "has_history": has_history,
    }


@router.get("/covers")
async def destination_covers(
    destinations: list[str] = Query(default=[]),
    user: TravelUser = Depends(get_current_user),
):
    """热门目的地封面（增强项）。

    排名仍由 ``/api/onboarding`` 的数据库统计决定；这里仅给同一批地名补图。结果使用进程内
    TTL 缓存，高德不可用或单城失败时返回空值，前端自然回退品牌占位。
    """
    del user  # 依赖负责鉴权，封面内容不因用户而异
    cities = clean_cover_destinations(destinations)
    if not cities or not amap_enabled():
        return {"covers": {}}

    now = time.monotonic()
    covers: dict[str, str] = {}
    missing: list[str] = []
    for city in cities:
        cached = _cover_cache.get(city)
        if cached and cached[0] > now:
            if cached[1]:
                covers[city] = cached[1]
        else:
            missing.append(city)

    if missing:
        semaphore = asyncio.Semaphore(2)
        async with httpx.AsyncClient(trust_env=False) as client:
            async def resolve(city: str) -> tuple[str, str]:
                try:
                    async with semaphore:
                        return city, await search_destination_cover(client, city)
                except Exception:  # noqa: BLE001
                    logger.warning("热门目的地封面查询失败：%s", city, exc_info=True)
                    return city, ""

            resolved = await asyncio.gather(*(resolve(city) for city in missing))
        cached_at = time.monotonic()
        for city, url in resolved:
            ttl = COVER_SUCCESS_TTL_S if url else COVER_EMPTY_TTL_S
            _cover_cache[city] = (cached_at + ttl, url)
            if url:
                covers[city] = url

    return {"covers": covers}
