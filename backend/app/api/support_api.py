"""客服会话（Phase 73）：每个用户与管理员之间一条常驻会话。

设计取舍见 docs/task_plans/在线状态与客服会话-2026-08-04.md：
- 不做工单状态流转（当前规模用不上，状态机是净负担）
- 未读不另建表，由 `read_at` 两向对称推导，读取即已读
- 轮询而非推送，与全站其余对话流保持一致
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, is_online, iso_utc, require_admin
from app.config import settings
from app.db.models import TravelSupportMessage, TravelUser
from app.db.session import get_db

support_router = APIRouter(prefix="/api/support", tags=["support"])
admin_support_router = APIRouter(prefix="/api/admin/support", tags=["support"])


class SendSupportMessage(BaseModel):
    content: str


_iso = iso_utc  # 统一走带时区的序列化（naive ISO 会被浏览器按本地时区解读）


def _clean(content: str) -> str:
    text = (content or "").strip()
    if not text:
        raise HTTPException(400, "消息不能为空")
    return text[: settings.support_message_max_chars]


def _serialize(m: TravelSupportMessage) -> dict:
    return {"id": m.id, "sender": m.sender, "content": m.content,
            "created_at": _iso(m.created_at), "read": m.read_at is not None}


def _thread(db: Session, user_id: str) -> list[TravelSupportMessage]:
    return list(db.execute(
        select(TravelSupportMessage)
        .where(TravelSupportMessage.user_id == user_id)
        .order_by(TravelSupportMessage.created_at)
    ).scalars().all())


def _mark_read(db: Session, user_id: str, sender: str) -> None:
    """把对方发来的未读标记为已读。读取即已读——不再单独提供「标记已读」接口。"""
    rows = db.execute(
        select(TravelSupportMessage).where(
            TravelSupportMessage.user_id == user_id,
            TravelSupportMessage.sender == sender,
            TravelSupportMessage.read_at.is_(None),
        )
    ).scalars().all()
    if not rows:
        return
    now = datetime.now(timezone.utc)
    for r in rows:
        r.read_at = now
    db.commit()


# ---------- 用户侧 ----------

@support_router.get("/messages")
def my_messages(db: Session = Depends(get_db),
                user: TravelUser = Depends(get_current_user)):
    msgs = _thread(db, user.id)
    _mark_read(db, user.id, "admin")  # 我读到了管理员的回复
    return {"messages": [_serialize(m) for m in msgs]}


@support_router.post("/messages")
def send_message(req: SendSupportMessage, db: Session = Depends(get_db),
                 user: TravelUser = Depends(get_current_user)):
    msg = TravelSupportMessage(user_id=user.id, sender="user", content=_clean(req.content))
    db.add(msg)
    db.commit()
    return _serialize(msg)


@support_router.get("/unread")
def my_unread(db: Session = Depends(get_db),
              user: TravelUser = Depends(get_current_user)):
    """前端低频轮询红点用。故意做得极轻。"""
    n = db.execute(
        select(func.count()).select_from(TravelSupportMessage).where(
            TravelSupportMessage.user_id == user.id,
            TravelSupportMessage.sender == "admin",
            TravelSupportMessage.read_at.is_(None),
        )
    ).scalar_one()
    return {"unread": int(n)}


# ---------- 管理员侧 ----------

@admin_support_router.get("/threads")
def list_threads(_: TravelUser = Depends(require_admin), db: Session = Depends(get_db)):
    """所有有过客服消息的用户，按最新消息倒序；带未读数与最后一条摘要。"""
    rows = db.execute(
        select(
            TravelSupportMessage.user_id,
            func.count().label("total"),
            func.max(TravelSupportMessage.created_at).label("last_at"),
        ).group_by(TravelSupportMessage.user_id)
    ).all()
    if not rows:
        return {"threads": [], "unread_total": 0}

    unread = dict(db.execute(
        select(TravelSupportMessage.user_id, func.count()).where(
            TravelSupportMessage.sender == "user",
            TravelSupportMessage.read_at.is_(None),
        ).group_by(TravelSupportMessage.user_id)
    ).all())
    users = {u.id: u for u in db.execute(
        select(TravelUser).where(TravelUser.id.in_([r.user_id for r in rows]))
    ).scalars().all()}
    last_msgs = {}
    for uid in [r.user_id for r in rows]:
        m = db.execute(
            select(TravelSupportMessage)
            .where(TravelSupportMessage.user_id == uid)
            .order_by(TravelSupportMessage.created_at.desc()).limit(1)
        ).scalars().first()
        last_msgs[uid] = m

    threads = []
    for r in rows:
        u = users.get(r.user_id)
        m = last_msgs.get(r.user_id)
        threads.append({
            "user_id": r.user_id,
            "username": u.username if u else "(已删除用户)",
            "online": is_online(u.last_seen_at) if u else False,
            "last_seen_at": _iso(u.last_seen_at) if u else None,
            "total": int(r.total),
            "unread": int(unread.get(r.user_id, 0)),
            "last_at": _iso(r.last_at),
            "last_sender": m.sender if m else None,
            "last_excerpt": (m.content[:60] if m else ""),
        })
    threads.sort(key=lambda t: t["last_at"] or "", reverse=True)
    return {"threads": threads, "unread_total": sum(t["unread"] for t in threads)}


@admin_support_router.get("/{user_id}/messages")
def thread_messages(user_id: str, _: TravelUser = Depends(require_admin),
                    db: Session = Depends(get_db)):
    if db.get(TravelUser, user_id) is None:
        raise HTTPException(404, "用户不存在")
    msgs = _thread(db, user_id)
    _mark_read(db, user_id, "user")  # 管理员读到了用户的问题
    return {"messages": [_serialize(m) for m in msgs]}


@admin_support_router.post("/{user_id}/messages")
def reply(user_id: str, req: SendSupportMessage,
          _: TravelUser = Depends(require_admin), db: Session = Depends(get_db)):
    if db.get(TravelUser, user_id) is None:
        raise HTTPException(404, "用户不存在")
    msg = TravelSupportMessage(user_id=user_id, sender="admin", content=_clean(req.content))
    db.add(msg)
    db.commit()
    return _serialize(msg)
