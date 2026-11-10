"""协同行程的协作模块（Phase 87）：美食 / 行李 / 避坑。

对应 PRD《好友协同旅游-高保真架构图-改造版》的模块 2 / 6 / 7。
（模块 5 任务分工、模块 8 相册按用户要求已删除。）
单独成文件是因为 `trip_api.py` 已 2100+ 行；路由前缀与它相同，对前端是同一套 API。

所有接口一律过 `trip_api._member()` 成员校验（非成员 404，不泄露行程存在性），
写操作复用 `_log_event` 落进已有的动态时间线。
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.trip_api import _log_event, _member, _touch, _trip_users
from app.db.models import (
    TravelTripFood,
    TravelTripPackingItem,
    TravelTripPackingState,
    TravelTripPoll,
    TravelTripPollVote,
    TravelTripTip,
    TravelUser,
)
from app.db.session import get_db

router = APIRouter(prefix="/api/trips", tags=["trips"])

FOOD_CATEGORIES = ("小吃", "正餐", "甜点", "饮品", "其他")
FOOD_MEALS = ("早餐", "午餐", "下午茶", "晚餐", "夜宵", "待定")
FOOD_STATUSES = ("planned", "checked_in")
PACKING_STATES = ("packed", "unpacked", "na")
TIP_LEVELS = ("important", "notice")


def _clean(text: str, limit: int) -> str:
    return (text or "").strip()[:limit]


# ---------- 模块 2：美食 ----------

class FoodBody(BaseModel):
    name: str
    day: int | None = None
    meal_type: str = "待定"
    category: str = "正餐"
    city: str = ""
    address: str = ""
    price: float | None = None
    rating: float | None = None
    business_hours: str = ""
    recommend_food: list[str] = []
    note: str = ""
    status: str = "planned"
    is_favorite: bool = False
    checked_in: bool = False
    is_top: bool = False


def _clean_food_list(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items or []:
        item = _clean(str(raw), 40)
        if item and item not in seen:
            seen.add(item)
            out.append(item)
        if len(out) >= 12:
            break
    return out


def _food_recommendations(f: TravelTripFood) -> list[str]:
    try:
        data = json.loads(f.recommend_food_json or "[]")
    except Exception:
        data = []
    if not isinstance(data, list):
        return []
    return [str(x) for x in data if str(x).strip()][:12]


def _food_dict(f: TravelTripFood, users: dict) -> dict:
    return {
        "id": f.id, "name": f.name, "day": f.day, "meal_type": f.meal_type or "待定",
        "category": f.category, "city": f.city, "address": f.address or "",
        "price": f.price, "rating": f.rating, "business_hours": f.business_hours or "",
        "recommend_food": _food_recommendations(f), "note": f.note,
        "status": f.status or "planned", "is_favorite": bool(f.is_favorite),
        "checked_in": bool(f.checked_in), "is_top": f.is_top,
        "created_by": users.get(f.created_by, ""),
    }


def _apply_food_body(f: TravelTripFood, body: FoodBody, trip_destination: str = "") -> None:
    name = _clean(body.name, 128)
    if not name:
        raise HTTPException(400, "写一下店名或菜名")
    cat = body.category.strip() or "正餐"
    meal = body.meal_type.strip() or "待定"
    status = body.status.strip() or "planned"
    f.name = name
    f.day = body.day if body.day and body.day > 0 else None
    f.meal_type = meal if meal in FOOD_MEALS else _clean(meal, 16)
    f.category = cat if cat in FOOD_CATEGORIES else _clean(cat, 24)
    f.city = _clean(body.city, 64) or trip_destination
    f.address = _clean(body.address, 200)
    f.price = round(body.price, 2) if body.price and body.price > 0 else None
    f.rating = round(body.rating, 1) if body.rating and 0 < body.rating <= 5 else None
    f.business_hours = _clean(body.business_hours, 80)
    f.recommend_food_json = json.dumps(_clean_food_list(body.recommend_food), ensure_ascii=False)
    f.note = _clean(body.note, 500)
    f.status = status if status in FOOD_STATUSES else "planned"
    f.is_favorite = bool(body.is_favorite)
    f.checked_in = bool(body.checked_in) or f.status == "checked_in"
    if f.checked_in:
        f.status = "checked_in"
    f.is_top = bool(body.is_top)


@router.get("/{trip_id}/foods")
def list_foods(trip_id: str, db: Session = Depends(get_db),
               user: TravelUser = Depends(get_current_user)):
    _member(db, trip_id, user)
    users = _trip_users(db, trip_id)
    rows = db.execute(
        select(TravelTripFood).where(TravelTripFood.trip_id == trip_id)
        # TOP 置顶，其余按加入时间——排序稳定，多人同时看到的顺序一致
        .order_by(TravelTripFood.is_top.desc(), TravelTripFood.created_at)
    ).scalars().all()
    return [_food_dict(f, users) for f in rows]


@router.post("/{trip_id}/foods")
def add_food(trip_id: str, body: FoodBody, db: Session = Depends(get_db),
             user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    f = TravelTripFood(
        trip_id=trip_id, created_by=user.id,
    )
    _apply_food_body(f, body, trip.destination or "")
    db.add(f)
    _log_event(db, trip_id, user, f"添加美食「{f.name}」")
    _touch(db, trip)
    db.commit()
    return _food_dict(f, _trip_users(db, trip_id))


@router.patch("/{trip_id}/foods/{food_id}")
def update_food(trip_id: str, food_id: str, body: FoodBody, db: Session = Depends(get_db),
                user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    f = db.get(TravelTripFood, food_id)
    if f is None or f.trip_id != trip_id:
        raise HTTPException(404, "记录不存在")
    _apply_food_body(f, body, trip.destination or "")
    _log_event(db, trip_id, user, f"修改美食「{f.name}」")
    _touch(db, trip)
    db.commit()
    return _food_dict(f, _trip_users(db, trip_id))


@router.delete("/{trip_id}/foods/{food_id}")
def delete_food(trip_id: str, food_id: str, db: Session = Depends(get_db),
                user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    f = db.get(TravelTripFood, food_id)
    if f is None or f.trip_id != trip_id:
        raise HTTPException(404, "记录不存在")
    _log_event(db, trip_id, user, f"删除美食「{f.name}」")
    db.delete(f)
    _touch(db, trip)
    db.commit()
    return {"ok": True}


# ---------- 模块 6：行李（行=物品，列=成员，三态格） ----------

PACKING_TEMPLATES = ("身份证/护照", "充电宝", "充电器", "洗漱包", "防晒霜",
                     "常用药", "雨伞", "换洗衣物", "转换插头", "拖鞋")


class PackingItemBody(BaseModel):
    name: str
    category: str = "通用"


class PackingStateBody(BaseModel):
    state: str
    member: str = ""  # 要改谁那一格；留空 = 自己


@router.get("/{trip_id}/packing")
def list_packing(trip_id: str, db: Session = Depends(get_db),
                 user: TravelUser = Depends(get_current_user)):
    _member(db, trip_id, user)
    users = _trip_users(db, trip_id)
    items = db.execute(
        select(TravelTripPackingItem).where(TravelTripPackingItem.trip_id == trip_id)
        .order_by(TravelTripPackingItem.order_no, TravelTripPackingItem.created_at)
    ).scalars().all()
    states = db.execute(
        select(TravelTripPackingState).where(TravelTripPackingState.trip_id == trip_id)
    ).scalars().all()
    by_item: dict[str, dict[str, str]] = {}
    marked_by: dict[str, dict[str, str]] = {}
    for s in states:
        # 只回本行程现有成员的格子：成员退出后旧格子不该继续占一列
        if s.user_id not in users:
            continue
        owner = users[s.user_id]
        by_item.setdefault(s.item_id, {})[owner] = s.state
        # 代勾才回 updated_by：自己勾自己是常态，没必要每格都带一份冗余数据
        if s.updated_by and s.updated_by != s.user_id and s.updated_by in users:
            marked_by.setdefault(s.item_id, {})[owner] = users[s.updated_by]
    return {
        "members": list(users.values()),
        "items": [{
            "id": i.id, "name": i.name, "category": i.category,
            "states": by_item.get(i.id, {}),
            "marked_by": marked_by.get(i.id, {}),
        } for i in items],
        "templates": list(PACKING_TEMPLATES),
    }


@router.post("/{trip_id}/packing")
def add_packing_item(trip_id: str, body: PackingItemBody, db: Session = Depends(get_db),
                     user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    name = _clean(body.name, 80)
    if not name:
        raise HTTPException(400, "写一下物品名")
    order = db.execute(
        select(TravelTripPackingItem).where(TravelTripPackingItem.trip_id == trip_id)
    ).scalars().all()
    item = TravelTripPackingItem(
        trip_id=trip_id, name=name, category=_clean(body.category, 24) or "通用",
        order_no=len(order) + 1,
    )
    db.add(item)
    _log_event(db, trip_id, user, f"添加行李「{name}」")
    _touch(db, trip)
    db.commit()
    return {"id": item.id, "name": item.name, "category": item.category, "states": {}}


@router.put("/{trip_id}/packing/{item_id}/state")
def set_packing_state(trip_id: str, item_id: str, body: PackingStateBody,
                      db: Session = Depends(get_db),
                      user: TravelUser = Depends(get_current_user)):
    """设置某个成员那一格的状态。`member` 留空 = 改自己那格。

    **允许代别人勾**：出发前一个人拿着清单统一核对是真实场景。留下 `updated_by`，
    被代勾的人能看到是谁改的，不至于对不上账。目标必须是本行程成员。
    """
    trip = _member(db, trip_id, user)
    item = db.get(TravelTripPackingItem, item_id)
    if item is None or item.trip_id != trip_id:
        raise HTTPException(404, "物品不存在")
    if body.state not in PACKING_STATES:
        raise HTTPException(400, "状态非法")

    target_id = user.id
    if body.member.strip():
        users = _trip_users(db, trip_id)
        target_id = next((uid for uid, n in users.items() if n == body.member.strip()), "")
        if not target_id:
            raise HTTPException(400, "这个人不在本行程里")

    row = db.get(TravelTripPackingState, (item_id, target_id))
    if row is None:
        row = TravelTripPackingState(item_id=item_id, user_id=target_id, trip_id=trip_id)
        db.add(row)
    row.state = body.state
    row.updated_by = user.id
    _touch(db, trip)
    db.commit()  # 不写 event：三态点击是高频操作，会把动态时间线刷爆
    return {"item_id": item_id, "state": row.state,
            "by_other": target_id != user.id}


class PackingPatchBody(BaseModel):
    name: str = ""
    category: str = ""


@router.patch("/{trip_id}/packing/{item_id}")
def update_packing_item(trip_id: str, item_id: str, body: PackingPatchBody,
                        db: Session = Depends(get_db),
                        user: TravelUser = Depends(get_current_user)):
    """改物品名或分类。分类管理（重命名/合并）就是对一批物品逐个调这个接口。"""
    trip = _member(db, trip_id, user)
    item = db.get(TravelTripPackingItem, item_id)
    if item is None or item.trip_id != trip_id:
        raise HTTPException(404, "物品不存在")
    if body.name.strip():
        item.name = _clean(body.name, 80)
    if body.category.strip():
        item.category = _clean(body.category, 24)
    _touch(db, trip)
    db.commit()
    return {"id": item.id, "name": item.name, "category": item.category}


@router.delete("/{trip_id}/packing/{item_id}")
def delete_packing_item(trip_id: str, item_id: str, db: Session = Depends(get_db),
                        user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    item = db.get(TravelTripPackingItem, item_id)
    if item is None or item.trip_id != trip_id:
        raise HTTPException(404, "物品不存在")
    db.execute(delete(TravelTripPackingState).where(TravelTripPackingState.item_id == item_id))
    _log_event(db, trip_id, user, f"删除行李「{item.name}」")
    db.delete(item)
    _touch(db, trip)
    db.commit()
    return {"ok": True}


# ---------- 模块 7：避坑 ----------

class TipBody(BaseModel):
    content: str
    level: str = "notice"


def _tip_dict(t: TravelTripTip, users: dict) -> dict:
    return {"id": t.id, "content": t.content, "level": t.level,
            "created_by": users.get(t.created_by, "")}


@router.get("/{trip_id}/tips")
def list_tips(trip_id: str, db: Session = Depends(get_db),
              user: TravelUser = Depends(get_current_user)):
    _member(db, trip_id, user)
    users = _trip_users(db, trip_id)
    rows = db.execute(
        select(TravelTripTip).where(TravelTripTip.trip_id == trip_id)
        # important 在前：重要提示不该被后加的普通提醒挤到下面
        .order_by(TravelTripTip.level, TravelTripTip.created_at)
    ).scalars().all()
    return [_tip_dict(t, users) for t in rows]


@router.post("/{trip_id}/tips")
def add_tip(trip_id: str, body: TipBody, db: Session = Depends(get_db),
            user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    content = _clean(body.content, 300)
    if not content:
        raise HTTPException(400, "写一下要提醒什么")
    t = TravelTripTip(
        trip_id=trip_id, content=content,
        level=body.level if body.level in TIP_LEVELS else "notice", created_by=user.id,
    )
    db.add(t)
    _log_event(db, trip_id, user, "添加避坑提示")
    _touch(db, trip)
    db.commit()
    return _tip_dict(t, _trip_users(db, trip_id))


@router.patch("/{trip_id}/tips/{tip_id}")
def update_tip(trip_id: str, tip_id: str, body: TipBody, db: Session = Depends(get_db),
               user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    t = db.get(TravelTripTip, tip_id)
    if t is None or t.trip_id != trip_id:
        raise HTTPException(404, "记录不存在")
    content = _clean(body.content, 300)
    if not content:
        raise HTTPException(400, "写一下要提醒什么")
    t.content = content
    t.level = body.level if body.level in TIP_LEVELS else t.level
    _log_event(db, trip_id, user, "修改避坑提示")
    _touch(db, trip)
    db.commit()
    return _tip_dict(t, _trip_users(db, trip_id))


@router.delete("/{trip_id}/tips/{tip_id}")
def delete_tip(trip_id: str, tip_id: str, db: Session = Depends(get_db),
               user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    t = db.get(TravelTripTip, tip_id)
    if t is None or t.trip_id != trip_id:
        raise HTTPException(404, "记录不存在")
    _log_event(db, trip_id, user, "删除避坑提示")
    db.delete(t)
    _touch(db, trip)
    db.commit()
    return {"ok": True}


# ---------- 同行人投票（2026-11-10） ----------

class PollBody(BaseModel):
    question: str
    options: list[str]
    day: int | None = None   # 第几天；不填 = 关于整趟行程


class VoteBody(BaseModel):
    option: int


def _poll_dict(db: Session, poll: TravelTripPoll, users: dict[str, str], me: str) -> dict:
    options = json.loads(poll.options_json or "[]")
    votes = db.execute(select(TravelTripPollVote).where(TravelTripPollVote.poll_id == poll.id)).scalars().all()
    voters: list[list[str]] = [[] for _ in options]
    mine = None
    for v in votes:
        if v.user_id not in users or not 0 <= v.option_idx < len(options):
            continue  # 已退出行程的人的票不再计入
        voters[v.option_idx].append(users[v.user_id])
        if v.user_id == me:
            mine = v.option_idx
    return {
        "id": poll.id, "question": poll.question, "closed": bool(poll.closed), "day": poll.day,
        "options": [{"text": text, "votes": len(voters[i]), "voters": voters[i]} for i, text in enumerate(options)],
        "my_vote": mine, "total": sum(len(v) for v in voters), "members": len(users),
        "created_by": users.get(poll.created_by, ""), "mine": poll.created_by == me,
        "created_at": poll.created_at.isoformat() if poll.created_at else "",
    }


def _poll(db: Session, trip_id: str, poll_id: str) -> TravelTripPoll:
    poll = db.get(TravelTripPoll, poll_id)
    if poll is None or poll.trip_id != trip_id:
        raise HTTPException(404, "投票不存在")
    return poll


@router.get("/{trip_id}/polls")
def list_polls(trip_id: str, db: Session = Depends(get_db),
               user: TravelUser = Depends(get_current_user)):
    _member(db, trip_id, user)
    users = _trip_users(db, trip_id)
    rows = db.execute(
        select(TravelTripPoll).where(TravelTripPoll.trip_id == trip_id)
        .order_by(TravelTripPoll.closed, TravelTripPoll.created_at.desc())  # 进行中的在前
    ).scalars().all()
    return [_poll_dict(db, r, users, user.id) for r in rows]


@router.post("/{trip_id}/polls")
def create_poll(trip_id: str, body: PollBody, db: Session = Depends(get_db),
                user: TravelUser = Depends(get_current_user)):
    from app.api.notification_api import upsert_notification

    trip = _member(db, trip_id, user)
    question = _clean(body.question, 120)
    options: list[str] = []
    for raw in body.options:
        text = _clean(raw, 60)
        if text and text not in options:
            options.append(text)
    if not question:
        raise HTTPException(400, "写一下要大家决定什么")
    if not 2 <= len(options) <= 4:
        raise HTTPException(400, "需要 2 到 4 个不重复的选项")
    # 天数越界（行程后来缩短了等）就当成整趟行程的投票，不让发起失败
    day = body.day if body.day is not None and 1 <= body.day <= max(1, trip.days or 1) else None
    poll = TravelTripPoll(trip_id=trip_id, question=question, day=day,
                          options_json=json.dumps(options, ensure_ascii=False), created_by=user.id)
    db.add(poll)
    db.flush()
    _log_event(db, trip_id, user, f"发起投票「{question[:30]}」")
    _touch(db, trip)
    users = _trip_users(db, trip_id)
    actor = (user.display_name or user.username or "同行者").strip()
    for member_id in users:
        if member_id == user.id:
            continue
        upsert_notification(  # 与投票同事务：投票建了通知没落，或反过来，都比一起失败难查
            db, user_id=member_id, actor_id=user.id, type="trip_poll",
            title=f"{actor} 发起了投票", body=(f"第 {day} 天：" if day else "") + question[:80],
            target_kind="trip", target_id=trip_id,
            dedupe_key=f"trip-poll:{poll.id}:{member_id}",
            meta={"trip_id": trip_id, "poll_id": poll.id, "trip_title": trip.title or "", "day": day},
        )
    db.commit()
    return _poll_dict(db, poll, users, user.id)


@router.post("/{trip_id}/polls/{poll_id}/vote")
def vote_poll(trip_id: str, poll_id: str, body: VoteBody, db: Session = Depends(get_db),
              user: TravelUser = Depends(get_current_user)):
    _member(db, trip_id, user)
    poll = _poll(db, trip_id, poll_id)
    if poll.closed:
        raise HTTPException(400, "投票已结束")
    if not 0 <= body.option < len(json.loads(poll.options_json or "[]")):
        raise HTTPException(400, "没有这个选项")
    vote = db.get(TravelTripPollVote, (poll_id, user.id))
    if vote is None:
        db.add(TravelTripPollVote(poll_id=poll_id, user_id=user.id, option_idx=body.option))
    else:
        vote.option_idx = body.option
    db.commit()  # 投票不写 event：高频点击会刷爆时间线（同行李三态）
    return _poll_dict(db, poll, _trip_users(db, trip_id), user.id)


@router.post("/{trip_id}/polls/{poll_id}/close")
def close_poll(trip_id: str, poll_id: str, db: Session = Depends(get_db),
               user: TravelUser = Depends(get_current_user)):
    trip = _member(db, trip_id, user)
    poll = _poll(db, trip_id, poll_id)
    if user.id not in {poll.created_by, trip.owner_id}:
        raise HTTPException(403, "只有发起人或行程创建者可以结束投票")
    poll.closed = True
    _log_event(db, trip_id, user, f"结束投票「{poll.question[:30]}」")
    db.commit()
    return _poll_dict(db, poll, _trip_users(db, trip_id), user.id)


@router.delete("/{trip_id}/polls/{poll_id}")
def delete_poll(trip_id: str, poll_id: str, db: Session = Depends(get_db),
                user: TravelUser = Depends(get_current_user)):
    from app.db.models import TravelNotification

    trip = _member(db, trip_id, user)
    poll = _poll(db, trip_id, poll_id)
    if user.id not in {poll.created_by, trip.owner_id}:
        raise HTTPException(403, "只有发起人或行程创建者可以删除投票")
    db.execute(delete(TravelTripPollVote).where(TravelTripPollVote.poll_id == poll_id))
    db.execute(delete(TravelNotification).where(TravelNotification.dedupe_key.like(f"trip-poll:{poll_id}:%")))
    db.delete(poll)
    db.commit()
    return {"ok": True}
