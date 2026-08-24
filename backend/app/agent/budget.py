"""预算明细面板（Phase 67）

从已生成的攻略正文抽结构化开销 + 需预约项（LLM）→ 分类归一 → **服务端重算汇总**
→ 写一条 meta.budget 的 assistant 消息供前端渲染成面板。

为什么汇总要服务端算：让模型自己算总额会输出 `"total": 30+54+120=324` 这类非法 JSON
（TripStar 就因此被迫写正则 eval 修复）。这里模型只给单项金额，加法我们自己做。
"""

import asyncio
import json
import logging

from app.agent.context_security import EXTERNAL_POLICY, wrap_external
from app.llm.client import EXTRACT_THINKING_DISCIPLINE
from app.agent.trip_planner import normalize_budget_category
from app.config import settings
from app.db.models import TravelMessage
from app.db.session import get_session
from app.llm.client import get_llm
from app.schemas.budget_schema import BudgetData

logger = logging.getLogger(__name__)

# 分类展示顺序（面板里按这个排，不按金额，保证多次生成视觉稳定）
CATEGORY_ORDER = ["大交通", "住宿", "餐饮", "门票", "交通", "其他"]

EXTRACT_SYSTEM = (
    "你是旅行预算整理助手，把攻略正文里的花费和需预约信息整理成结构化数据。\n"
    "铁律：只用正文里**真实出现**的金额和信息，绝对不要估算、不要编造、不要脑补市场价。"
    "正文没写预算就给空的 items 数组。\n"
    "- items：逐项开销。金额按**一个人**算；写「200-300元」这类区间取中间值 250；"
    "写「¥400/晚」且住 2 晚就拆成 2 项或写 1 项 800 并在 name 里注明。\n"
    "- **覆盖要完整**：正文预算表里的汇总类条目（如「餐饮：正餐7次×140 + 小吃6次×50」）"
    "也要按其中的乘式拆成对应明细计入，不要因为它不是单笔花费就漏掉——"
    "漏项会让面板总额远低于正文，用户会认为数据不可信。\n"
    "- guide_stated_total：正文若自己写了合计金额（团组口径）就照抄，没写填 0。\n"
    "- category 只能填：住宿/交通/餐饮/门票/大交通/其他。"
    "往返目的地的机票高铁算「大交通」，当地地铁打车算「交通」。\n"
    "- 不要输出总计项（如「合计」「总预算」），总额由系统自己算，你输出总计会导致重复计算。\n"
    "- reservations：需要提前预约或抢票的景点，依据正文里「需要预约」「提前预约」「抢票」"
    "「约满」「官方预约」等表述判断，正文没提就给空数组。\n"
    "- notes：预算口径说明 0-3 条，如「不含往返大交通」。"
) + EXTRACT_THINKING_DISCIPLINE

# 明显是「合计」行的项目名——模型偶尔无视上面的约束，兜底剔除避免总额翻倍
_TOTAL_WORDS = ("合计", "总计", "总预算", "小计", "共计", "总花费", "总费用", "人均合计")


def _is_total_line(name: str) -> bool:
    return any(w in (name or "") for w in _TOTAL_WORDS)


def build_budget_payload(data: BudgetData) -> dict:
    """把抽取结果整理成前端直接消费的 payload；汇总全部在这里重算。"""
    items: list[dict] = []
    for it in data.items:
        amount = round(float(it.amount or 0), 2)
        # 负数/零/合计行都不进明细：金额无意义或会导致重复计算
        if amount <= 0 or _is_total_line(it.name):
            continue
        items.append(
            {
                "category": normalize_budget_category(it.category),
                "name": (it.name or "").strip() or "未命名开销",
                "day": max(0, int(it.day or 0)),
                "amount": amount,
                "note": (it.note or "").strip(),
            }
        )

    total = round(sum(i["amount"] for i in items), 2)

    # 分类汇总：按 CATEGORY_ORDER 固定顺序，只保留有金额的类
    by_category = []
    for cat in CATEGORY_ORDER:
        amt = round(sum(i["amount"] for i in items if i["category"] == cat), 2)
        if amt <= 0:
            continue
        by_category.append(
            {
                "category": cat,
                "amount": amt,
                "pct": round(amt / total * 100, 1) if total > 0 else 0.0,
            }
        )

    # 逐天汇总：day=0（整趟通用）不进逐天，单独作为 shared 展示
    day_nums = sorted({i["day"] for i in items if i["day"] > 0})
    by_day = [
        {
            "day": d,
            "amount": round(sum(i["amount"] for i in items if i["day"] == d), 2),
        }
        for d in day_nums
    ]
    shared = round(sum(i["amount"] for i in items if i["day"] == 0), 2)

    reservations = [
        {
            "name": (r.name or "").strip(),
            "channel": (r.channel or "").strip(),
            "advance": (r.advance or "").strip(),
            "note": (r.note or "").strip(),
        }
        for r in data.reservations
        if (r.name or "").strip()
    ]

    headcount = max(1, int(data.headcount or 1))
    notes = [n.strip() for n in data.notes if (n or "").strip()][:3]
    # 口径对账（走查 P2-b）：正文自带合计与逐项重算差 >20% 时，主动说明差异来源——
    # 两个数并排且相差上千，不解释会让整个面板显得不可信。逐项累加仍是唯一采信口径。
    stated = round(float(data.guide_stated_total or 0), 2)
    group_total = round(total * headcount, 2)
    if stated > 0 and group_total > 0 and abs(group_total - stated) / stated > 0.2:
        notes = notes[:2] + [
            f"与正文合计（¥{stated:g}）有差异：面板只累计正文明确列出的单笔花费，"
            "正文合计含估算类打包项；以逐项累加为准"
        ]
    return {
        "currency": (data.currency or "CNY").strip() or "CNY",
        "headcount": headcount,
        "total": total,
        "group_total": group_total,
        "by_category": by_category,
        "by_day": by_day,
        "shared": shared,
        "items": items,
        "reservations": reservations,
        "notes": notes,
    }


