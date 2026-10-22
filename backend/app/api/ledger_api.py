"""独立个人旅行记账：整数分、逐币种汇总、UUID 幂等新增。"""
import logging
from collections import defaultdict
from datetime import date, timedelta, timezone
import secrets
from typing import Literal
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import TravelLedger, TravelLedgerEntry, TravelLedgerMember, TravelLedgerShare, TravelTrip, TravelTripMember, TravelUser, _now
from app.db.session import get_db

router = APIRouter(prefix="/api/ledger", tags=["ledger"])
logger = logging.getLogger(__name__)
CURRENCIES = {"CNY", "MYR", "SGD", "USD", "EUR", "JPY", "HKD", "THB", "KRW", "GBP", "AUD", "TWD", "VND", "IDR"}
CATEGORIES = {"餐饮", "交通", "住宿", "门票", "购物", "其他"}


class BookBody(BaseModel):
    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("请输入名称")
        return value


class LinkedBookBody(BookBody):
    trip_id: str | None = Field(default=None, min_length=1, max_length=32)


class EntryBody(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    version: int | None = Field(default=None, ge=1)
    amount: Decimal = Field(gt=0, le=Decimal("9999999.99"), max_digits=9, decimal_places=2, allow_inf_nan=False)
    currency: str = "CNY"
    category: str = "其他"
    spent_at: date
    note: str = Field(default="", max_length=500)

    @field_validator("currency")
    @classmethod
    def currency_allowed(cls, value):
        if value not in CURRENCIES:
            raise ValueError("不支持的币种")
        return value

    @field_validator("category")
    @classmethod
    def category_allowed(cls, value):
        if value not in CATEGORIES:
            raise ValueError("不支持的分类")
        return value


class NewEntry(EntryBody):
    id: UUID


def _role(db, book, user):
    if book.user_id == user.id:
        return "owner"
    member = db.get(TravelLedgerMember, (book.id, user.id))
    return member.role if member and member.status == "accepted" else None


def _book(db, book_id, user, permission="read"):
    stmt = select(TravelLedger).where(TravelLedger.id == book_id)
    if permission != "read":
        stmt = stmt.with_for_update()
    book = db.scalar(stmt)
    role = _role(db, book, user) if book else None
    if role is None:
        raise HTTPException(404, "账本不存在或未加入")
    if permission == "owner" and role != "owner":
        raise HTTPException(403, "只有账本创建者能执行此操作")
    if permission == "edit" and role not in ("owner", "editor"):
        raise HTTPException(403, "当前为只读权限，不能修改账单")
    return book


def _accessible_trips(db, user):
    return {trip.id: {"id": trip.id, "title": trip.title} for trip in db.scalars(
        select(TravelTrip).join(TravelTripMember, TravelTripMember.trip_id == TravelTrip.id)
        .where(TravelTripMember.user_id == user.id, TravelTripMember.status == "accepted")
    )}


def _validate_trip(db, trip_id, user):
    if trip_id is None:
        return
    # Lock the parent until commit so deletion cannot race a new association.
    trip = db.scalar(select(TravelTrip).where(TravelTrip.id == trip_id).with_for_update())
    member = db.get(TravelTripMember, (trip_id, user.id))
    if trip is None or member is None or member.status != "accepted":
        raise HTTPException(404, "行程不存在或尚未加入")


def _entry(db, book_id, entry_id):
    entry = db.get(TravelLedgerEntry, entry_id)
    if entry is None or entry.ledger_id != book_id:
        raise HTTPException(404, "账单不存在")
    return entry


def _values(body):
    return dict(title=(body.title or "").strip() or body.category, amount_minor=int(body.amount * 100), currency=body.currency,
                category=body.category, spent_at=body.spent_at.isoformat(), note=body.note.strip())


def _entry_dict(entry):
    return {"id": entry.id, **{key: getattr(entry, key) for key in
            ("title", "amount_minor", "currency", "category", "spent_at", "note", "created_by", "updated_by", "version")}}


def _summary(book, entries, trips=None, role="owner"):
    linked = (trips or {}).get(book.trip_id)
    totals = defaultdict(int)
    categories = defaultdict(int)
    days = defaultdict(int)
    for entry in entries:
        totals[entry.currency] += entry.amount_minor
        categories[(entry.currency, entry.category)] += entry.amount_minor
        days[(entry.currency, entry.spent_at)] += entry.amount_minor
    return {"id": book.id, "title": book.title, "trip": linked, "role": role, "target_currency": book.target_currency, "count": len(entries), "totals": dict(totals),
            "by_category": [{"currency": c, "category": k, "amount_minor": v} for (c, k), v in sorted(categories.items())],
            "by_day": [{"currency": c, "date": k, "amount_minor": v} for (c, k), v in sorted(days.items(), reverse=True)]}


# Membership is independent of trip membership. All mutations serialize on the book.
class RoleBody(BaseModel):
    role: Literal["editor", "viewer"] = "viewer"


class InviteBody(RoleBody):
    username: str = Field(min_length=1, max_length=64)


class RespondBody(BaseModel):
    accept: bool


class TokenBody(BaseModel):
    token: str = Field(min_length=32, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def _capacity(db, book):
    count = len(db.scalars(select(TravelLedgerMember).where(
        TravelLedgerMember.ledger_id == book.id, TravelLedgerMember.status.in_(["accepted", "pending"])
    )).all())
    if count >= 49:
        raise HTTPException(409, "账本成员已满（含待接受邀请最多 50 人）")


def _share_dict(share):
    if not share or not share.token or share.expires_at.replace(tzinfo=timezone.utc) <= _now():
        return None
    return {"token": share.token, "role": share.role, "expires_at": share.expires_at.replace(tzinfo=timezone.utc).isoformat()}


def _shared(db, token, lock=False):
    stmt = select(TravelLedger).join(TravelLedgerShare).where(TravelLedgerShare.token == token)
    if lock:
        stmt = stmt.with_for_update(of=TravelLedger)
    book = db.scalar(stmt)
    # Refresh the token after taking the book lock (revocation may have just committed).
    share = db.get(TravelLedgerShare, book.id, populate_existing=True) if book else None
    if not share or share.token != token or not _share_dict(share):
        raise HTTPException(404, "分享链接无效、已撤销或已过期")
    return book, share


@router.get("/invites/pending")
def pending_invites(db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    rows = db.execute(select(TravelLedger, TravelLedgerMember, TravelUser.username).join(
        TravelLedgerMember, TravelLedgerMember.ledger_id == TravelLedger.id
    ).join(TravelUser, TravelUser.id == TravelLedger.user_id).where(
        TravelLedgerMember.user_id == user.id, TravelLedgerMember.status == "pending"
    )).all()
    return [{"id": b.id, "title": b.title, "role": m.role, "inviter": name} for b, m, name in rows]


@router.get("/shared/{token}")
def preview_share(token: str, db: Session = Depends(get_db)):
    book, share = _shared(db, token)
    owner = db.get(TravelUser, book.user_id)
    return {"title": book.title, "role": share.role, "inviter": owner.username if owner else "创建者",
            "expires_at": _share_dict(share)["expires_at"]}


@router.post("/join")
def join_share(body: TokenBody, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book, share = _shared(db, body.token, lock=True)
    if book.user_id == user.id:
        return {"id": book.id}
    member = db.get(TravelLedgerMember, (book.id, user.id))
    if member and member.status == "removed":
        raise HTTPException(403, "你已被移出此账本，请联系创建者重新邀请")
    if member and member.status == "accepted":
        return {"id": book.id}  # Never escalate an existing member using a link.
    if not member or member.status != "pending":
        _capacity(db, book)
        if not member:
            member = TravelLedgerMember(ledger_id=book.id, user_id=user.id)
            db.add(member)
        member.role = share.role
    member.status = "accepted"
    db.commit()
    return {"id": book.id}


@router.post("/{book_id}/invites/respond")
def respond_invite(book_id: str, body: RespondBody, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = db.scalar(select(TravelLedger).where(TravelLedger.id == book_id).with_for_update())
    member = db.get(TravelLedgerMember, (book_id, user.id))
    if not book or not member or member.status != "pending":
        raise HTTPException(404, "邀请不存在或已处理")
    member.status = "accepted" if body.accept else "declined"
    db.commit()
    return {"id": book_id}


@router.get("/{book_id}/members")
def members(book_id: str, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user)
    owner = db.get(TravelUser, book.user_id)
    result = [{"id": book.user_id, "username": owner.username if owner else "创建者", "role": "owner", "status": "accepted"}]
    stmt = select(TravelLedgerMember, TravelUser.username).join(TravelUser, TravelUser.id == TravelLedgerMember.user_id).where(
        TravelLedgerMember.ledger_id == book_id,
        TravelLedgerMember.status.in_(["accepted", "pending"] if book.user_id == user.id else ["accepted"]),
    ).order_by(TravelLedgerMember.created_at)
    result += [{"id": m.user_id, "username": name, "role": m.role, "status": m.status} for m, name in db.execute(stmt)]
    return result


@router.post("/{book_id}/members")
def invite_member(book_id: str, body: InviteBody, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user, "owner")
    target = db.scalar(select(TravelUser).where(TravelUser.username == body.username.strip()))
    if not target:
        raise HTTPException(404, "未找到此用户名，请核对完整用户名")
    if target.id == book.user_id:
        raise HTTPException(400, "你已经是创建者")
    member = db.get(TravelLedgerMember, (book_id, target.id))
    if member and member.status in ("pending", "accepted"):
        return {"ok": True}  # Retry never silently changes permissions.
    _capacity(db, book)
    if not member:
        member = TravelLedgerMember(ledger_id=book_id, user_id=target.id)
        db.add(member)
    member.role = body.role
    member.status = "pending"
    db.commit()
    return {"ok": True}


@router.patch("/{book_id}/members/{user_id}")
def change_role(book_id: str, user_id: str, body: RoleBody, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    _book(db, book_id, user, "owner")
    member = db.get(TravelLedgerMember, (book_id, user_id))
    if not member or member.status not in ("pending", "accepted"):
        raise HTTPException(404, "成员不存在或不能修改创建者")
    member.role = body.role
    db.commit()
    return {"ok": True}


@router.delete("/{book_id}/members/{user_id}")
def remove_member(book_id: str, user_id: str, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    _book(db, book_id, user, "owner")
    member = db.get(TravelLedgerMember, (book_id, user_id))
    if not member:
        raise HTTPException(404, "成员不存在或不能移除创建者")
    member.status = "removed"  # Keep a tombstone so a leaked link cannot undo removal.
    db.commit()
    return {"ok": True}


@router.post("/{book_id}/leave")
def leave_book(book_id: str, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user, "member")
    if book.user_id == user.id:
        raise HTTPException(403, "创建者不能退出，可删除账本")
    db.get(TravelLedgerMember, (book_id, user.id)).status = "left"
    db.commit()
    return {"ok": True}


@router.get("/{book_id}/share")
def get_share(book_id: str, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    _book(db, book_id, user, "owner")
    return _share_dict(db.get(TravelLedgerShare, book_id))


@router.post("/{book_id}/share")
def create_share(book_id: str, body: RoleBody, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    _book(db, book_id, user, "owner")
    share = db.get(TravelLedgerShare, book_id)
    if not share:
        share = TravelLedgerShare(ledger_id=book_id)
        db.add(share)
    share.token = secrets.token_urlsafe(32)
    share.role = body.role
    share.expires_at = _now() + timedelta(days=7)
    db.commit()
    return _share_dict(share)


@router.delete("/{book_id}/share")
def revoke_share(book_id: str, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    _book(db, book_id, user, "owner")
    share = db.get(TravelLedgerShare, book_id)
    if share:
        share.token = None
        db.commit()
    return {"ok": True}


@router.get("")
def list_books(trip_id: str | None = None, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    member_ids = select(TravelLedgerMember.ledger_id).where(TravelLedgerMember.user_id == user.id, TravelLedgerMember.status == "accepted")
    books = db.scalars(select(TravelLedger).where(or_(TravelLedger.user_id == user.id, TravelLedger.id.in_(member_ids))).order_by(TravelLedger.updated_at.desc())).all()
    entries = db.scalars(select(TravelLedgerEntry).where(TravelLedgerEntry.ledger_id.in_([b.id for b in books]))).all()
    grouped = defaultdict(list)
    for entry in entries:
        grouped[entry.ledger_id].append(entry)
    trips = _accessible_trips(db, user)
    if trip_id is not None and trip_id not in trips:
        raise HTTPException(404, "行程不存在或尚未加入")
    return [_summary(book, grouped[book.id], trips, _role(db, book, user)) for book in books if trip_id is None or book.trip_id == trip_id]


@router.post("")
def create_book(body: LinkedBookBody, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    _validate_trip(db, body.trip_id, user)
    book = TravelLedger(user_id=user.id, title=body.title, trip_id=body.trip_id)
    db.add(book)
    db.commit()
    return _summary(book, [], _accessible_trips(db, user))


@router.get("/{book_id}")
def get_book(book_id: str, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user)
    entries = db.scalars(select(TravelLedgerEntry).where(TravelLedgerEntry.ledger_id == book_id)
                         .order_by(TravelLedgerEntry.spent_at.desc(), TravelLedgerEntry.created_at.desc())).all()
    return {**_summary(book, entries, _accessible_trips(db, user), _role(db, book, user)), "entries": [_entry_dict(e) for e in entries]}


@router.patch("/{book_id}")
def rename_book(book_id: str, body: LinkedBookBody, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user, "owner")
    if "trip_id" in body.model_fields_set:
        _validate_trip(db, body.trip_id, user)
        book.trip_id = body.trip_id
    book.title = body.title
    book.updated_at = _now()
    db.commit()
    return {"ok": True}


@router.delete("/{book_id}")
def delete_book(book_id: str, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user, "owner")
    db.execute(delete(TravelLedgerEntry).where(TravelLedgerEntry.ledger_id == book_id))
    db.execute(delete(TravelLedgerMember).where(TravelLedgerMember.ledger_id == book_id))
    db.execute(delete(TravelLedgerShare).where(TravelLedgerShare.ledger_id == book_id))
    db.delete(book)
    db.commit()
    return {"ok": True}


def _replay(entry, book_id, values):
    if entry.ledger_id != book_id or any(getattr(entry, k) != v for k, v in values.items()):
        raise HTTPException(409, "此账单已保存，请刷新后编辑")
    return _entry_dict(entry)


@router.post("/{book_id}/entries")
def create_entry(book_id: str, body: NewEntry, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user, "edit")
    values = _values(body)
    existing = db.get(TravelLedgerEntry, body.id.hex)
    if existing:
        return _replay(existing, book_id, values)
    entry = TravelLedgerEntry(id=body.id.hex, ledger_id=book_id, created_by=user.id, updated_by=user.id, **values)
    db.add(entry)
    book.updated_at = _now()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(TravelLedgerEntry, body.id.hex)
        if existing:
            return _replay(existing, book_id, values)
        raise HTTPException(409, "账本已变化，请刷新后重试")
    return _entry_dict(entry)


class DraftBody(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    today: date | None = None


@router.post("/{book_id}/ai-draft")
def ai_draft(book_id: str, body: DraftBody, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """一句话 → 账单草稿，不写库；用户在预览里确认后走 entries/batch。"""
    from app.agent.ledger_draft import draft_entries
    from app.llm.client import get_llm
    book = _book(db, book_id, user)
    if _role(db, book, user) not in ("owner", "editor"):
        raise HTTPException(403, "当前为只读权限，不能修改账单")
    trip = db.get(TravelTrip, book.trip_id) if book.trip_id else None
    recent = list(db.scalars(select(TravelLedgerEntry.currency).where(TravelLedgerEntry.ledger_id == book_id)
                             .order_by(TravelLedgerEntry.created_at.desc()).limit(20)))
    db.rollback()  # 别在等模型的几秒里攥着连接上的事务
    # 客户端给的「今天」是用户本地日期；偏离服务器日期一天以上就不信（时区最多差一天）。
    server_today = date.today()
    today = body.today if body.today and abs((body.today - server_today).days) <= 1 else server_today
    try:
        drafts = draft_entries(get_llm(), body.text.strip(), today=today,
                               destination=(trip.destination if trip else None) or (trip.title if trip else None), recent=recent)
    except Exception:  # noqa: BLE001
        logger.warning("一句话记账抽取失败 book=%s", book_id, exc_info=True)
        raise HTTPException(502, "暂时没能识别，稍后再试，或手动记一笔")
    if not drafts.items:
        raise HTTPException(422, "没认出金额，换个说法试试，比如「午饭 拉面 1200 日元」")
    return {"drafts": drafts.items, "default_currency": drafts.default_currency,
            "currency_source": drafts.currency_source, "dropped": drafts.dropped}


class BatchBody(BaseModel):
    entries: list[NewEntry] = Field(min_length=1, max_length=30)


@router.post("/{book_id}/entries/batch")
def create_entries(book_id: str, body: BatchBody, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """确认后一次入账：同一事务，要么全记上要么都不记；按客户端 id 幂等，重复提交返回已有账单。"""
    book = _book(db, book_id, user, "edit")
    saved = []
    for item in body.entries:
        values = _values(item)
        existing = db.get(TravelLedgerEntry, item.id.hex)
        if existing:
            saved.append(_replay(existing, book_id, values))
            continue
        entry = TravelLedgerEntry(id=item.id.hex, ledger_id=book_id, created_by=user.id, updated_by=user.id, **values)
        db.add(entry)
        saved.append(entry)
    book.updated_at = _now()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "账本已变化，请刷新后重试")
    return {"entries": [item if isinstance(item, dict) else _entry_dict(item) for item in saved]}


@router.patch("/{book_id}/entries/{entry_id}")
def edit_entry(book_id: str, entry_id: str, body: EntryBody, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user, "edit")
    entry = _entry(db, book_id, entry_id)
    if body.version is not None and entry.version != body.version:
        raise HTTPException(409, "这笔账单已被其他人修改，请关闭表单、刷新后重新编辑")
    entry.version += 1
    entry.updated_by = user.id
    for key, value in _values(body).items():
        setattr(entry, key, value)
    book.updated_at = _now()
    db.commit()
    return _entry_dict(entry)


@router.delete("/{book_id}/entries/{entry_id}")
def delete_entry(book_id: str, entry_id: str, version: int | None = None, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user, "edit")
    entry = _entry(db, book_id, entry_id)
    if version is not None and entry.version != version:
        raise HTTPException(409, "这笔账单已被修改，请刷新后重新确认删除")
    db.delete(entry)
    book.updated_at = _now()
    db.commit()
    return {"ok": True}


class CurrencyBody(BaseModel):
    target_currency: str

    @field_validator("target_currency")
    @classmethod
    def supported(cls, value):
        if value not in CURRENCIES:
            raise ValueError("不支持的汇总币种")
        return value


@router.patch("/{book_id}/currency")
def set_currency(book_id: str, body: CurrencyBody, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user, "owner")
    book.target_currency = body.target_currency
    book.updated_at = _now()
    db.commit()
    return {"ok": True}


@router.get("/{book_id}/conversion")
async def conversion(book_id: str, refresh: bool = False, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    from app.tools.ledger_fx import convert_totals
    book = _book(db, book_id, user)
    entries = db.scalars(select(TravelLedgerEntry).where(TravelLedgerEntry.ledger_id == book_id)).all()
    totals = _summary(book, entries)['totals']
    return await convert_totals(totals, book.target_currency, refresh)
