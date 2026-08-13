"""统一社交通知（Phase 84）。

通知属于持久化业务数据：全部按当前登录用户过滤。写入 helper 由好友/接力事务调用，只 flush，
提交仍由原业务操作统一完成，避免出现“关系失败但通知成功”的半事务。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import TravelNotification, TravelUser
from app.db.session import get_db

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def upsert_notification(
    db: Session,
    *,
    user_id: str,
    actor_id: str | None,
    type: str,
    title: str,
    body: str,
    target_kind: str,
    target_id: str | None,
    dedupe_key: str,
    meta: dict | None = None,
) -> TravelNotification:
    """新增或刷新一个定向事件。重复事件回到未读，但不会堆积。"""
    row = db.execute(select(TravelNotification).where(
        TravelNotification.dedupe_key == dedupe_key,
    )).scalar_one_or_none()
    now = _now()
    values = {
        "user_id": user_id,
        "actor_id": actor_id,
        "type": type[:32],
        "title": title[:128],
        "body": body[:320],
        "target_kind": target_kind[:24],
        "target_id": target_id,
        "meta_json": json.dumps(meta or {}, ensure_ascii=False),
        "read_at": None,
        "updated_at": now,
    }
    if row is None:
        row = TravelNotification(dedupe_key=dedupe_key[:160], created_at=now, **values)
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    db.flush()
    return row


def delete_notification(db: Session, dedupe_key: str) -> None:
    row = db.execute(select(TravelNotification).where(
        TravelNotification.dedupe_key == dedupe_key,
    )).scalar_one_or_none()
    if row is not None:
        db.delete(row)
        db.flush()


def delete_target_notifications(db: Session, target_kind: str, target_id: str) -> None:
    rows = db.execute(select(TravelNotification).where(
        TravelNotification.target_kind == target_kind,
        TravelNotification.target_id == target_id,
    )).scalars().all()
    for row in rows:
        db.delete(row)
    if rows:
        db.flush()


def _avatar(user: TravelUser | None) -> str:
    return f"/travel/api/uploads/{user.avatar_upload_id}" if user and user.avatar_upload_id else ""


def _serialize(db: Session, row: TravelNotification) -> dict:
    actor = db.get(TravelUser, row.actor_id) if row.actor_id else None
    try:
        meta = json.loads(row.meta_json or "{}")
    except (TypeError, ValueError):
        meta = {}
    return {
        "id": row.id,
        "type": row.type,
        "title": row.title,
        "body": row.body,
        "target_kind": row.target_kind,
        "target_id": row.target_id or "",
        "meta": meta if isinstance(meta, dict) else {},
        "read": row.read_at is not None,
        "created_at": _aware(row.updated_at or row.created_at).isoformat(),
        "actor": {
            "id": actor.id if actor else "",
            "username": actor.username if actor else "17同游",
            "display_name": ((actor.display_name or actor.username).strip() if actor else "17同游"),
            "avatar_url": _avatar(actor),
        },
    }


@router.get("")
def list_notifications(
    limit: int = Query(default=40, ge=1, le=100),
    db: Session = Depends(get_db),
    user: TravelUser = Depends(get_current_user),
):
    rows = db.execute(
        select(TravelNotification)
        .where(TravelNotification.user_id == user.id)
        .order_by(TravelNotification.updated_at.desc())
        .limit(limit)
    ).scalars().all()
    unread = int(db.scalar(select(func.count()).select_from(TravelNotification).where(
        TravelNotification.user_id == user.id,
        TravelNotification.read_at.is_(None),
    )) or 0)
    return {"notifications": [_serialize(db, row) for row in rows], "unread": unread}


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    unread = int(db.scalar(select(func.count()).select_from(TravelNotification).where(
        TravelNotification.user_id == user.id,
        TravelNotification.read_at.is_(None),
    )) or 0)
    return {"unread": unread}


@router.post("/{notification_id}/read")
def read_notification(notification_id: str, db: Session = Depends(get_db),
                      user: TravelUser = Depends(get_current_user)):
    row = db.get(TravelNotification, notification_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "通知不存在")
    if row.read_at is None:
        row.read_at = _now()
        db.commit()
    return {"status": "ok"}


@router.post("/read-all")
def read_all_notifications(db: Session = Depends(get_db),
                           user: TravelUser = Depends(get_current_user)):
    db.execute(update(TravelNotification).where(
        TravelNotification.user_id == user.id,
        TravelNotification.read_at.is_(None),
    ).values(read_at=_now()))
    db.commit()
    return {"status": "ok"}
