"""记忆系统（Phase 4）

两类记忆：
  A. 历史会话引用（past_chat）：检索旧会话的标题 + 助手首段摘要，注入上下文。
  B. 提炼型长期记忆（travel_memory 表）：每轮回复后旁路提炼，模型输出
     add/update/delete 操作（带已有记忆清单，能去重、修正、失效），而非只会新增。

检索策略（个人工具，记忆量级几十~几百条）：全量注入 + 排序截断，不用向量库；
量大后升级 pgvector（见 docs/task_plans/task_plan-phase4-记忆系统提案.md）。

所有 DB 函数接受 Session 参数，便于用 sqlite 内存库离线测试；
编排层通过 get_session() 包装调用。
"""

import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.context_security import EXTERNAL_POLICY, wrap_external
from app.config import settings
from app.db.models import TravelConversation, TravelMemory, TravelMessage
from app.schemas.memory_schema import MemoryConsolidation, MemoryUpdatePlan

logger = logging.getLogger(__name__)

MEMORY_TYPES = ("preference", "fact", "procedural")  # trip_state 已于 2026-07-31 退役

# Phase 17：规范 key 集合（三元组谓词）。LLM 优先复用，保证记忆按槽合并、行数有界。
CANONICAL_KEYS: dict[str, str] = {
    "口味偏好": "preference",
    "兴趣偏好": "preference",
    "节奏偏好": "preference",
    "预算偏好": "preference",
    "住宿偏好": "preference",
    "出行方式": "preference",
    "常驻城市": "fact",
    "忌口过敏": "fact",
    "同行情况": "fact",
    "旅行足迹": "fact",       # Phase 45 情景→语义：累积去过/规划过的城市
    "规划习惯": "procedural",  # Phase 45 程序记忆：规划/预订流程偏好
    # 2026-07-31 退役「当前行程」(trip_state)：它是时点事实伪装成长期偏好，
    # 日期/预算/人数会被生成端当成本次约束（线上真实泄漏）；而它唯一的用途
    # ——跨会话指代消解——已由确定性的 recent_plan_hint 接管（永远新鲜、不进记忆表）。
}
_KEY_LIST = "、".join(CANONICAL_KEYS)

EXTRACT_SYSTEM = (
    "你是记忆管理助手，用「三元组归槽」方式维护用户长期记忆：每条记忆挂在一个 key 上，"
    "同一 key 只保留一条。\n"
    "只记「跨对话仍然有用」的信息；不要记一次性查询、攻略正文、本轮才有意义的细节。\n"
    f"key 优先从规范集合里选：{_KEY_LIST}。同类信息务必复用同一个 key，让它们合并成一条，"
    "不要为近义内容新造 key。\n"
    "输出操作：\n"
    "- 该 key 尚无记忆、且有新信息 → add（给出 key 和 content）。\n"
    "- 该 key 已有记忆、需补充或修正 → update（给出同一个 key；content 写合并后的完整表述，"
    "把旧信息和新信息并进去，而不是只写新增部分）。\n"
    "- 用户明确否认/该事实失效 → delete（给出该记忆 id）。\n"
    "**不要记具体某一次行程**（哪天去哪、几天几晚、这次多少预算、这次住哪）——"
    "那是一次性的时点信息，过后就是噪声，系统另有机制处理；只记「下次出行仍然成立」的部分。\n"
    "content 用一句话第三人称陈述，如「用户爱吃海鲜和辣」。explicit：用户亲口说=true，"
    "从上下文推断=false。没有值得记的就输出空列表。\n"
    "三条提炼纪律（Phase 30）：\n"
    "- 相对日期一律换算成**绝对日期**再存（「下周五出发」→「2026-07-24 出发」），"
    "否则时间一过记忆就失真；\n"
    "- **正面确认也值得记**：用户对方案表示满意/采纳（「就按这个来」「上次那家酒店不错」）"
    "时，把被认可的特征提炼成偏好——只记纠正会让画像越来越保守；\n"
    "- 偏好尽量附简短原因（「爱吃辣——川渝人」），便于以后判断边界情况。\n"
    "两条新纪律（Phase 45）：\n"
    "- **规划习惯（程序记忆）**：用户流露的规划/预订流程偏好（先定酒店再排景点、"
    "偏好自由行不跟团、习惯提前很久订票、喜欢自己 DIY），归到 key=规划习惯；\n"
    "- **旅行足迹**：用户去过或规划过某个目的地时，把城市名并入 key=旅行足迹"
    "（累积列出，如「去过厦门、成都、哈尔滨」）——只留城市，不要带这次的日期、"
    "天数和预算。这是行程信息里唯一值得长期保留的部分。"
)


# ---------- 读取 / 注入 ----------

def load_memories(db: Session, user_id: str, limit: int | None = None) -> list[TravelMemory]:
    """按 重要性 取某用户的记忆（Phase 15 按用户隔离）。

    排序 = explicit(weight)↓ → 访问频率(hit_count)↓ → 更新时间↓（Phase 45 补访问频率）：
    explicit（用户亲口说的）仍最高优先；同档内高频命中的核心偏好靠前，也因此在
    `_prune` 剪枝时被优先保留，不会因久未更新被误删。
    """
    stmt = (
        select(TravelMemory)
        .where(TravelMemory.user_id == user_id)
        .order_by(TravelMemory.weight.desc(), TravelMemory.hit_count.desc(), TravelMemory.updated_at.desc())
    )
    if limit:
        stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars().all())


