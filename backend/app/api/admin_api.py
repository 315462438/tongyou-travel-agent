"""管理后台（Phase 74）：角色管理 / 邀请码 / 公告推送。

设计取舍见 docs/task_plans/管理后台批次-角色邀请码公告图片表情-2026-08-04.md
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, iso_utc, require_admin
from app.config import settings
from app.db.models import (
    TravelAnnouncement,
    TravelAnnouncementRead,
    TravelInviteCode,
    TravelUser,
)
from app.db.session import get_db

admin_manage_router = APIRouter(prefix="/api/admin", tags=["admin"])
announce_router = APIRouter(prefix="/api/announcements", tags=["announcements"])


# ---------- 角色 ----------

class RoleRequest(BaseModel):
    is_admin: bool


@admin_manage_router.patch("/users/{user_id}/role")
def set_role(user_id: str, req: RoleRequest,
             me: TravelUser = Depends(require_admin), db: Session = Depends(get_db)):
    """升级/降级管理员。两条防呆都放服务端——前端禁用按钮挡不住直接打接口。"""
    target = db.get(TravelUser, user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    if target.id == me.id:
        # 允许改自己 = 可以一键把自己锁在管理后台外面，且无法自助恢复
        raise HTTPException(400, "不能修改自己的角色，请让另一位管理员操作")
    if target.is_admin and not req.is_admin:
        others = db.execute(
            select(func.count()).select_from(TravelUser)
            .where(TravelUser.is_admin.is_(True), TravelUser.id != target.id)
        ).scalar_one()
        if not others:
            raise HTTPException(400, "这是最后一个管理员，降级后系统将没有管理员")
    target.is_admin = bool(req.is_admin)
    db.commit()
    return {"id": target.id, "username": target.username, "is_admin": target.is_admin}


# ---------- 邀请码 ----------

class CreateInvite(BaseModel):
    max_uses: int | None = None


def _invite_row(c: TravelInviteCode) -> dict:
    exhausted = c.used_count >= c.max_uses
    return {
        "code": c.code, "max_uses": c.max_uses, "used_count": c.used_count,
        "active": c.active, "exhausted": exhausted,
        "usable": bool(c.active and not exhausted),
        "created_at": iso_utc(c.created_at),
    }


@admin_manage_router.get("/invites")
def list_invites(_: TravelUser = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.execute(
        select(TravelInviteCode).order_by(TravelInviteCode.created_at.desc())
    ).scalars().all()
    return {"invites": [_invite_row(c) for c in rows],
            "env_fallback": bool((settings.register_invite_code or "").strip())}


@admin_manage_router.post("/invites")
def create_invite(req: CreateInvite, me: TravelUser = Depends(require_admin),
                  db: Session = Depends(get_db)):
    uses = req.max_uses or settings.invite_code_default_uses
    if uses < 1 or uses > 500:
        raise HTTPException(400, "邀请人数需在 1-500 之间")
    # 去掉易混字符（0/O、1/I/l），邀请码常被手抄或口述
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    code = "-".join(
        "".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2)
    )
    row = TravelInviteCode(code=code, created_by=me.id, max_uses=uses)
    db.add(row)
    db.commit()
    return _invite_row(row)


@admin_manage_router.delete("/invites/{code}")
def deactivate_invite(code: str, _: TravelUser = Depends(require_admin),
                      db: Session = Depends(get_db)):
    row = db.get(TravelInviteCode, code)
    if row is None:
        raise HTTPException(404, "邀请码不存在")
    row.active = False  # 不删行：保留「谁的码带进来多少人」的审计痕迹
    db.commit()
    return _invite_row(row)


def consume_invite_code(db: Session, code: str) -> bool:
    """注册时消费一个名额。命中并成功占位返回 True。

    **必须用带条件的 UPDATE 原子占位**：先 SELECT 再 +1 的写法下，
    两个人同时用最后一个名额会双双通过（检查与写入之间有窗口）。
    """
    code = (code or "").strip().upper()
    if not code:
        return False
    result = db.execute(
        update(TravelInviteCode)
        .where(
            TravelInviteCode.code == code,
            TravelInviteCode.active.is_(True),
            TravelInviteCode.used_count < TravelInviteCode.max_uses,
        )
        .values(used_count=TravelInviteCode.used_count + 1)
    )
    if result.rowcount:
        db.commit()
        return True
    db.rollback()
    return False


def invite_required(db: Session) -> bool:
    """是否需要邀请码：DB 里有任何码，或 .env 配了老钥匙。"""
    if (settings.register_invite_code or "").strip():
        return True
    n = db.execute(select(func.count()).select_from(TravelInviteCode)).scalar_one()
    return bool(n)


# ---------- 公告 ----------

class CreateAnnouncement(BaseModel):
    title: str
    content: str


@admin_manage_router.post("/announcements")
def publish(req: CreateAnnouncement, me: TravelUser = Depends(require_admin),
            db: Session = Depends(get_db)):
    title = (req.title or "").strip()
    content = (req.content or "").strip()
    if not title or not content:
        raise HTTPException(400, "标题和内容都不能为空")
    row = TravelAnnouncement(
        title=title[:128], content=content[: settings.announcement_max_chars],
        created_by=me.id)
    db.add(row)
    db.commit()
    return {"id": row.id, "title": row.title}


@admin_manage_router.delete("/announcements/{ann_id}")
def withdraw(ann_id: str, _: TravelUser = Depends(require_admin),
             db: Session = Depends(get_db)):
    row = db.get(TravelAnnouncement, ann_id)
    if row is None:
        raise HTTPException(404, "公告不存在")
    db.delete(row)
    db.execute(
        TravelAnnouncementRead.__table__.delete()
        .where(TravelAnnouncementRead.announcement_id == ann_id)
    )
    db.commit()
    return {"status": "ok"}


def _read_ids(db: Session, user_id: str) -> set[str]:
    return set(db.execute(
        select(TravelAnnouncementRead.announcement_id)
        .where(TravelAnnouncementRead.user_id == user_id)
    ).scalars().all())


@announce_router.get("")
def my_announcements(db: Session = Depends(get_db),
                     user: TravelUser = Depends(get_current_user)):
    rows = db.execute(
        select(TravelAnnouncement).order_by(TravelAnnouncement.created_at.desc()).limit(50)
    ).scalars().all()
    read = _read_ids(db, user.id)
    authors = {u.id: u.username for u in db.execute(
        select(TravelUser).where(TravelUser.id.in_([r.created_by for r in rows] or [""]))
    ).scalars().all()} if rows else {}
    return {"announcements": [
        {"id": r.id, "title": r.title, "content": r.content,
         "created_at": iso_utc(r.created_at), "read": r.id in read,
         "author": authors.get(r.created_by, "管理员")}
        for r in rows
    ]}


@announce_router.get("/unread")
def unread_count(db: Session = Depends(get_db),
                 user: TravelUser = Depends(get_current_user)):
    """未读靠推导（有公告 && 无已读行），发布公告不给每个用户复制一份。"""
    total = db.execute(select(func.count()).select_from(TravelAnnouncement)).scalar_one()
    read = db.execute(
        select(func.count()).select_from(TravelAnnouncementRead)
        .where(TravelAnnouncementRead.user_id == user.id)
    ).scalar_one()
    return {"unread": max(0, int(total) - int(read))}


@announce_router.post("/{ann_id}/read")
def mark_read(ann_id: str, db: Session = Depends(get_db),
              user: TravelUser = Depends(get_current_user)):
    if db.get(TravelAnnouncement, ann_id) is None:
        raise HTTPException(404, "公告不存在")
    exists = db.get(TravelAnnouncementRead, {"announcement_id": ann_id, "user_id": user.id})
    if exists is None:
        db.add(TravelAnnouncementRead(announcement_id=ann_id, user_id=user.id))
        db.commit()
    return {"status": "ok"}
