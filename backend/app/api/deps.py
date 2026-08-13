"""鉴权依赖（Phase 15）：从 Authorization: Bearer <token> 解析当前用户。"""

import logging
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import TravelSession, TravelUser
from app.db.session import get_db

logger = logging.getLogger(__name__)


def _as_utc(dt: datetime | None) -> datetime | None:
    """DB 取回的时间可能是 naive（Postgres TIMESTAMP 无时区），统一按 UTC 解读。

    不做这一步，naive 与 aware 相减会直接 TypeError，把整个鉴权打挂。
    """
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso_utc(dt: datetime | None) -> str | None:
    """序列化成**带时区**的 ISO。

    Postgres 的 TIMESTAMP 是 naive，直接 `.isoformat()` 出来没有偏移量，
    浏览器 `Date.parse` 会按**本地时区**解读 —— 东八区下会凭空差 8 小时，
    「刚刚活跃」显示成「8 小时前」。
    """
    aware = _as_utc(dt)
    return aware.isoformat() if aware else None


def touch_last_seen(db: Session, user: TravelUser) -> None:
    """更新 `last_seen_at`（Phase 73 在线状态）。

    **必须节流**：这里是全站最热的路径，每个请求写一次会造成明显的写放大
    （前端本来就在轮询消息/未读）。距上次不足 `online_touch_throttle_s` 直接跳过。

    任何失败都只记日志——在线状态是运营看板功能，绝不能因为它让用户登不上。
    """
    now = datetime.now(timezone.utc)
    last = _as_utc(user.last_seen_at)
    if last is not None and (now - last).total_seconds() < settings.online_touch_throttle_s:
        return
    try:
        user.last_seen_at = now
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.warning("touch last_seen_at 失败（忽略）", exc_info=True)


def get_current_user(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> TravelUser:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(401, "未登录")
    sess = db.get(TravelSession, token)
    if sess is None:
        raise HTTPException(401, "登录已失效，请重新登录")
    user = db.get(TravelUser, sess.user_id)
    if user is None:
        raise HTTPException(401, "用户不存在")
    touch_last_seen(db, user)
    return user


# 允许的时钟偏差：超过这个幅度的「未来时间」不是偏差，是时区/存储出了问题
_MAX_CLOCK_SKEW_S = 120


def is_online(last_seen_at: datetime | None, now: datetime | None = None) -> bool:
    """在线判定放服务端，不把阈值下放给前端——两端各判一次必然漂移。"""
    last = _as_utc(last_seen_at)
    if last is None:
        return False
    now = now or datetime.now(timezone.utc)
    delta = (now - last).total_seconds()
    # 明显来自未来 → 多半是时区折算错了（naive 列 + 非 UTC 服务器时区，见 pitfalls）。
    # 不能返回 True：那会让**所有人永远在线**，而且离线越久越像刚活跃，错得毫无声响。
    if delta < -_MAX_CLOCK_SKEW_S:
        return False
    return delta <= settings.online_window_s


def require_admin(user: TravelUser = Depends(get_current_user)) -> TravelUser:
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    return user
