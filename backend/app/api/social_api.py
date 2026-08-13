"""目的地接力站、好友与个人主页（Phase 81）。

公开只表示“对已登录的 17同游用户公开”。任何响应都走字段白名单，绝不序列化 ORM 对象，
避免密码哈希、管理员身份、last_seen 等账号字段进入社交面。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.notification_api import (
    delete_notification,
    delete_target_notifications,
    upsert_notification,
)
from app.db.models import (
    TravelFriendship,
    TravelRelayPost,
    TravelRelayReaction,
    TravelUpload,
    TravelUser,
)
from app.db.session import get_db

router = APIRouter(prefix="/api/social", tags=["social"])

PHASES = {"planning", "on_trip", "returned"}
KINDS = {"condition", "route", "question"}
REACTIONS = {"useful", "verified", "outdated"}


class ProfileUpdate(BaseModel):
    display_name: str = Field(default="", max_length=40)
    bio: str = Field(default="", max_length=240)
    home_city: str = Field(default="", max_length=64)
    travel_styles: list[str] = Field(default_factory=list, max_length=6)
    profile_public: bool = True
    avatar_upload_id: str | None = Field(default=None, max_length=32)


class FriendResponse(BaseModel):
    accept: bool


class RelayCreate(BaseModel):
    destination: str = Field(min_length=1, max_length=64)
    phase: str = Field(max_length=16)
    kind: str = Field(max_length=16)
    content: str = Field(min_length=2, max_length=1000)


class ReactionRequest(BaseModel):
    reaction: str = Field(max_length=16)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _styles(user: TravelUser) -> list[str]:
    try:
        rows = json.loads(user.travel_styles_json or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item)[:16] for item in rows if str(item).strip()][:6]


def _avatar(user: TravelUser) -> str:
    return f"/travel/api/uploads/{user.avatar_upload_id}" if user.avatar_upload_id else ""


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _user_card(user: TravelUser) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": (user.display_name or user.username).strip(),
        "avatar_url": _avatar(user),
        "bio": user.bio or "",
        "home_city": user.home_city or "",
        "travel_styles": _styles(user),
    }


def _friend_count(db: Session, user_id: str) -> int:
    return int(db.scalar(select(func.count()).select_from(TravelFriendship).where(
        TravelFriendship.status == "accepted",
        or_(TravelFriendship.user_low_id == user_id, TravelFriendship.user_high_id == user_id),
    )) or 0)


def _profile(db: Session, user: TravelUser, own: bool = False) -> dict:
    data = _user_card(user)
    post_count = int(db.scalar(select(func.count()).select_from(TravelRelayPost).where(
        TravelRelayPost.user_id == user.id)) or 0)
    verified_count = int(db.scalar(
        select(func.count()).select_from(TravelRelayReaction)
        .join(TravelRelayPost, TravelRelayPost.id == TravelRelayReaction.post_id)
        .where(TravelRelayPost.user_id == user.id, TravelRelayReaction.reaction == "verified")
    ) or 0)
    data.update({
        "profile_public": bool(user.profile_public),
        "stats": {
            "relay_posts": post_count,
            "verified": verified_count,
            "friends": _friend_count(db, user.id),
        },
        "recent_relay": [
            {
                "id": post.id,
                "destination": post.destination,
                "phase": post.phase,
                "kind": post.kind,
                "content": post.content,
                "created_at": _aware(post.created_at).isoformat(),
            }
            for post in db.execute(
                select(TravelRelayPost)
                .where(TravelRelayPost.user_id == user.id)
                .order_by(TravelRelayPost.created_at.desc())
                .limit(6)
            ).scalars().all()
        ],
    })
    if own:
        data["avatar_upload_id"] = user.avatar_upload_id or ""
    return data


def _get_friendship(db: Session, a: str, b: str) -> TravelFriendship | None:
    low, high = _pair(a, b)
    return db.execute(select(TravelFriendship).where(
        TravelFriendship.user_low_id == low,
        TravelFriendship.user_high_id == high,
    )).scalar_one_or_none()


@router.get("/me")
def my_profile(db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    return _profile(db, user, own=True)


@router.patch("/me")
def update_profile(req: ProfileUpdate, db: Session = Depends(get_db),
                   user: TravelUser = Depends(get_current_user)):
    avatar_id = (req.avatar_upload_id or "").strip() or None
    if avatar_id:
        upload = db.get(TravelUpload, avatar_id)
        if upload is None or upload.user_id != user.id:
            raise HTTPException(400, "头像图片不存在或不属于当前账号")

    clean_styles: list[str] = []
    for item in req.travel_styles:
        value = " ".join(str(item).strip().split())[:16]
        if value and value not in clean_styles:
            clean_styles.append(value)
    user.display_name = " ".join(req.display_name.strip().split())[:40] or None
    user.bio = req.bio.strip()[:240] or None
    user.home_city = " ".join(req.home_city.strip().split())[:64] or None
    user.travel_styles_json = json.dumps(clean_styles[:6], ensure_ascii=False)
    user.profile_public = bool(req.profile_public)
    user.avatar_upload_id = avatar_id
    db.commit()
    return _profile(db, user, own=True)


@router.get("/users")
def search_users(q: str = Query(default="", max_length=40), db: Session = Depends(get_db),
                 user: TravelUser = Depends(get_current_user)):
    stmt = select(TravelUser).where(
        TravelUser.id != user.id,
        TravelUser.profile_public.is_(True),
    )
    query = q.strip()
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(or_(
            TravelUser.username.ilike(pattern),
            TravelUser.display_name.ilike(pattern),
            TravelUser.home_city.ilike(pattern),
        ))
    users = db.execute(stmt.order_by(TravelUser.last_seen_at.desc().nullslast()).limit(20)).scalars().all()
    result = []
    for row in users:
        card = _user_card(row)
        friendship = _get_friendship(db, user.id, row.id)
        card.update({
            "friendship_id": friendship.id if friendship else "",
            "friendship_status": friendship.status if friendship else "none",
            "requester_id": friendship.requester_id if friendship else "",
        })
        result.append(card)
    return {"users": result}


@router.get("/users/{user_id}")
def public_profile(user_id: str, db: Session = Depends(get_db),
                   user: TravelUser = Depends(get_current_user)):
    target = db.get(TravelUser, user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    friendship = _get_friendship(db, user.id, target.id) if target.id != user.id else None
    is_friend = bool(friendship and friendship.status == "accepted")
    if target.id != user.id and not target.profile_public and not is_friend:
        raise HTTPException(404, "用户主页不可见")
    data = _profile(db, target, own=target.id == user.id)
    data.update({
        "friendship_id": friendship.id if friendship else "",
        "friendship_status": friendship.status if friendship else ("self" if target.id == user.id else "none"),
        "requester_id": friendship.requester_id if friendship else "",
    })
    return data


@router.get("/friends")
def list_friends(db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    rows = db.execute(select(TravelFriendship).where(or_(
        TravelFriendship.user_low_id == user.id,
        TravelFriendship.user_high_id == user.id,
    )).order_by(TravelFriendship.updated_at.desc())).scalars().all()
    groups: dict[str, list[dict]] = {"friends": [], "received": [], "sent": []}
    for row in rows:
        other_id = row.user_high_id if row.user_low_id == user.id else row.user_low_id
        other = db.get(TravelUser, other_id)
        if other is None:
            continue
        item = {**_user_card(other), "friendship_id": row.id, "requester_id": row.requester_id}
        if row.status == "accepted":
            groups["friends"].append(item)
        elif row.status == "pending" and row.requester_id == user.id:
            groups["sent"].append(item)
        elif row.status == "pending":
            groups["received"].append(item)
    return groups


@router.post("/friends/request/{user_id}")
def request_friend(user_id: str, db: Session = Depends(get_db),
                   user: TravelUser = Depends(get_current_user)):
    if user_id == user.id:
        raise HTTPException(400, "不能添加自己为好友")
    target = db.get(TravelUser, user_id)
    if target is None or not target.profile_public:
        raise HTTPException(404, "用户不存在或主页未公开")
    row = _get_friendship(db, user.id, user_id)
    now = _now()
    if row and row.status in {"pending", "accepted"}:
        raise HTTPException(409, "好友申请或好友关系已经存在")
    if row:
        row.requester_id = user.id
        row.status = "pending"
        row.updated_at = now
    else:
        low, high = _pair(user.id, user_id)
        row = TravelFriendship(
            user_low_id=low, user_high_id=high, requester_id=user.id,
            status="pending", created_at=now, updated_at=now,
        )
        db.add(row)
    low, high = _pair(user.id, user_id)
    actor_name = (user.display_name or user.username).strip()
    upsert_notification(
        db,
        user_id=target.id,
        actor_id=user.id,
        type="friend_request",
        title=f"{actor_name} 想加你为好友",
        body="你们可以在同游圈保持联系；好友不会自动看到私人行程。",
        target_kind="friends",
        target_id=user.id,
        dedupe_key=f"friend-request:{low}:{high}",
        meta={"tab": "friends"},
    )
    db.commit()
    return {"id": row.id, "status": row.status}


@router.post("/friends/{friendship_id}/respond")
def respond_friend(friendship_id: str, req: FriendResponse, db: Session = Depends(get_db),
                   user: TravelUser = Depends(get_current_user)):
    row = db.get(TravelFriendship, friendship_id)
    if row is None or user.id not in {row.user_low_id, row.user_high_id}:
        raise HTTPException(404, "好友申请不存在")
    if row.status != "pending" or row.requester_id == user.id:
        raise HTTPException(409, "当前申请不能由你处理")
    delete_notification(db, f"friend-request:{row.user_low_id}:{row.user_high_id}")
    row.status = "accepted" if req.accept else "rejected"
    row.updated_at = _now()
    if req.accept:
        actor_name = (user.display_name or user.username).strip()
        upsert_notification(
            db,
            user_id=row.requester_id,
            actor_id=user.id,
            type="friend_accepted",
            title=f"{actor_name} 接受了你的好友申请",
            body="你们现在已经是好友了，可以继续查看对方的旅行主页。",
            target_kind="friends",
            target_id=user.id,
            dedupe_key=f"friend-accepted:{row.user_low_id}:{row.user_high_id}",
            meta={"tab": "friends"},
        )
    db.commit()
    return {"id": row.id, "status": row.status}


@router.delete("/friends/{friendship_id}")
def remove_friend(friendship_id: str, db: Session = Depends(get_db),
                  user: TravelUser = Depends(get_current_user)):
    row = db.get(TravelFriendship, friendship_id)
    if row is None or user.id not in {row.user_low_id, row.user_high_id}:
        raise HTTPException(404, "好友关系不存在")
    delete_notification(db, f"friend-request:{row.user_low_id}:{row.user_high_id}")
    db.delete(row)
    db.commit()
    return {"status": "ok"}


def _reaction_counts(db: Session, post_id: str) -> dict[str, int]:
    rows = db.execute(
        select(TravelRelayReaction.reaction, func.count())
        .where(TravelRelayReaction.post_id == post_id)
        .group_by(TravelRelayReaction.reaction)
    ).all()
    counts = {name: 0 for name in REACTIONS}
    counts.update({name: int(count) for name, count in rows})
    return counts


def _post_card(db: Session, post: TravelRelayPost, author: TravelUser, viewer_id: str) -> dict:
    own_reaction = db.execute(select(TravelRelayReaction).where(
        TravelRelayReaction.post_id == post.id,
        TravelRelayReaction.user_id == viewer_id,
    )).scalar_one_or_none()
    expires = _aware(post.expires_at)
    return {
        "id": post.id,
        "destination": post.destination,
        "phase": post.phase,
        "kind": post.kind,
        "content": post.content,
        "expires_at": expires.isoformat() if expires else None,
        "expired": bool(expires and expires <= _now()),
        "created_at": _aware(post.created_at).isoformat(),
        "author": _user_card(author),
        "mine": post.user_id == viewer_id,
        "reactions": _reaction_counts(db, post.id),
        "my_reaction": own_reaction.reaction if own_reaction else "",
    }


@router.get("/station")
def station(destination: str = Query(default="天堂寨", min_length=1, max_length=64),
            phase: str = Query(default="", max_length=16),
            db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    dest = " ".join(destination.strip().split())[:64]
    stmt = select(TravelRelayPost).where(TravelRelayPost.destination == dest)
    if phase:
        if phase not in PHASES:
            raise HTTPException(400, "未知旅行阶段")
        stmt = stmt.where(TravelRelayPost.phase == phase)
    posts = db.execute(stmt.order_by(TravelRelayPost.created_at.desc()).limit(80)).scalars().all()
    cards = []
    for post in posts:
        author = db.get(TravelUser, post.user_id)
        if author is None or (not author.profile_public and author.id != user.id):
            continue
        cards.append(_post_card(db, post, author, user.id))
    counts = dict(db.execute(
        select(TravelRelayPost.phase, func.count())
        .join(TravelUser, TravelUser.id == TravelRelayPost.user_id)
        .where(TravelRelayPost.destination == dest)
        .where(or_(TravelUser.profile_public.is_(True), TravelUser.id == user.id))
        .group_by(TravelRelayPost.phase)
    ).all())
    return {
        "destination": dest,
        "posts": cards,
        "phase_counts": {name: int(counts.get(name, 0)) for name in PHASES},
    }


@router.post("/posts")
def create_post(req: RelayCreate, db: Session = Depends(get_db),
                user: TravelUser = Depends(get_current_user)):
    if req.phase not in PHASES:
        raise HTTPException(400, "未知旅行阶段")
    if req.kind not in KINDS:
        raise HTTPException(400, "未知接力内容类型")
    destination = " ".join(req.destination.strip().split())[:64]
    content = req.content.strip()
    if not destination or len(content) < 2:
        raise HTTPException(400, "请填写目的地和接力内容")
    expires = _now() + timedelta(hours=72) if req.kind == "condition" else None
    post = TravelRelayPost(
        user_id=user.id, destination=destination, phase=req.phase,
        kind=req.kind, content=content[:1000], expires_at=expires,
    )
    db.add(post)
    db.commit()
    return _post_card(db, post, user, user.id)


@router.post("/posts/{post_id}/react")
def react_post(post_id: str, req: ReactionRequest, db: Session = Depends(get_db),
               user: TravelUser = Depends(get_current_user)):
    if req.reaction not in REACTIONS:
        raise HTTPException(400, "未知反馈类型")
    post = db.get(TravelRelayPost, post_id)
    if post is None:
        raise HTTPException(404, "接力内容不存在")
    if post.user_id == user.id:
        raise HTTPException(400, "不能给自己的接力内容做验证")
    row = db.execute(select(TravelRelayReaction).where(
        TravelRelayReaction.post_id == post_id,
        TravelRelayReaction.user_id == user.id,
    )).scalar_one_or_none()
    notification_key = f"relay-reaction:{post_id}:{user.id}"
    toggled_off = bool(row and row.reaction == req.reaction)
    if toggled_off:
        db.delete(row)  # 再点一次 = 取消
        delete_notification(db, notification_key)
    elif row:
        row.reaction = req.reaction
    else:
        db.add(TravelRelayReaction(post_id=post_id, user_id=user.id, reaction=req.reaction))
    if not toggled_off:
        reaction_title = {
            "useful": "觉得你的接力很有用",
            "verified": "验证了你的接力内容",
            "outdated": "提醒你的接力可能已失效",
        }[req.reaction]
        actor_name = (user.display_name or user.username).strip()
        upsert_notification(
            db,
            user_id=post.user_id,
            actor_id=user.id,
            type="relay_reaction",
            title=f"{actor_name} {reaction_title}",
            body=f"{post.destination} · {post.content[:120]}",
            target_kind="relay",
            target_id=post.id,
            dedupe_key=notification_key,
            meta={"destination": post.destination, "reaction": req.reaction},
        )
    db.commit()
    return {"reactions": _reaction_counts(db, post_id)}


@router.delete("/posts/{post_id}")
def delete_post(post_id: str, db: Session = Depends(get_db),
                user: TravelUser = Depends(get_current_user)):
    post = db.get(TravelRelayPost, post_id)
    if post is None or post.user_id != user.id:
        raise HTTPException(404, "接力内容不存在")
    delete_target_notifications(db, "relay", post_id)
    db.query(TravelRelayReaction).filter(TravelRelayReaction.post_id == post_id).delete()
    db.delete(post)
    db.commit()
    return {"status": "ok"}
