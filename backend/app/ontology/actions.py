"""Action 层（Phase 86）

Palantir 本体的第三件套，也是最要紧的一件：**对象状态只能经 Action 修改**，
每个 Action 有类型化参数、前置校验（submission criteria）和审计记录。

## 为什么记忆写入首先需要它

Phase 69 的结论是「这类问题必须在工具层堵，prompt 写规矩没用」，但当时记忆写入这条路
只加了 `EXTERNAL_POLICY`（还是 prompt）。而记忆是全系统**唯一会跨会话持久生效**的写入：
`plan_memory_ops` 的输入含 `reply_head`（攻略正文，源自抓来的网页/小红书笔记），
模型据此产出的 add/update/delete 此前**直接落库**，且按 key 归槽意味着能覆盖
「口味/预算/住宿」等真实槽位。

这里把它变成确定性防线（全部**与措辞无关**，纯结构校验）：
1. 记忆内容不允许出现 URL / Markdown 图片 —— 记忆每轮都会被注入 prompt，
   带外链的记忆是**持久化**的数据外带通道（Phase 69 ③ 是单轮版本，这是跨会话版本）；
2. 记忆内容不允许出现上下文标签字面量（`</external_content>` 等）—— 否则一条被写进
   记忆的标签能在**之后每一轮**把注入内容洗白成可信区；
3. 内容与 key 的长度/形态约束 —— 挡住「把整段网页塞进一个槽位」；
4. 删除必须属于本人；单个动作失败不拖垮同批其余动作。

刻意**不做**的两件事：
- 「忽略之前的指令」这类措辞过滤。沿用 `context_security` 的判断——措辞变体无穷，
  角色标记 + 结构化校验才是主防线。
- **不碰 explicit 覆盖语义**。`_upsert_by_key` 允许后续推断内容覆盖 explicit 槽位的
  内容、只保留粘性权重，这是 Phase 17 有意的产品决策（记忆以最新为准），
  `test_explicit_is_sticky_and_weighted` 明确断言了它。想改是产品取舍，不是安全修复，
  这里不擅自翻案——权衡见改造文档「留给产品决定的一个张力」。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 记忆内容长度上限：正常三元组值都很短，超长基本是把整段攻略/网页塞进来了
MAX_MEMORY_CONTENT = 300
MAX_MEMORY_KEY = 32  # 槽位名是短谓词（「口味偏好」），不是一段话

# 数据外带向量：记忆每轮进 prompt，带外链等于给注入者一条持久通道
_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\([^)]*\)")
_TAG_LITERAL_RE = re.compile(r"(?i)</?\s*(?:external_content|background_memory|conversation_summary)")

# 写入来源可信度。当前只进审计日志（回答「这条记忆是谁写的」），不参与放行判定——
# 校验规则对两种来源一视同仁。留着是因为审计需要 provenance，且后续要加差异化策略时
# 接口已经在位；**不要**据此推断它现在有安全效果。
TRUST_USER = "user"           # 用户在界面上的直接操作（记忆面板增删）
TRUST_ASSISTANT = "external"  # LLM 从含外部内容的上下文里提炼出来的


@dataclass(frozen=True)
class Violation:
    code: str
    message: str


@dataclass
class ActionContext:
    """Action 执行上下文。db 由调用方管理事务（Action 只负责 flush，不 commit）。"""

    db: object
    user_id: str
    source_cid: str = ""
    trust: str = TRUST_ASSISTANT


@dataclass
class ActionResult:
    applied: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)


class Action:
    """所有写入动作的基类。

    `rationale` 对应 Palantir 的 action rationale，也就是本项目 `ChangeOp.reason`
    已经在做的事——「为什么这么改」和改动本身一起留存。
    """

    action_type: str = "action"

    def __init__(self, rationale: str = "") -> None:
        self.rationale = (rationale or "").strip()

    def validate(self, ctx: ActionContext) -> list[Violation]:  # pragma: no cover - 抽象
        raise NotImplementedError

    def apply(self, ctx: ActionContext) -> dict | None:  # pragma: no cover - 抽象
        raise NotImplementedError

    def describe(self) -> dict:
        return {"action": self.action_type, "rationale": self.rationale}


def _content_violations(content: str) -> list[Violation]:
    """记忆内容的通用校验（与来源无关）。"""
    out: list[Violation] = []
    if not content:
        out.append(Violation("empty_content", "内容为空"))
        return out
    if len(content) > MAX_MEMORY_CONTENT:
        out.append(
            Violation("content_too_long", f"内容超过 {MAX_MEMORY_CONTENT} 字（{len(content)}）")
        )
    if _MD_LINK_RE.search(content) or _URL_RE.search(content):
        # 记忆每轮注入 prompt；带外链的记忆是持久化的数据外带通道
        out.append(Violation("content_has_url", "记忆内容不允许包含链接或图片"))
    if _TAG_LITERAL_RE.search(content):
        out.append(Violation("content_has_tag", "记忆内容不允许包含上下文标签字面量"))
    return out


class SetMemory(Action):
    """写入/覆盖一条长期记忆（按 (user_id, key) 归槽，Phase 17 语义不变）。"""

    action_type = "set_memory"

    def __init__(
        self, *, key: str, content: str, mtype: str = "preference",
        explicit: bool = False, memory_id: str = "", rationale: str = "",
    ) -> None:
        super().__init__(rationale)
        self.key = (key or "").strip()
        self.content = (content or "").strip()
        self.mtype = mtype
        self.explicit = bool(explicit)
        self.memory_id = (memory_id or "").strip()

    def validate(self, ctx: ActionContext) -> list[Violation]:
        out = _content_violations(self.content)
        if self.key and (len(self.key) > MAX_MEMORY_KEY or "\n" in self.key):
            # 槽位名是给人看的短谓词（「口味偏好」）。一整段文字当 key 只可能来自注入或
            # 模型跑飞，放行会污染归槽机制本身。
            out.append(Violation("bad_key", "槽位名不合法（过长或含换行）"))
        return out

    def apply(self, ctx: ActionContext) -> dict | None:
        from app.agent.memory import CANONICAL_KEYS, MEMORY_TYPES, _upsert_by_key
        from app.db.models import TravelMemory

        mtype = CANONICAL_KEYS.get(self.key) or (
            self.mtype if self.mtype in MEMORY_TYPES else "preference"
        )
        explicit = self.explicit

        applied: list[dict] = []
        if self.key:
            _upsert_by_key(
                ctx.db, ctx.user_id, self.key, mtype, self.content,
                explicit, ctx.source_cid, applied,
            )
            return applied[0] if applied else None

        # 无 key 但有 id：按 id 改（兼容 Phase 17 归槽之前的存量散条）
        if self.memory_id:
            row = ctx.db.get(TravelMemory, self.memory_id)
            if row is None or row.user_id != ctx.user_id:
                return None
            row.content, row.type = self.content, mtype
            return {"op": "update", "id": row.id, "type": mtype, "content": self.content}

        # 既无 key 也无 id：插入散条。**保留这条旧路径是刻意的**——归槽是目标，但静默丢掉
        # 一条合法记忆比多一条散条更糟；散条由 `_prune` 和睡眠整合兜底收敛。
        row = TravelMemory(
            user_id=ctx.user_id, type=mtype, content=self.content, explicit=explicit,
            weight=2.0 if explicit else 1.0, source_conversation_id=ctx.source_cid or None,
        )
        ctx.db.add(row)
        ctx.db.flush()
        return {"op": "add", "id": row.id, "type": mtype, "content": self.content}


class DeleteMemory(Action):
    """删除一条长期记忆。"""

    action_type = "delete_memory"

    def __init__(self, *, memory_id: str, rationale: str = "") -> None:
        super().__init__(rationale)
        self.memory_id = (memory_id or "").strip()

    def validate(self, ctx: ActionContext) -> list[Violation]:
        from app.db.models import TravelMemory

        if not self.memory_id:
            return [Violation("no_target", "未指定要删除的记忆 id")]
        row = ctx.db.get(TravelMemory, self.memory_id)
        if row is None:
            return [Violation("not_found", "记忆不存在")]
        if row.user_id != ctx.user_id:
            # 跨用户越权：不区分「不存在」和「不属于你」，避免泄露存在性（同 Phase 68）
            return [Violation("not_found", "记忆不存在")]
        return []

    def apply(self, ctx: ActionContext) -> dict | None:
        from app.db.models import TravelMemory

        row = ctx.db.get(TravelMemory, self.memory_id)
        if row is None or row.user_id != ctx.user_id:
            return None
        rec = {"op": "delete", "id": row.id, "type": row.type, "content": row.content}
        ctx.db.delete(row)
        return rec


def apply_actions(actions: list[Action], ctx: ActionContext) -> ActionResult:
    """校验 → 应用 → 审计。校验不过的动作被丢弃并记账，不影响其余动作。

    审计走结构化日志而非独立审计表：这是个人量级平台，一条 warning 日志 + 返回给前端的
    `applied` 列表已经能回答「记忆为什么变了/为什么没变」。真需要可回溯的审计流水时
    再加表（此处刻意不提前做）。
    """
    result = ActionResult()
    for act in actions:
        violations = act.validate(ctx)
        if violations:
            for v in violations:
                result.rejected.append({**act.describe(), "code": v.code, "message": v.message})
                logger.warning(
                    "action rejected type=%s code=%s user=%s cid=%s trust=%s: %s",
                    act.action_type, v.code, ctx.user_id, ctx.source_cid, ctx.trust, v.message,
                )
            continue
        try:
            rec = act.apply(ctx)
        except Exception:  # noqa: BLE001 — 单个动作失败不拖垮整批
            logger.warning("action apply failed type=%s", act.action_type, exc_info=True)
            result.rejected.append({**act.describe(), "code": "apply_failed", "message": "执行失败"})
            continue
        if rec:
            result.applied.append(rec)
    return result
