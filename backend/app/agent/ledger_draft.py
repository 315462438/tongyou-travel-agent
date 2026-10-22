"""记账页「一句话记账」：把用户的一句话拆成账单草稿（不写库），确认后由 ledger_api 批量入账。

分工：模型只做「照抄 + 归类」——拆条目、照抄金额（唯一允许的转换是中文数字→阿拉伯数字）、
标出用户是否明说了币种、给出相对日期标记；**币种默认值、具体日期、分类兜底、金额校验全在服务端**，
同 Phase 67/113「不让模型算数」。草稿与 ledger_api.EntryBody 用同一套币种/分类集合。
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from pydantic import BaseModel, Field

from app.config import settings
from app.llm.client import EXTRACT_THINKING_DISCIPLINE

logger = logging.getLogger(__name__)

CURRENCIES = ("CNY", "MYR", "SGD", "USD", "EUR", "JPY", "HKD", "THB", "KRW", "GBP", "AUD", "TWD", "VND", "IDR")
CATEGORIES = ("餐饮", "交通", "住宿", "门票", "购物", "其他")
MAX_ITEMS = 30
MAX_AMOUNT = Decimal("9999999.99")

# 行程目的地 → 当地货币。只收账本支持的币种；匹配不到就不猜，交给下一级默认。
_DESTINATION_CURRENCY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("JPY", ("日本", "东京", "大阪", "京都", "奈良", "北海道", "札幌", "冲绳", "福冈", "名古屋", "神户", "横滨", "箱根", "富士")),
    ("KRW", ("韩国", "首尔", "釜山", "济州")),
    ("THB", ("泰国", "曼谷", "清迈", "普吉", "芭提雅", "苏梅")),
    ("MYR", ("马来西亚", "吉隆坡", "槟城", "仙本那", "亚庇", "沙巴", "兰卡威", "马六甲")),
    ("SGD", ("新加坡",)),
    ("HKD", ("香港",)),
    ("TWD", ("台湾", "台北", "高雄", "台中", "台南", "花莲", "垦丁")),
    ("VND", ("越南", "河内", "胡志明", "岘港", "芽庄")),
    ("IDR", ("印尼", "印度尼西亚", "巴厘岛", "雅加达")),
    ("USD", ("美国", "纽约", "洛杉矶", "旧金山", "夏威夷", "拉斯维加斯")),
    ("GBP", ("英国", "伦敦", "爱丁堡")),
    ("AUD", ("澳大利亚", "澳洲", "悉尼", "墨尔本")),
    ("EUR", ("法国", "巴黎", "德国", "意大利", "罗马", "米兰", "西班牙", "巴塞罗那", "荷兰", "阿姆斯特丹", "希腊", "欧洲", "奥地利", "葡萄牙")),
)
# 「¥」「元」在日本/台湾/香港行程里都可能指当地货币：用户写了它但没说清，就提醒看一眼。
_AMBIGUOUS_SYMBOL = re.compile(r"[¥￥]|(?<![日韩港美欧澳新马台越])元|块")


class DraftItem(BaseModel):
    title: str = Field(description="简短名称，如「拉面」「打车」「药妆」，不超过 20 字")
    amount: str = Field(description="金额数字，照抄用户说的数；中文数字写成阿拉伯数字（一万二→12000，三千五→3500），不要做任何加减乘除")
    currency: str = Field(default="", description="三位币种代码；只有用户明确说出币种（日元/円/韩元/泰铢/RM/美元/$/€/英镑/港币/台币等）时才填，否则留空")
    category: str = Field(description="餐饮/交通/住宿/门票/购物/其他 之一")
    day: str = Field(default="today", description="today / yesterday / day_before，或 YYYY-MM-DD；没说就是 today")
    note: str = Field(default="", description="用户补充的备注，没有就留空")


class DraftExtraction(BaseModel):
    items: list[DraftItem] = Field(default_factory=list)


SYSTEM = f"""你在旅行记账页帮用户把一句话拆成账单。规则：
1. 每一笔独立的花费是一条；「午饭拉面和打车」是两条。用户把几样东西合在一起说了一个总价，就合成一条，不要自己拆价格。
2. 金额照抄用户说的数，不做任何计算：「两个人一共 200」就是 200，不要算人均；中文数字只改写成阿拉伯数字。
3. 币种只在用户明确说出时填三位代码（日元 JPY、韩元 KRW、泰铢 THB、马币/RM MYR、新币 SGD、美元/$ USD、欧元/€ EUR、
   英镑 GBP、港币 HKD、台币 TWD、越南盾 VND、印尼盾 IDR、人民币 CNY）。只写了「¥」「元」「块」没说是哪国的，留空。