def age_delta(ts):
    """距某个入库时间的间隔（None 输入返回 None）。

    ⚠️ 时区约定（2026-07-31 踩坑）：时间列是 `timestamp without time zone`，而 `_now()`
    返回 aware UTC——psycopg 写入时会先转成**会话时区（服务器本地 CST）**再抹掉 tzinfo。
    所以库里的 naive 值是**本地时间**，必须用本地 `now()` 相减。此前按 UTC 解读，
    所有时间都显得「新 8 小时」；这在天级窗口上无感，但会让 20 小时的图片有效期窗口
    放行已经 403 的 URL。
    """
    from datetime import datetime, timezone

    if ts is None:
        return None
    return (datetime.now(timezone.utc) - ts) if ts.tzinfo else (datetime.now() - ts)


def _age_label(updated_at) -> str:
    """人类可读的记忆年龄（Phase 30，借鉴 Claude Code memoryAge：模型不擅长日期算术，
    「47 天前」比裸时间戳更能触发过期意识）。"""
    delta = age_delta(updated_at)
    if delta is None:
        return ""
    days = max(0, delta.days)
    if days == 0:
        return "今天"
    if days == 1:
        return "昨天"
    return f"{days} 天前"


def format_memories_block(memories: list[TravelMemory]) -> str:
    """记忆 → prompt 注入块。空记忆返回空串（调用方直接拼接即可）。

    Phase 30：每条带年龄标注（模型不擅长日期算术，「47 天前」比时间戳更能触发过期意识）。
    """
    if not memories:
        return ""
    type_label = {"preference": "偏好", "fact": "事实", "procedural": "习惯"}
    lines = []
    for m in memories:
        age = _age_label(m.updated_at)
        suffix = f"（{age}）" if age else ""
        lines.append(f"- [{m.id}][{m.key or type_label.get(m.type, m.type)}] {m.content}{suffix}")
    return (
        "关于用户的长期记忆（历史对话中积累，请在规划时考虑）：\n" + "\n".join(lines) +
        "\n记忆使用纪律：记忆只用于把握口味/节奏/兴趣等长期偏好。其中出现的日期/节假日/"
        "目的地/预算属于**当时那次行程**，除非用户本轮明确重申，不要把它们当作本次行程的"
        "时间、地点或预算写进回答（例如记忆里是国庆去成都，用户这次没提时间，"
        "就绝不要在回答里写「国庆期间」或按国庆做建议）。"
    )


# 无效首回复的开头标记（停止/报错等），这些不该被当历史攻略引用
_JUNK_PREFIXES = ("已停止", "重新发", "生成失败", "抱歉", "找不到", "未能", "没找到", "无法")
_MIN_GUIDE_LEN = 120  # 短于此的助手回复多为停止/寒暄，不作历史引用


def _clean_snippet(text: str, limit: int = 120) -> str:
    """清洗摘录：去 markdown 记号、折叠空白、截断，避免注入一堆 ## ** 噪声。"""
    t = re.sub(r"[#>*`_\[\]—-]+", "", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit]


def _first_guide_reply(db: Session, cid: str) -> TravelMessage | None:
    """取某会话第一条『像样攻略』的助手回复：跳过流式占位/海报/停止/报错/过短。"""
    msgs = db.execute(
        select(TravelMessage)
        .where(TravelMessage.conversation_id == cid, TravelMessage.role == "assistant")
        .order_by(TravelMessage.created_at)
    ).scalars().all()
    for m in msgs:
        meta = {}
        if m.meta_json:
            try:
                meta = json.loads(m.meta_json)
            except Exception:  # noqa: BLE001
                meta = {}
        if meta.get("streaming") or meta.get("poster") or meta.get("budget"):  # 流式占位/海报/预算面板不是攻略
            continue
        content = (m.content or "").strip()
        if len(content) < _MIN_GUIDE_LEN or content.startswith(_JUNK_PREFIXES):
            continue
        return m
    return None


def recall_past_chats(
    db: Session, user_id: str, destination: str, exclude_cid: str, limit: int = 3
) -> list[dict]:
    """检索该用户『与当前目的地相关』的历史会话（Phase 20；2026-07-31 换结构化索引）。

    改造前用**标题子串**猜目的地（标题=用户第一句话的截断）：第一句没报城市的会话永远
    漏检，多城「武汉、开封、洛阳」整串匹配几乎必然失败；且对每个命中会话再单独查一次它的
    全部 assistant 消息（N+1，单条 meta_json 最大 12KB）。

    现在读 `travel_conversation.destination`（finalize 时落的真实解析结果），按城市**重叠**
    匹配；正文直接按 `guide_message_id` 取，**固定 2 次查询**，与会话数无关。
    返回 [{conversation_id, title, snippet}]。
    """
    from app.agent.site_router import split_cities  # 复用：去重保序 + 剥「市」后缀

    want = set(split_cities(destination))
    if not want:
        return []
    rows = db.execute(
        select(
            TravelConversation.id,
            TravelConversation.title,
            TravelConversation.destination,
            TravelConversation.guide_message_id,
        )
        .where(
            TravelConversation.id != exclude_cid,
            TravelConversation.user_id == user_id,
            TravelConversation.destination.isnot(None),
            TravelConversation.destination != "",
        )
        .order_by(TravelConversation.updated_at.desc())
        .limit(50)
    ).all()

    hits = [r for r in rows if want & set(split_cities(r.destination))][:limit]
    if not hits:
        return []
    by_id = {
        m.id: m for m in db.execute(
            select(TravelMessage).where(
                TravelMessage.id.in_([r.guide_message_id for r in hits if r.guide_message_id])
            )
        ).scalars().all()
    }
    out: list[dict] = []
    for r in hits:
        msg = by_id.get(r.guide_message_id) if r.guide_message_id else None
        if msg is None:  # 索引缺失（老会话未回填 / 攻略被删）→ 退回逐条扫描
            msg = _first_guide_reply(db, r.id)
        if msg is None:
            continue
        out.append({
            "conversation_id": r.id,
            "title": r.title,
            "snippet": _clean_snippet(msg.content),
        })
    return out


