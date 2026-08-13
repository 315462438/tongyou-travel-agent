"""登录 / 注册（Phase 15）"""

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, is_online, iso_utc, require_admin
from app.auth import hash_password, new_token, verify_password
from app.config import settings
from app.db.models import (
    TravelConversation,
    TravelMemory,
    TravelSession,
    TravelUser,
)
from app.db.session import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_一-龥]{2,20}$")


class AuthRequest(BaseModel):
    username: str
    password: str
    invite_code: str = ""  # Phase 70：注册邀请码（登录时忽略）


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


_DEFAULT_ADMIN_PASSWORD = "admin123"  # config.py 的引导默认口令


def _must_change_password(user: TravelUser) -> bool:
    """Phase 51 批6（P1 安全）：admin 仍在用引导默认口令 → 前端强提示改密。"""
    return bool(user.is_admin) and verify_password(_DEFAULT_ADMIN_PASSWORD, user.password_hash)


def _issue(db: Session, user: TravelUser) -> dict:
    token = new_token()
    db.add(TravelSession(token=token, user_id=user.id))
    db.commit()
    return {"token": token, "username": user.username, "is_admin": user.is_admin,
            "display_name": user.display_name or user.username,
            "avatar_url": f"/travel/api/uploads/{user.avatar_upload_id}" if user.avatar_upload_id else "",
            "must_change_password": _must_change_password(user)}


@router.post("/register")
def register(req: AuthRequest, db: Session = Depends(get_db)):
    # Phase 70：邀请码注册。资源模型本来就不支持公开流量（浏览器池 2 个槽、
    # 小红书共享单账号、LLM 账单按用量走），且注册即拿到沙箱执行 + 深度研究。
    # 留空 = 不校验（本地开发默认；线上在 .env 配 REGISTER_INVITE_CODE 开启）。
    # Phase 74：邀请码改由管理员在后台生成（每码限量）。校验顺序刻意做成**兼容优先**：
    #   ① DB 里有 active 且未用满的码 → 命中即原子占位
    #   ② 否则回退 .env 的老钥匙（存量部署不受影响）
    #   ③ 两者都没配 → 开放注册（本地开发行为不变）
    from app.api.admin_api import consume_invite_code, invite_required

    supplied = req.invite_code.strip()
    if invite_required(db):
        env_code = (settings.register_invite_code or "").strip()
        if not (consume_invite_code(db, supplied) or (env_code and supplied == env_code)):
            raise HTTPException(
                403, "邀请码无效或已用完。目前为邀请注册，可以找邀请你的朋友或管理员要一个新的邀请码")

    username = req.username.strip()
    if not _USERNAME_RE.match(username):
        raise HTTPException(400, "用户名需 2-20 位，仅限中英文、数字、下划线")
    if len(req.password) < 6:
        raise HTTPException(400, "密码至少 6 位")
    if db.execute(select(TravelUser).where(TravelUser.username == username)).scalar_one_or_none():
        raise HTTPException(409, "该用户名已被注册")
    user = TravelUser(username=username, password_hash=hash_password(req.password))
    db.add(user)
    db.commit()
    return _issue(db, user)


@router.post("/login")
def login(req: AuthRequest, db: Session = Depends(get_db)):
    user = db.execute(
        select(TravelUser).where(TravelUser.username == req.username.strip())
    ).scalar_one_or_none()
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "用户名或密码不对")
    return _issue(db, user)


@router.get("/me")
def me(user: TravelUser = Depends(get_current_user)):
    return {"username": user.username, "is_admin": user.is_admin,
            "display_name": user.display_name or user.username,
            "avatar_url": f"/travel/api/uploads/{user.avatar_upload_id}" if user.avatar_upload_id else "",
            "must_change_password": _must_change_password(user)}


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, db: Session = Depends(get_db),
                    user: TravelUser = Depends(get_current_user)):
    """改密（Phase 51 批6）：校验旧口令，设新口令。admin 借此摆脱默认口令。"""
    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(400, "原密码不对")
    if len(req.new_password) < 6:
        raise HTTPException(400, "新密码至少 6 位")
    if req.new_password == _DEFAULT_ADMIN_PASSWORD and user.is_admin:
        raise HTTPException(400, "新密码不能仍是默认口令，请换一个")
    user.password_hash = hash_password(req.new_password)
    # 改密后使其它会话失效（安全），保留当前 token 不强制重登
    db.query(TravelSession).filter(TravelSession.user_id == user.id).delete()
    db.commit()
    return _issue(db, user)


@router.post("/logout")
def logout(authorization: str | None = None, db: Session = Depends(get_db),
           user: TravelUser = Depends(get_current_user)):
    # 删除该用户全部会话令牌（简单起见整体登出）
    db.query(TravelSession).filter(TravelSession.user_id == user.id).delete()
    db.commit()
    return {"status": "ok"}


@admin_router.get("/users")
def list_users(_: TravelUser = Depends(require_admin), db: Session = Depends(get_db)):
    """管理员：注册用户列表 + 每人会话/记忆计数。"""
    users = db.execute(select(TravelUser).order_by(TravelUser.created_at)).scalars().all()
    conv_counts = dict(db.execute(
        select(TravelConversation.user_id, func.count()).group_by(TravelConversation.user_id)
    ).all())
    mem_counts = dict(db.execute(
        select(TravelMemory.user_id, func.count()).group_by(TravelMemory.user_id)
    ).all())
    return {
        "total": len(users),
        "users": [
            {
                "id": u.id,  # Phase 73：admin 侧要用它开客服会话
                "username": u.username, "is_admin": u.is_admin,
                "conversations": conv_counts.get(u.id, 0),
                "memories": mem_counts.get(u.id, 0),
                "created_at": u.created_at.isoformat() if u.created_at else None,
                # 在线判定由服务端给，前端不重算阈值（两端各判一次必然漂移）
                "last_seen_at": iso_utc(u.last_seen_at),
                "online": is_online(u.last_seen_at),
            }
            for u in users
        ],
    }
