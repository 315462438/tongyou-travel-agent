"""独立个人旅行记账：整数分、逐币种汇总、UUID 幂等新增。"""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import TravelLedger, TravelLedgerEntry, TravelUser, _now
from app.db.session import get_db

router = APIRouter(prefix="/api/ledger", tags=["ledger"])
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


class EntryBody(BookBody):
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


def _book(db, book_id, user):
    book = db.get(TravelLedger, book_id)
    if book is None or book.user_id != user.id:
        raise HTTPException(404, "账本不存在")
    return book


def _entry(db, book_id, entry_id):
    entry = db.get(TravelLedgerEntry, entry_id)
    if entry is None or entry.ledger_id != book_id:
        raise HTTPException(404, "账单不存在")
    return entry


def _values(body):
    return dict(title=body.title, amount_minor=int(body.amount * 100), currency=body.currency,
                category=body.category, spent_at=body.spent_at.isoformat(), note=body.note.strip())


def _entry_dict(entry):
    return {"id": entry.id, **{key: getattr(entry, key) for key in
            ("title", "amount_minor", "currency", "category", "spent_at", "note")}}


def _summary(book, entries):
    totals = defaultdict(int)
    categories = defaultdict(int)
    days = defaultdict(int)
    for entry in entries:
        totals[entry.currency] += entry.amount_minor
        categories[(entry.currency, entry.category)] += entry.amount_minor
        days[(entry.currency, entry.spent_at)] += entry.amount_minor
    return {"id": book.id, "title": book.title, "target_currency": book.target_currency, "count": len(entries), "totals": dict(totals),
            "by_category": [{"currency": c, "category": k, "amount_minor": v} for (c, k), v in sorted(categories.items())],
            "by_day": [{"currency": c, "date": k, "amount_minor": v} for (c, k), v in sorted(days.items(), reverse=True)]}


@router.get("")
def list_books(db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    books = db.scalars(select(TravelLedger).where(TravelLedger.user_id == user.id).order_by(TravelLedger.updated_at.desc())).all()
    entries = db.scalars(select(TravelLedgerEntry).join(TravelLedger).where(TravelLedger.user_id == user.id)).all()
    grouped = defaultdict(list)
    for entry in entries:
        grouped[entry.ledger_id].append(entry)
    return [_summary(book, grouped[book.id]) for book in books]


@router.post("")
def create_book(body: BookBody, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = TravelLedger(user_id=user.id, title=body.title)
    db.add(book)
    db.commit()
    return _summary(book, [])


@router.get("/{book_id}")
def get_book(book_id: str, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user)
    entries = db.scalars(select(TravelLedgerEntry).where(TravelLedgerEntry.ledger_id == book_id)
                         .order_by(TravelLedgerEntry.spent_at.desc(), TravelLedgerEntry.created_at.desc())).all()
    return {**_summary(book, entries), "entries": [_entry_dict(e) for e in entries]}


@router.patch("/{book_id}")
def rename_book(book_id: str, body: BookBody, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user)
    book.title = body.title
    book.updated_at = _now()
    db.commit()
    return {"ok": True}


@router.delete("/{book_id}")
def delete_book(book_id: str, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user)
    db.execute(delete(TravelLedgerEntry).where(TravelLedgerEntry.ledger_id == book_id))
    db.delete(book)
    db.commit()
    return {"ok": True}


def _replay(entry, book_id, values):
    if entry.ledger_id != book_id or any(getattr(entry, k) != v for k, v in values.items()):
        raise HTTPException(409, "此账单已保存，请刷新后编辑")
    return _entry_dict(entry)


@router.post("/{book_id}/entries")
def create_entry(book_id: str, body: NewEntry, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user)
    values = _values(body)
    existing = db.get(TravelLedgerEntry, body.id.hex)
    if existing:
        return _replay(existing, book_id, values)
    entry = TravelLedgerEntry(id=body.id.hex, ledger_id=book_id, **values)
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


@router.patch("/{book_id}/entries/{entry_id}")
def edit_entry(book_id: str, entry_id: str, body: EntryBody, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user)
    entry = _entry(db, book_id, entry_id)
    for key, value in _values(body).items():
        setattr(entry, key, value)
    book.updated_at = _now()
    db.commit()
    return _entry_dict(entry)


@router.delete("/{book_id}/entries/{entry_id}")
def delete_entry(book_id: str, entry_id: str, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    book = _book(db, book_id, user)
    db.delete(_entry(db, book_id, entry_id))
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
    book = _book(db, book_id, user)
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