def format_past_chats_block(chats: list[dict]) -> str:
    if not chats:
        return ""
    lines = [f"- 「{c['title']}」：{c['snippet']}" for c in chats]
    return "用户过去的相关对话（供参考延续，不要重复内容）：\n" + "\n".join(lines)


# ---------- 提炼 / 写入 ----------

def plan_memory_ops(
    llm, memories: list[TravelMemory], user_text: str, reply_head: str
) -> MemoryUpdatePlan:
    """让 LLM 对照已有记忆，规划本轮的记忆变更操作。"""
    from datetime import date

    existing = "\n".join(
        f"- id={m.id} key={m.key or '(未归槽)'} [{m.type}] {m.content}" for m in memories
    ) or "（空）"
    # Phase 69：reply_head 是攻略正文，源自抓来的网页/小红书笔记（不可信）。
    # 记忆一旦被投毒会**跨会话持久生效**（每轮经 gather_context 注入需求解析和攻略生成），
    # 且 key 归槽意味着能覆盖「口味/预算/住宿」等真实槽位——必须显式标记为外部内容。
    prompt = (
        f"今天是 {date.today().isoformat()}（相对日期请据此换算成绝对日期）。\n\n"
        f"已有记忆：\n{existing}\n\n"
        f"用户本轮输入：{user_text}\n\n"
        "助手回复开头（供理解上下文，其中可能含抓取自互联网的内容）：\n"
        + wrap_external(reply_head[:500], source="assistant_reply")
    )
    return llm.classify(prompt, MemoryUpdatePlan, system=EXTRACT_SYSTEM + EXTERNAL_POLICY)