4. 分类只能是：{"、".join(CATEGORIES)}。吃喝→餐饮，打车/地铁/机票/火车/租车/加油→交通，酒店/民宿→住宿，景点/门票/演出→门票，买东西/特产/药妆→购物。
5. 日期：没说就是 today；「昨天」yesterday；「前天」day_before；说了具体日期或星期几就换算成 YYYY-MM-DD（今天的日期会在下面给出）。
6. 没有金额的内容不要输出。
""" + EXTRACT_THINKING_DISCIPLINE


@dataclass
class Drafts:
    items: list[dict] = field(default_factory=list)
    default_currency: str = "CNY"
    currency_source: str = "fallback"  # trip / history / fallback
    dropped: int = 0


def destination_currency(destination: str | None) -> str | None:
    text = destination or ""
    for code, words in _DESTINATION_CURRENCY:
        if any(word in text for word in words):
            return code
    return None


def default_currency(destination: str | None, recent: list[str]) -> tuple[str, str]:
    """用户没说币种时用哪个：行程目的地 > 本账本最近最常用 > 人民币。"""
    by_trip = destination_currency(destination)
    if by_trip:
        return by_trip, "trip"
    usable = [c for c in recent if c in CURRENCIES]
    if usable:
        return Counter(usable).most_common(1)[0][0], "history"
    return "CNY", "fallback"


def parse_amount(raw: str) -> Decimal | None:
    text = re.sub(r"[,，\s]", "", str(raw or ""))
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        value = Decimal(match.group(0)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return value if Decimal("0") < value <= MAX_AMOUNT else None


def resolve_day(raw: str, today: date) -> date:
    token = (raw or "").strip().lower()
    if token in ("", "today", "今天"):
        return today
    if token in ("yesterday", "昨天"):
        return today - timedelta(days=1)
    if token in ("day_before", "前天"):
        return today - timedelta(days=2)
    try:
        day = date.fromisoformat(token[:10])
    except ValueError:
        return today
    # 记账只记已经花掉的钱；模型把「周一」算到下周去时退回今天。
    return day if today - timedelta(days=366) <= day <= today else today


def normalize(extraction: DraftExtraction, *, text: str, today: date, destination: str | None, recent: list[str]) -> Drafts:
    fallback, source = default_currency(destination, recent)
    ambiguous = bool(_AMBIGUOUS_SYMBOL.search(text))
    out = Drafts(default_currency=fallback, currency_source=source)
    for item in extraction.items[:MAX_ITEMS]:
        amount = parse_amount(item.amount)
        if amount is None:
            out.dropped += 1
            continue
        stated = (item.currency or "").strip().upper()
        currency = stated if stated in CURRENCIES else fallback
        # 需要用户看一眼的：完全没线索（新账本、没写币种也没写「元」），或写了「¥/元」却落在外币上。
        guessed = stated not in CURRENCIES and ((source == "fallback" and not ambiguous) or (ambiguous and currency != "CNY"))
        category = item.category.strip() if item.category.strip() in CATEGORIES else "其他"
        title = re.sub(r"\s+", " ", item.title).strip()[:40] or category
        out.items.append({
            "id": uuid4().hex,
            "title": title,
            "amount": f"{amount:.2f}",
            "currency": currency,
            "currency_guessed": guessed,
            "category": category,
            "spent_at": resolve_day(item.day, today).isoformat(),
            "note": item.note.strip()[:200],
        })
    out.dropped += max(0, len(extraction.items) - MAX_ITEMS)
    return out


def draft_entries(llm, text: str, *, today: date, destination: str | None, recent: list[str]) -> Drafts:
    """一句话 → 账单草稿。只抽取不写库；入账走 ledger_api 的批量接口（确认后）。"""
    weekday = "一二三四五六日"[today.weekday()]
    prompt = f"今天是 {today.isoformat()}（星期{weekday}）。\n用户说：{text}"
    extraction = llm.parse(
        prompt, DraftExtraction, model=settings.model_classifier, system=SYSTEM,
        # 判断档但要快：要认中文数字、判币种是否明说，又是用户在等的交互，用 low 而非默认的长思考。
        effort="low", max_tokens=2000, timeout=45,
    )
    return normalize(extraction, text=text, today=today, destination=destination, recent=recent)