def generate_budget(cid: str, message_id: str) -> None:
    """后台入口：占位 → 抽取 → 终稿。任何异常都必须把占位消息终稿掉。

    停止（2026-07-31）：此前完全没接协作式取消——用户点「停止」标记没人读、任务照跑，
    且残留的取消标记会把**下一轮**正常消息在首个检查点误杀（线上真实反馈「不能中途停止」）。
    现在：检查点响应停止 + finally 清标记。
    """
    from app.agent.cancel import TurnCancelled, clear_cancel

    msg_id = _add_streaming(cid)
    try:
        asyncio.run(_run(cid, message_id, msg_id))
    except TurnCancelled:
        _finalize(msg_id, "已停止本次预算统计。", None)
    except Exception:
        logger.warning("预算面板生成失败 cid=%s", cid, exc_info=True)
        _finalize(msg_id, "抱歉，预算明细生成失败了，请重试。", None)
    finally:
        clear_cancel(cid)


async def _budget_data(cid: str, message_id: str, guide: str, llm) -> BudgetData | None:
    """拿预算视图数据：优先从本体对象图投影（零 LLM 调用），失败回退旧的直接抽取。

    Phase 86：与手账海报共用同一份 `TripObject`——先点海报再点预算时这里不再调 LLM，
    两个面板的地点/金额也不会再出现「同一份攻略解析出两套结果」。
    汇总口径不变：仍由下面的 `build_budget_payload` 服务端逐项累加。
    """
    from app.agent import cancel

    if settings.ontology_enabled:
        try:
            from app.ontology.extract import BUDGET_LANES
            from app.ontology.projections import to_budget_data
            from app.ontology.store import ensure_trip_object

            # 只抽预算要的两路；先点过海报的话 profile 已在缓存里，这里只补 cost 一路
            trip = await ensure_trip_object(cid, message_id, llm=llm, need=BUDGET_LANES)
            if trip is not None and (trip.expenses or trip.reservations):
                return to_budget_data(trip)
        except cancel.TurnCancelled:
            raise
        except Exception:  # noqa: BLE001 — 本体层出问题不能让预算面板整个不可用
            logger.warning("ontology budget projection failed, falling back", exc_info=True)

    # 回退：直接从正文抽（Phase 67 旧路径）
    try:
        # wait_cancellable：抽取调用可能因结构化重试拖到分钟级，等待期间每秒响应停止
        return await cancel.wait_cancellable(cid, asyncio.to_thread(
            llm.parse,
            wrap_external(guide[:6000], source="guide"),
            BudgetData,
            model=settings.model_classifier,
            system=EXTRACT_SYSTEM + EXTERNAL_POLICY,
            # 判断档：金额一律人均口径，「区间价取中间值」「两人合计→人均」都是推导不是照抄
            effort=settings.extract_judgment_reasoning_effort,
        ))
    except cancel.TurnCancelled:
        raise
    except Exception:  # noqa: BLE001
        logger.warning("预算抽取失败 cid=%s", cid, exc_info=True)
        return None


async def _run(cid: str, message_id: str, msg_id: str) -> None:
    with get_session() as db:
        src = db.get(TravelMessage, message_id)
        guide = (src.content or "") if src else ""

    if not guide.strip():
        _finalize(msg_id, "找不到要统计预算的攻略内容。", None)
        return

    from app.agent import cancel

    llm = get_llm()
    try:
        cancel.check(cid)  # 抽取前：停止请求在这里立即生效
        data = await _budget_data(cid, message_id, guide, llm)
    except cancel.TurnCancelled:
        # 必须在 _run 内部终稿，不能靠外层 generate_budget 接：asyncio.run 退出时会
        # join 默认线程池（等孤儿 LLM 线程跑完，可达分钟级），外层的 finalize 会被拖到
        # 那之后——用户点了停止却要等 LLM 自然结束才看到（2026-07-31 线上实测排障）。
        _finalize(msg_id, "已停止本次预算统计。", None)
        cancel.clear_cancel(cid)  # 立即清，残留标记会误杀下一轮
        return
    if data is None:
        _finalize(msg_id, "预算信息提取失败了，请重试。", None)
        return

    payload = build_budget_payload(data)
    if not payload["items"] and not payload["reservations"]:
        _finalize(
            msg_id,
            "这份攻略里没有写明具体花费，没法统计预算。可以让我在攻略里补上预算再试。",
            None,
        )
        return

    _finalize(msg_id, "预算明细", {"budget": payload})


def _add_streaming(cid: str) -> str:
    """占一条流式 assistant 消息（生成期间 running=true，前端持续轮询）。"""
    with get_session() as db:
        m = TravelMessage(
            conversation_id=cid,
            role="assistant",
            content="",
            meta_json=json.dumps({"streaming": True}),
        )
        db.add(m)
        db.commit()
        return m.id


def _finalize(msg_id: str, content: str, meta: dict | None) -> None:
    """把占位消息终稿（去掉 streaming 标记），并清掉生成期间的临时进度。"""
    cid = None
    with get_session() as db:
        m = db.get(TravelMessage, msg_id)
        if m is None:
            return
        cid = m.conversation_id
        m.content = content
        m.meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
        db.commit()
    if cid:
        from app.agent.orchestrator import clear_plain_progress

        clear_plain_progress(cid)