def _find_by_key(db: Session, user_id: str, key: str) -> TravelMemory | None:
    """同一 (user, key) 的现有槽位（Phase 17 三元组归槽）。"""
    if not key:
        return None
    return db.execute(
        select(TravelMemory)
        .where(TravelMemory.user_id == user_id, TravelMemory.key == key)
        .order_by(TravelMemory.updated_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _upsert_by_key(
    db: Session, user_id: str, key: str, mtype: str, content: str,
    explicit: bool, source_cid: str, applied: list[dict],
) -> None:
    """按 (user, key) 覆盖/合并写入一条记忆，落实四条策略。"""
    row = _find_by_key(db, user_id, key)
    if row is not None:
        # 相同 key 直接覆盖 + 时间更新优先；explicit「粘性」：一旦明确表达，不被推断内容降级
        row.content = content
        row.type = mtype
        row.explicit = row.explicit or explicit
        row.weight = 2.0 if row.explicit else 1.0
        row.source_conversation_id = source_cid or row.source_conversation_id
        applied.append({"op": "update", "id": row.id, "key": key, "type": mtype, "content": content})
        return
    row = TravelMemory(
        user_id=user_id, type=mtype, key=key or None, content=content,
        explicit=explicit, weight=2.0 if explicit else 1.0,
        source_conversation_id=source_cid or None,
    )
    db.add(row)
    db.flush()
    applied.append({"op": "add", "id": row.id, "key": key, "type": mtype, "content": content})


def _prune(db: Session, user_id: str) -> None:
    """兜底剪枝：某用户记忆超过上限时，按 权重↓、更新时间↓ 保留前 N 条。"""
    rows = load_memories(db, user_id)
    for row in rows[settings.memory_max_rows:]:
        db.delete(row)


def apply_ops(
    db: Session, plan: MemoryUpdatePlan, user_id: str, source_cid: str = "",
    trust: str | None = None,
) -> list[dict]:
    """应用记忆操作，返回实际生效的变更（给前端展示「已记住」）。

    Phase 17：add/update 一律按 (user, key) 归槽 upsert（相同 key 覆盖合并）；delete 按 id。
    Phase 86：不再直接写库，一律经**本体 Action 层**（`app/ontology/actions.py`）——
    记忆是全系统唯一跨会话持久生效的写入，而 `plan` 的输入含攻略正文（源自不可信网页）。
    校验不过的动作被丢弃并记进日志，不影响同批其余动作。

    trust 默认 `TRUST_ASSISTANT`（模型提炼）；记忆面板等用户直接操作传 `TRUST_USER`。
    """
    from app.ontology.actions import (
        TRUST_ASSISTANT,
        ActionContext,
        DeleteMemory,
        SetMemory,
        apply_actions,
    )

    actions = []
    for op in plan.ops:
        kind = (op.op or "").strip().lower()
        if kind in ("add", "update"):
            actions.append(
                SetMemory(
                    key=(op.key or "").strip(),
                    content=(op.content or "").strip(),
                    mtype=op.type,
                    explicit=bool(op.explicit),
                    memory_id=(op.id or "").strip(),
                    rationale=f"{kind} from turn",
                )
            )
        elif kind == "delete":
            actions.append(DeleteMemory(memory_id=(op.id or "").strip(), rationale="delete from turn"))

    ctx = ActionContext(
        db=db, user_id=user_id, source_cid=source_cid, trust=trust or TRUST_ASSISTANT,
    )
    result = apply_actions(actions, ctx)
    _prune(db, user_id)
    db.commit()
    return result.applied


SELECT_SYSTEM = (
    "你在为旅行助手挑选与用户本轮消息相关的长期记忆。给你记忆清单（id/槽位/内容）和"
    "本轮消息，返回**明确会用上**的记忆 id 列表（最多 {top} 条）。\n"
    "宁缺毋滥：拿不准就不要选；一条都不相关就返回空列表。"
    "只按内容相关性判断，不要因为记忆「重要」就选。"
)


def select_relevant_memories(llm, memories: list[TravelMemory], user_text: str) -> list[TravelMemory]:
    """记忆条数多时用小模型挑相关子集（Phase 30，借鉴 Claude Code findRelevantMemories）。

    保底规则：explicit（用户亲口说的）**始终注入**不过选择器——漏掉它的代价远大于
    多占几行 prompt。其余走 LLM 挑选；LLM 失败回退全量。
    """
    always = [m for m in memories if m.explicit]
    candidates = [m for m in memories if m not in always]
    if not candidates:
        return memories
    try:
        from pydantic import BaseModel

        class _Picked(BaseModel):
            ids: list[str]

        listing = "\n".join(f"- id={m.id} [{m.key or m.type}] {m.content}" for m in candidates)
        r = llm.classify(
            f"记忆清单：\n{listing}\n\n用户本轮消息：{user_text[:300]}",
            _Picked, system=SELECT_SYSTEM.format(top=settings.memory_select_top),
        )
        picked_ids = set(r.ids[: settings.memory_select_top])
    except Exception:  # noqa: BLE001 — 选择器是增强，失败回退全量注入
        logger.warning("memory selection failed, fallback to all", exc_info=True)
        return memories
    picked = [m for m in candidates if m.id in picked_ids]
    return always + picked


# ---------- 编排层入口（内部管理 session） ----------

RECENT_PLAN_HINT_DAYS = 14  # 超过这个天数的「最近规划」不再用于指代消解


def recent_plan_hint(db: Session, user_id: str, exclude_cid: str = "") -> str:
    """跨会话指代消解用的**确定性**提示（2026-07-31，取代 trip_state 记忆槽）。

    读该用户**其它会话**里最近一条带 `destination` 的会话索引列（finalize 时落盘）。
    相比 LLM 提炼的「当前行程」记忆：永远新鲜、不丢结构、不进记忆表、不携带日期/预算
    等会被误当本次约束的字段。初版是翻最近 30 条消息的 meta_json（≈150KB 只为读一个
    城市名），换列后是一行两个短列。

    措辞是**待确认指代**而非事实断言——用户本轮报了地名就该忽略它。无数据返回空串。
    """
    row = db.execute(
        select(TravelConversation.destination, TravelConversation.updated_at)
        .where(
            TravelConversation.user_id == user_id,
            TravelConversation.id != exclude_cid,
            TravelConversation.destination.isnot(None),
            TravelConversation.destination != "",
        )
        .order_by(TravelConversation.updated_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return ""
    dest, updated_at = row
    days = _age_days(updated_at)
    if days is not None and days > RECENT_PLAN_HINT_DAYS:
        return ""
    age = _age_label(updated_at)
    when = f"（{age}）" if age else ""
    return (
        f"最近一次规划的目的地是「{dest}」{when}。仅当用户本轮**没有指明目的地**、"
        f"且像是在延续那次行程（如「帮我加一天」「那边冷不冷」）时，才把它当作本轮目的地；"
        f"用户提了别的地方就忽略这条。它只是指代线索，不代表本次的日期、预算或人数。"
    )


def _age_days(updated_at) -> int | None:
    delta = age_delta(updated_at)
    return None if delta is None else max(0, delta.days)


def gather_context(cid: str, destination: str, user_id: str, user_text: str = "") -> dict:
    """会话开始时收集记忆上下文：注入块 + 前端展示用的 memories_used（按用户隔离）。

    Phase 30：记忆条数超过 memory_select_threshold 且有本轮消息时，先用 v4-flash 挑
    相关子集再注入（宁缺毋滥）；否则维持全量注入。
    """
    from app.db.session import get_session

    if not settings.memory_enabled or not user_id:
        return {"block": "", "used": []}
    # 先取三态快照：它读的是消息表，与下面的记忆读取无依赖。放在 with 外面，
    # 免得在整个记忆块期间多占一条连接（pool_size=5）。
    try:
        previous = previous_injected_memories(cid)
    except Exception:  # noqa: BLE001
        # 读失败是基础设施问题，不是「拿不准说过什么」——这时保持静默而不是发
        # Unknown 那句重申，免得一次 DB 抖动就给每轮都加一段噪声。
        logger.warning("read previous injected memories failed cid=%s", cid, exc_info=True)
        previous = None
    with get_session() as db:
        memories = load_memories(db, user_id, limit=settings.memory_max_inject)
        # 一份新的完整规划明确覆盖旧「当前行程」；兴趣若本轮没说也不应暗中改变主题。
        from app.agent.context_security import is_explicit_itinerary_request

        # trip_state 已退役（2026-07-31）：存量行与模型偶发新造的都在这里硬挡掉，
        # 具体某次行程不再进记忆，指代消解走 recent_plan_hint。
        memories = [m for m in memories if m.type != "trip_state"]
        # 本轮库里**全部**记忆的 key（在相关性筛选之前捕获）——用于区分「真删了」与
        # 「这轮没选中」。少了这一步，一次 select_relevant_memories 就会被报成用户撤回偏好。
        all_keys = {m.key for m in memories if m.key}
        if is_explicit_itinerary_request(user_text):
            # 一份新的完整规划不应被旧的兴趣主题暗中带偏
            memories = [m for m in memories if m.key != "兴趣偏好"]
        if user_text and len(memories) > settings.memory_select_threshold:
            from app.llm.client import get_llm

            memories = select_relevant_memories(get_llm(), memories, user_text)
        _bump_hit_count(db, memories)  # Phase 45：实际注入的记忆访问频率 +1
        chats = recall_past_chats(db, user_id, destination, exclude_cid=cid)
        # 三态变更通知（2026-08-22）：对话历史承载着旧偏好，删除/更新必须显式说，
        # 否则模型只会看到自己早前基于旧偏好写下的推荐。all_keys 用**全量**记忆的 key，
        # 好把「真删了」和「本轮没被相关性筛中」区分开。
        changes, announced = "", {}
        try:
            changes, announced = format_memory_changes(previous, memories, all_keys)
        except Exception:  # noqa: BLE001 — 变更通知是增强，绝不能拖垮上下文收集
            logger.warning("memory change notice failed cid=%s", cid, exc_info=True)
        block = "\n\n".join(
            b for b in (format_memories_block(memories), changes, format_past_chats_block(chats)) if b
        )
        used = [
            {"kind": "memory", "type": m.type, "key": m.key, "content": m.content} for m in memories
        ] + [
            {"kind": "past_chat", "title": c["title"], "content": c["snippet"]} for c in chats
        ]
    # `announced` 要由调用方写进 meta.memories_changed——它是「已经说过」的账，
    # 落库失败/本轮被取消时**下一轮会重发**，方向安全（重复一句 vs 永久漏发）。
    return {"block": block, "used": used, "changes": changes, "announced": announced}


def _bump_hit_count(db: Session, memories: list[TravelMemory]) -> None:
    """被注入的记忆记一笔账：hit_count +1、last_used_at = 现在（Phase 45 / 2026-08-24）。
    写失败只 warn——记账是排序增强，绝不能因它挂掉整轮上下文收集。

    ⚠️ **这是纯记账写，绝不能碰 `updated_at`**。`updated_at` 的语义是「内容最后一次变化」，
    而 `onupdate=_now` 对本行的**任何** UPDATE 都生效（与改哪一列无关）——2026-08-24 之前
    这里用 ORM 属性赋值，于是每轮注入都把 updated_at 推到当下，`format_memories_block`
    贴进 prompt 的年龄标签（Phase 30，专为触发模型的过期意识而建）因此**永远显示「今天」**，
    越活跃的用户偏得越狠。线上 47 行里 25 行受影响。

    压住 onupdate 的唯一办法是把该列**显式列进 SET 子句**自赋值：SQLAlchemy 只在列不在
    SET 里时才套用 onupdate。有两个方向的回归测试钉住（只测「记账时不动」的话，
    把整列 onupdate 删掉也能过）。

    顺带把 Python 侧读改写换成 SQL 自增：同一用户的 direct 链路不过浏览器池，
    并发轮次会丢计数。
    """
    if not memories:
        return
    from sqlalchemy import func, update

    from app.db.models import _now

    try:
        db.execute(
            update(TravelMemory)
            .where(TravelMemory.id.in_([m.id for m in memories]))
            .values(
                hit_count=func.coalesce(TravelMemory.hit_count, 0) + 1,
                last_used_at=_now(),
                updated_at=TravelMemory.updated_at,  # ← 自赋值，压住 onupdate
            )
            .execution_options(synchronize_session=False)
        )
        db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("bump hit_count failed", exc_info=True)
        db.rollback()


CONSOLIDATE_SYSTEM = (
    "你是记忆整理助手。下面是某用户零散、重复、追加式堆积的长期记忆，请**去重、合并、归槽**，"
    "重写成一组规范三元组。\n"
    f"每条挂一个 key，优先从规范集合选：{_KEY_LIST}。近义/同类记忆合并成一条（如多条口味偏好"
    "合并为「用户爱吃海鲜、辣」）。\n"
    "「当前行程」是单槽，只保留最新那次规划的目的地；过期/一次性的行程记录目的地并入"
    "「旅行足迹」（累积去过/规划过的城市，合并时不要丢城市），只有当前正在进行的留在「当前行程」。\n"
    "同一个 key 只能出现一次。丢掉无长期价值的内容。explicit 尽量保守（拿不准填 false）。"
)


def consolidate_memories(db: Session, user_id: str, llm) -> dict:
    """一次性把某用户现有记忆重写成规范三元组并整体替换（清理存量脏数据）。

    返回 {"before": n, "after": m}。LLM 失败则原样不动。

    ⚠️ **实现是"删旧建新"，所以每条记忆的历史（建立时间/命中数/最后使用/亲述标记）默认会被
    清零**——用户点一次「整理记忆」，半年前形成的偏好就变成「建立 刚刚 · 最后使用 从未」，
    亲述标记也会被 LLM 重新臆断（CONSOLIDATE_SYSTEM 让它"拿不准填 false"，而它只看得到内容，
    本来就判不出用户当初是不是亲口说的）。

    2026-08-24 起**按 key 继承**：新行的 key 在旧行里存在就继承那一行的历史。
    key 是 Phase 17 归槽的主键，这是唯一不含猜测的映射——N 条合并成 M 条时，
    "这条新记忆的祖先是谁"没有别的可靠依据（旧行没有 key 的、或 LLM 新合成的 key，
    只能算新记忆）。`explicit` 取**或**（粘性，只升不降），对齐 `_upsert_by_key` 的语义。
    """
    rows = load_memories(db, user_id)
    before = len(rows)
    if before == 0:
        return {"before": 0, "after": 0}
    listing = "\n".join(f"- [{m.type}] {m.content}" for m in rows)
    result: MemoryConsolidation = llm.classify(
        f"用户现有记忆（{before} 条）：\n{listing}", MemoryConsolidation, system=CONSOLIDATE_SYSTEM
    )
    # key → 该 key 下旧行的历史。归槽保证一个 key 一行，但真撞上重复也要有确定归宿：
    # 建立时间取**最早**（祖先只会更老）、命中数与最后使用取**最大**（别把用量算没了）。
    ancestry: dict[str, dict] = {}
    for m in rows:
        k = (m.key or "").strip()
        if not k:
            continue                      # 无 key 的旧行没有可靠映射，其历史只能丢
        prev = ancestry.get(k)
        if prev is None:
            ancestry[k] = {
                "created_at": m.created_at, "hit_count": m.hit_count or 0,
                "last_used_at": m.last_used_at, "explicit": bool(m.explicit),
                "source_conversation_id": m.source_conversation_id,
                # 内容 → 该内容的 updated_at。整理常常只是原样带过某个 key，
                # 那种情况下内容并没有变，updated_at 不该被推到当下（否则刚修好的
                # 「年龄标签永远显示今天」会从整理这扇门重新进来）。
                "by_content": {(m.content or "").strip(): m.updated_at},
            }
            continue
        prev["created_at"] = min(filter(None, (prev["created_at"], m.created_at)), default=None)
        prev["hit_count"] = max(prev["hit_count"], m.hit_count or 0)
        stamps = [t for t in (prev["last_used_at"], m.last_used_at) if t]
        prev["last_used_at"] = max(stamps) if stamps else None
        prev["explicit"] = prev["explicit"] or bool(m.explicit)
        prev["by_content"].setdefault((m.content or "").strip(), m.updated_at)

    seen: set[str] = set()
    kept: list[TravelMemory] = []
    for t in result.memories:
        key = (t.key or "").strip()
        content = (t.content or "").strip()
        if not content or key in seen:  # 同 key 只留第一条
            continue
        seen.add(key)
        mtype = CANONICAL_KEYS.get(key) or (t.type if t.type in MEMORY_TYPES else "preference")
        past = ancestry.get(key, {})
        # explicit 只升不降：LLM 只看得到内容，判不出用户当初是不是亲口说的，
        # 而 Phase 17 的「明确表达优先」是粘性的（`_upsert_by_key` 用的也是 or）。
        explicit = bool(t.explicit) or bool(past.get("explicit"))
        row = TravelMemory(
            user_id=user_id, type=mtype, key=key or None, content=content,
            explicit=explicit, weight=2.0 if explicit else 1.0,
            hit_count=past.get("hit_count", 0),
            source_conversation_id=past.get("source_conversation_id"),
        )
        if past.get("created_at"):        # 有祖先就继承建立时间，没有就是真的新记忆
            row.created_at = past["created_at"]
        row.last_used_at = past.get("last_used_at")
        # 内容一字未改 → 这不是一次内容变更，updated_at 保持原值；改了才推到当下
        unchanged_at = past.get("by_content", {}).get(content)
        if unchanged_at:
            row.updated_at = unchanged_at
        kept.append(row)
    if not kept:  # 兜底：LLM 空结果就别把人家记忆清空
        return {"before": before, "after": before}
    for old in rows:
        db.delete(old)
    db.flush()
    for row in kept:
        db.add(row)
    db.commit()
    return {"before": before, "after": len(kept)}


def extract_and_save(cid: str, user_text: str, reply_head: str, user_id: str) -> list[dict]:
    """回复生成后同步提炼记忆（按用户隔离）。任何失败都只记日志，不阻塞回复。

    Phase 57：提炼后顺带做「睡眠整合」门控——新记忆攒够 + 距上次够久就后台整理（不阻塞本轮）。
    """
    from app.db.session import get_session
    from app.llm.client import get_llm

    if not settings.memory_enabled or not user_id:
        return []
    try:
        with get_session() as db:
            memories = load_memories(db, user_id)
            plan = plan_memory_ops(get_llm(), memories, user_text, reply_head)
            saved = apply_ops(db, plan, user_id, source_cid=cid)
        maybe_consolidate_async(user_id)  # 门控 + 后台整合，绝不阻塞回复
        return saved
    except Exception:  # noqa: BLE001
        logger.warning("memory extraction failed for %s", cid, exc_info=True)
        return []


# ---------- Phase 57：睡眠整合（chapter8 机制⑤）----------

import threading  # noqa: E402
from datetime import timedelta  # noqa: E402

_consolidating: set[str] = set()  # 正在整合的 user_id，防同一用户并发跑
_consolidate_lock = threading.Lock()


def _should_sleep_consolidate(db: Session, user_id: str) -> bool:
    """门控（纯判断、可测）：距上次整合够久 + 攒够新记忆 + 记忆总量值得整，才返回 True。"""
    from sqlalchemy import func

    from app.db.models import TravelUser, _now

    user = db.get(TravelUser, user_id)
    if user is None:
        return False
    last = user.memory_consolidated_at
    if last is not None:
        # DB TIMESTAMP 取回是 naive，_now() 是 aware——统一去 tz 再比（对齐 site_router 的处理）
        elapsed = _now().replace(tzinfo=None) - last.replace(tzinfo=None)
        if elapsed < timedelta(hours=settings.memory_consolidate_min_hours):
            return False
    base = select(func.count()).select_from(TravelMemory).where(TravelMemory.user_id == user_id)
    total = db.execute(base).scalar() or 0
    if total < settings.memory_consolidate_min_total:
        return False
    fresh_q = base if last is None else base.where(TravelMemory.updated_at > last)
    new_count = db.execute(fresh_q).scalar() or 0
    return new_count >= settings.memory_consolidate_min_new


def maybe_consolidate_async(user_id: str) -> bool:
    """轮末检查门控，满足就起后台线程整理记忆。返回是否触发（供测试/日志）。"""
    if not settings.memory_enabled or not settings.memory_sleep_consolidate_enabled or not user_id:
        return False
    try:
        from app.db.session import get_session

        with get_session() as db:
            if not _should_sleep_consolidate(db, user_id):
                return False
    except Exception:  # noqa: BLE001 — 门控查询失败不影响主流程
        logger.warning("sleep-consolidate gate failed for %s", user_id, exc_info=True)
        return False
    with _consolidate_lock:  # 同一用户同时只跑一个
        if user_id in _consolidating:
            return False
        _consolidating.add(user_id)
    threading.Thread(target=_run_sleep_consolidate, args=(user_id,), daemon=True).start()
    return True


def _run_sleep_consolidate(user_id: str) -> None:
    """后台整合 + 更新门控时间戳。失败只记日志，绝不影响用户交互。"""
    try:
        from app.db.models import TravelUser, _now
        from app.db.session import get_session
        from app.llm.client import get_llm

        with get_session() as db:
            res = consolidate_memories(db, user_id, get_llm())
            user = db.get(TravelUser, user_id)
            if user is not None:
                user.memory_consolidated_at = _now()
                db.commit()
        logger.info("sleep-consolidated memories for %s: %s", user_id, res)
    except Exception:  # noqa: BLE001
        logger.warning("sleep-consolidate failed for %s", user_id, exc_info=True)
    finally:
        with _consolidate_lock:
            _consolidating.discard(user_id)


# ---------------------------------------------------------------------------
# 记忆变更通知（三态，移植自 Codex 的 PreviousSectionState）
# ---------------------------------------------------------------------------
#
# 我们的上下文是**投影**：记忆每轮从库里现算，模型只看得到当前值，历史里不存在陈旧
# 副本——所以 Codex 那套「重复注入 + REPLACEMENT_NOTICE 消歧」我们大半不需要。
#
# 但有一格是需要的：**对话历史本身承载了旧状态**。用户第 3 轮被推荐了一堆素食馆
# （因为当时记忆里有「忌口=素食」），第 8 轮说「我现在不忌口了」→ 记忆被删。第 8 轮的
# prompt 里，历史逐字带着那些素食推荐，而记忆块里那条已经消失——模型没有任何信号
# 知道约束解除了，只看到自己过去言之凿凿的输出。这正是 Codex `agents_md.rs` 里
# `(None, previous_may_contain_instructions=true)` 那一格：**删除必须显式通知**。
#
# ⚠️ 快照必须**跨全会话聚合**，不能只跟上一轮比（2026-08-24 修）。陈旧状态是逐轮
# **累积**的：第 1 轮展示「忌口=吃素」→ 模型写下一堆素食推荐（病灶从此留在历史里），
# 第 2 轮用户问机场怎么走、忌口被 `select_relevant_memories` 筛掉，第 3 轮忌口被删——
# 只跟第 2 轮比的话 `忌口 ∉ previous`，**静默漏发**，而第 1 轮那段素食推荐还在。
# 所以 `shown` 收全会话展示过的每个 (key, value)。
#
# 代价是「恰好一次」会破（并集里那条永远在，就会每轮都发），所以**通知这个动作本身
# 也要记账**：`meta.memories_changed` 记下本轮通知过什么，下一轮据此跳过。
# 这其实更忠于 Codex——它的 `WorldStateSnapshot` 也是 merge patch 一路累积推进的。

_UNKNOWN = object()  # 三态哨兵：知道说过，但不知道说的是什么
_MISS = object()     # "从未通知过"，与"通知过移除"（记为 None）区分
_HISTORY_SCAN_LIMIT = 60  # 回溯的 assistant 消息条数上限


class InjectionHistory:
    """本会话「已经告诉过模型什么」的账本（对应 Codex 的 WorldStateSnapshot）。

    - `shown`：key → 曾经展示过的**所有**值。判据是「历史里有没有基于别的值写下的内容」，
      所以要全集，不是最后一个值。
    - `announced`：key → 上次通知的新值；`None` 表示"已通知它被移除"。
      用来保证同一次变更只通知一遍，而**再次变更仍会再通知**。
    """

    __slots__ = ("shown", "announced")

    def __init__(self, shown: dict[str, set[str]], announced: dict[str, str | None]):
        self.shown = shown
        self.announced = announced

    def __repr__(self) -> str:  # 调试用
        return f"InjectionHistory(shown={ {k: sorted(v) for k, v in self.shown.items()} }, announced={self.announced})"


def _parse_meta(m: TravelMessage) -> dict:
    if not m.meta_json:
        return {}
    try:
        return json.loads(m.meta_json)
    except Exception:  # noqa: BLE001
        return {}


def previous_injected_memories(cid: str):
    """本会话已经告诉过模型什么（三态，对应 `PreviousSectionState`）。

    - `None`               → **Absent**：本会话还没有过终稿回复，历史里不存在与记忆
      冲突的表述，无需任何通知。
    - `_UNKNOWN`           → **Unknown**：**最近**那条真回合没记下注入了什么
      （改造前的老消息）。拿不准时要通知——见 `format_memory_changes` 的代价不对称说明。
    - `InjectionHistory`   → **Known**：可精确比对。

    只用**最近一条**判 Unknown，更早的老消息只是不贡献数据而已——否则一条老消息会让
    整个会话永远停在 Unknown，那句兜底重申就会每轮都发。
    """
    from app.db.session import get_session

    with get_session() as db:
        rows = db.execute(
            select(TravelMessage)
            .where(TravelMessage.conversation_id == cid, TravelMessage.role == "assistant")
            .order_by(TravelMessage.created_at.desc())
            .limit(_HISTORY_SCAN_LIMIT)
        ).scalars().all()

    # 流式占位/海报/预算面板不是一次「模型读过记忆并作答」的回合
    turns = [
        (m, meta) for m, meta in ((m, _parse_meta(m)) for m in rows)
        if not (meta.get("streaming") or meta.get("poster") or meta.get("budget"))
    ]
    if not turns:
        return None  # Absent

    newest_meta = turns[0][1]
    newest_used = newest_meta.get("memories_used")
    if not isinstance(newest_used, list):
        return _UNKNOWN
    newest_mem = [u for u in newest_used if isinstance(u, dict) and u.get("kind") == "memory"]
    if newest_mem and not any(u.get("key") for u in newest_mem):
        # 老格式：注入过记忆却一条 key 都没有 → 比不出差异。注意与「上一轮确实一条
        # 都没注入」区分：那种情况 newest_mem 为空，是 Known（空账本）。
        return _UNKNOWN

    shown: dict[str, set[str]] = {}
    announced: dict[str, str | None] = {}
    for _m, meta in reversed(turns):  # 由旧到新回放，新的通知覆盖旧的
        for u in meta.get("memories_used") or []:
            if not isinstance(u, dict) or u.get("kind") != "memory":
                continue
            key = u.get("key")
            if key:
                shown.setdefault(key, set()).add(u.get("content", ""))
        changed = meta.get("memories_changed")
        if isinstance(changed, dict):
            announced.update(changed)
    return InjectionHistory(shown, announced)


def format_memory_changes(previous, injected: list[TravelMemory], all_keys: set[str]) -> tuple[str, dict]:
    """渲染「相对本会话早前的回复，记忆发生了什么变化」。

    返回 `(通知文本, 本轮新通知的 {key: 新值/None})`——后者由调用方写进
    `meta.memories_changed`，下一轮据此跳过，保证同一次变更只说一遍。

    只通知**更新**与**删除**，不通知新增——新增不与历史里的任何表述矛盾，说了是噪声。
    （同 Codex：`(Some, previous_absent)` 那一格原样发，不加 REPLACEMENT_NOTICE。）

    `all_keys` 是本轮库里**全部**记忆的 key，用来把「真删了」和「本轮没被
    `select_relevant_memories` 选中」区分开——后者绝不能报成删除，否则一次相关性筛选
    就会让模型以为用户撤回了偏好。

    ⚠️ **误判方向的代价不对称**（同 Phase 104 的境内外判定）：多发一句「这条已更新」
    只是几十个 token；漏发则模型继续按历史里那条已被推翻的约束作答，且用户看不出
    它为什么固执。所以 Unknown 一律往「通知」这边倒。
    """
    if previous is None:  # Absent
        return "", {}
    if previous is _UNKNOWN:
        # 比不出差异，就整体重申权威性——对应 Codex 在 Unknown 下发 REPLACEMENT_NOTICE。
        return (
            "以上记忆是**当前有效**的版本。若本对话早前的回复与它冲突，一律以上面这份为准"
            "（用户可能中途更新过偏好）。"
        ), {}

    current = {m.key: (m.content or "") for m in injected if m.key}
    lines: list[str] = []
    newly: dict[str, str | None] = {}

    for key, value in current.items():
        seen = previous.shown.get(key)
        if not seen or seen == {value}:
            continue  # 没展示过（=新增，不通知）；或展示过的全是当前这个值（=没变）
        if previous.announced.get(key, _MISS) == value:
            continue  # 这次变更已经通知过了
        lines.append(f"- 「{key}」已更新为：{value}")
        newly[key] = value

    for key in previous.shown:
        if key in all_keys:
            continue  # 库里还在——可能只是本轮没被相关性筛中，绝不能报成删除
        if previous.announced.get(key, _MISS) is None:
            continue  # 已经通知过它被移除了
        lines.append(f"- 「{key}」已被移除，不再适用")
        newly[key] = None

    if not lines:
        return "", {}
    return (
        "⚠️ 相对本对话早前的回复，以下偏好发生了变化，请以此为准（早前基于旧偏好给出的"
        "建议若与之冲突，需要主动修正）：\n" + "\n".join(lines)
    ), newly
