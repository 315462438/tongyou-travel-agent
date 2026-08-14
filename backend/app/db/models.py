import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TravelUser(Base):
    """用户（Phase 15：登录/注册 + 数据隔离）"""

    __tablename__ = "travel_user"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))  # pbkdf2$iter$salt$hash
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Phase 57：上次「睡眠整合」记忆的时间（门控频率用；空=从未整过）
    memory_consolidated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Phase 73：最近一次带 token 的请求时间（admin 在线状态用）。
    # NULL = 该列上线前就存在、之后再没来过的存量用户 → 显示「从未活跃」，不回填伪造。
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True)
    # Phase 81：公开个人主页。公开字段与账号凭证同表，避免 1:1 profile 空行；API 严格白名单序列化。
    display_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    avatar_upload_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(240), nullable=True)
    home_city: Mapped[str | None] = mapped_column(String(64), nullable=True)
    travel_styles_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_public: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TravelSession(Base):
    """登录令牌 → 用户（Phase 15）"""

    __tablename__ = "travel_session"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TravelConversation(Base):
    """对话会话（Phase 2：对话式攻略生成）"""

    __tablename__ = "travel_conversation"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)  # Phase 15
    title: Mapped[str] = mapped_column(String(256), default="新对话")
    plan_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 2026-07-31 跨会话检索索引：finalize_guide 时落盘，取代「拿标题猜目的地 + 逐会话翻消息」
    destination: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    guide_message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Phase 30 历史压缩：近 N 轮之外的早期对话折叠成结构化摘要（轮末旁路更新）
    history_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    history_summary_count: Mapped[int] = mapped_column(Integer, default=0)  # 上次折叠时覆盖到的消息数
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class TravelMessage(Base):
    """对话消息 = 会话的**只追加日志**。role: user / assistant / progress / action / summary

    Phase 91（借鉴 dsh 的 surface 投影）：模型看到的历史不是这张表本身，而是从它
    **投影**出来的 surface（见 `orchestrator.derive_surface`）。投影规则由
    `surface_op` 决定：

    - `append`（默认）：正常进入 surface；
    - `replace`：**遮蔽** `shadow_from_id`..`shadow_to_id` 这段（含两端），
      用本条顶替。压缩因此不再覆盖任何东西——摘要是追加的一条新消息，
      被它折叠的原始消息全部留在表里，可完整回放。

    改造前 `update_history_summary` 是就地改写 `conversation.history_summary`，
    每轮全量重写会把上一轮的摘要冲掉，无法回答「三天前那轮压缩后模型看到了什么」。
    """

    __tablename__ = "travel_message"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("travel_conversation.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user / assistant / progress / action / summary
    content: Mapped[str] = mapped_column(Text, default="")
    # 该条 assistant 消息对应的模型思考过程（可折叠展示）
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 附加数据：攻略结构化、来源链接、任务状态等（JSON）
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 91 surface 投影：append（默认）/ replace
    surface_op: Mapped[str] = mapped_column(String(12), default="append")
    # replace 时遮蔽的消息区间（含两端）。按 created_at 定位，不依赖自增序号。
    shadow_from_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    shadow_to_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TravelSiteLogin(Base):
    """站点扫码登录记录（Phase 9；Phase 15 按用户隔离：(user_id, site) 复合主键）"""

    __tablename__ = "travel_site_login"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    site: Mapped[str] = mapped_column(String(64), primary_key=True)
    logged_in_at: Mapped[datetime] = mapped_column(default=_now)


class TravelInflightTurn(Base):
    """在途对话轮登记（Phase 16）：进程被杀后，startup 据此从 checkpoint 续跑。"""

    __tablename__ = "travel_inflight_turn"

    cid: Mapped[str] = mapped_column(String(32), primary_key=True)
    turn_id: Mapped[str] = mapped_column(String(32))  # = 触发本轮的用户消息 id = checkpoint thread_id
    user_id: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(default=_now)


class TravelCtripCity(Base):
    """携程城市 ID 缓存（Phase 8：动态解析后落库，避免重复走页面交互）"""

    __tablename__ = "travel_ctrip_city"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    city_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TravelGeocode(Base):
    """地名→坐标缓存（Phase 55/62）。

    Phase 62 新键为 ``v2|provider|country|city|name``，并复用本表缓存城市国家上下文；
    旧 ``城市|地名`` 仅留作历史数据，不再参与海外查询。
    """

    __tablename__ = "travel_geocode"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    location: Mapped[str] = mapped_column(String(64))  # "lng,lat"
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TravelMemory(Base):
    """长期记忆（Phase 4）。type: preference（稳定偏好）/ fact（事实）/ procedural（习惯）。

    trip_state 已于 2026-07-31 退役（见 memory.CANONICAL_KEYS 注释），存量行由迁移清除。
    """

    __tablename__ = "travel_memory"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)  # Phase 15
    type: Mapped[str] = mapped_column(String(16), default="preference")
    key: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)  # Phase 17 三元组谓词
    content: Mapped[str] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    explicit: Mapped[bool] = mapped_column(default=False)  # Phase 17 用户明确表达（优先/粘性）
    hit_count: Mapped[int] = mapped_column(Integer, default=0)  # Phase 45 访问频率（注入即 +1，参与排序/剪枝）
    source_conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class TravelUserSkill(Base):
    """用户私有上传的深度研究技能（Phase 27）。只在上传者自己的深度研究会话里生效。"""

    __tablename__ = "travel_user_skill"
    __table_args__ = (UniqueConstraint("user_id", "name", name="ux_user_skill_name"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(64))  # 需与 content frontmatter 里的 name 一致
    description: Mapped[str] = mapped_column(String(1024))
    content: Mapped[str] = mapped_column(Text)  # SKILL.md 正文（含 frontmatter），单文件场景的主内容
    # 多文件技能包（Phase 27b zip 上传）：JSON {相对路径: 文本内容}，含 "SKILL.md" 自身。
    # 单文件粘贴上传时也会写这一列（{"SKILL.md": content}），保持两条路径行为一致；
    # 旧数据允许为空，skills_loader 读取时回退成 {"SKILL.md": content}。
    files_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class TravelPlan(Base):
    __tablename__ = "travel_plan"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    destination: Mapped[str] = mapped_column(String(128))
    start_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    pace: Mapped[str | None] = mapped_column(String(32), nullable=True)
    interests: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    hotel_preferences: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    status: Mapped[str] = mapped_column(String(32), default="created")
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class TravelTask(Base):
    """Agent 任务状态（评审 🟡3：落库，进程重启后可查询）"""

    __tablename__ = "travel_task"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    plan_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("travel_plan.id"), nullable=True)
    # Phase 68：归属用户，/api/agent/tasks/{id} 据此做归属校验（存量迁移归 admin）
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    # pending / running / need_user_handoff / done / failed
    current_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    handoff_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkpoint_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class TravelPage(Base):
    __tablename__ = "travel_page"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    plan_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("travel_plan.id"), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("travel_task.id"), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # hotel / guide / unknown / login_wall / captcha / payment
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TravelHotel(Base):
    __tablename__ = "travel_hotel"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    plan_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("travel_plan.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(256))
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_per_night: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pros: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    cons: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    suitability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TravelNote(Base):
    __tablename__ = "travel_note"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    plan_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("travel_plan.id"), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    spots: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    restaurants: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    tips: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    avoid_pitfalls: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TravelTrip(Base):
    """协同行程（Phase 35：多人路线规划板）"""

    __tablename__ = "travel_trip"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(256), default="新行程")
    destination: Mapped[str] = mapped_column(String(64), default="")
    days: Mapped[int] = mapped_column(Integer, default=2)
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)  # Phase 36 预算总额（元）
    # Phase 51 结构化导入：计划预算按类别拆分 JSON dict（住宿/交通/餐饮/门票/大交通/其他 → 金额）
    budget_breakdown_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 54：逐日类型/过夜城市，以及攻略里的酒店候选（候选不等于已预订住宿）。
    day_plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    hotel_recommendations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[str | None] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD，天气检查用
    # Phase 36 对话联动：从攻略消息导入时记录来源，板上可跳回原对话
    source_conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    invite_token: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)  # Phase 42 分享链接
    ai_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # seeding/reviewing/failed
    ai_review: Mapped[str | None] = mapped_column(Text, nullable=True)  # AI 检查建议（面板展示）
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class TravelTripMember(Base):
    """行程成员（owner 也占一行，role=owner；被邀请者 role=editor）"""

    __tablename__ = "travel_trip_member"

    trip_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default="editor")
    status: Mapped[str] = mapped_column(String(16), default="accepted")  # 35b: pending=待接受邀请
    last_seen: Mapped[datetime | None] = mapped_column(nullable=True)  # Phase 38 presence
    editing_day: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 正在看第几天
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TravelTripStop(Base):
    """行程地点条目。location 为 "lng,lat"（国内高德/海外 WGS84）；查不到时为空。"""

    __tablename__ = "travel_trip_stop"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(String(32), index=True)
    day: Mapped[int] = mapped_column(Integer, default=1)
    order_no: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Phase 36 卡片字段（全选填）
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # HH:MM
    stay_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transport: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 步行/驾车/公交/打车/骑行
    ticket_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    tags: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 逗号分隔
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TravelTripSuggestion(Base):
    """AI 提案（Phase 37）：AI 永不直接改行程，改动以 diff 提案落表，人工采纳/拒绝/恢复。"""

    __tablename__ = "travel_trip_suggestion"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32))  # 发起人
    prompt: Mapped[str] = mapped_column(Text, default="")
    reply: Mapped[str] = mapped_column(Text, default="")  # AI 回复/解释（AI Explain）
    diff_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # [{op,...,reason}]
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # pending / answered（纯问答无改动）/ applied / rejected / reverted
    snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # apply 前的 stops 快照
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TravelTripComment(Base):
    """地点评论（Phase 38）"""

    __tablename__ = "travel_trip_comment"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(String(32), index=True)
    stop_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TravelTripChatMessage(Base):
    """行程群聊消息（Phase 61）：行程级公共讨论，不绑定具体地点。"""

    __tablename__ = "travel_trip_chat_message"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=_now, index=True)


class TravelTripEvent(Base):
    """修改记录（Phase 38）：谁在何时做了什么（轻量 activity log，不做快照回滚源）。"""

    __tablename__ = "travel_trip_event"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TravelTripExpense(Base):
    """行程记账（Phase 41）：多人 AA，participants_json 为参与分摊的 user_id 列表。"""

    __tablename__ = "travel_trip_expense"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(String(32), index=True)
    payer_user_id: Mapped[str] = mapped_column(String(32))  # 垫付人
    amount: Mapped[float] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(16), default="其他")
    participants_json: Mapped[str] = mapped_column(Text)  # JSON [user_id, ...]
    # 花费发生的日期（YYYY-MM-DD）。与 created_at 分开：补记昨天的账很常见，
    # 记账时间不等于花钱时间。空 = 未填，展示时回落 created_at。
    spent_at: Mapped[str] = mapped_column(String(10), default="")
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TravelSupportMessage(Base):
    """客服会话消息（Phase 73）：每个用户与管理员之间**一条常驻会话**，不做工单状态流转。

    未读**不另建 thread 表**，直接由 `read_at` 算，两个方向对称：
      admin 未读 = sender='user'  AND read_at IS NULL
      用户未读   = sender='admin' AND read_at IS NULL
    读取即标记已读，语义简单，不会出现计数与消息对不上的漂移。
    """

    __tablename__ = "travel_support_message"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # 会话归属的普通用户（不是发送者）——admin 回复时这里仍是对方的 id
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    sender: Mapped[str] = mapped_column(String(8))  # user | admin
    content: Mapped[str] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True)


class TravelInviteCode(Base):
    """邀请码（Phase 74）：取代写死在 .env 的单一常量，由管理员按需生成。

    每码限量（默认 5 人），用满即失效，需要再生成新的。停用只置 active=False 不删行，
    保留「谁的码带进来多少人」的审计痕迹。
    """

    __tablename__ = "travel_invite_code"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_by: Mapped[str] = mapped_column(String(32))
    max_uses: Mapped[int] = mapped_column(Integer, default=5)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TravelAnnouncement(Base):
    """公告（Phase 74）：管理员一键推送给所有账号。"""

    __tablename__ = "travel_announcement"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True)


class TravelAnnouncementRead(Base):
    """公告已读标记（Phase 74）。

    **不给每个用户复制一份公告**——28 用户 × N 条 = 纯写放大。未读改为推导：
    「存在公告，且我没有对应的已读行」。发布一条公告只写 1 行。
    """

    __tablename__ = "travel_announcement_read"

    announcement_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TravelUpload(Base):
    """用户上传的图片（Phase 74）：客服会话与行程群聊共用。

    只存元数据，字节落磁盘（`settings.upload_dir`）。文件名一律用 uuid，
    **绝不使用用户提供的文件名**（路径穿越）。
    """

    __tablename__ = "travel_upload"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    mime: Mapped[str] = mapped_column(String(32))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TravelFriendship(Base):
    """好友申请与关系（Phase 81）。一对用户全生命周期只保留一行。"""

    __tablename__ = "travel_friendship"
    __table_args__ = (
        UniqueConstraint("user_low_id", "user_high_id", name="ux_friendship_pair"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_low_id: Mapped[str] = mapped_column(String(32), index=True)
    user_high_id: Mapped[str] = mapped_column(String(32), index=True)
    requester_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now)


class TravelRelayPost(Base):
    """目的地接力站公开内容（Phase 81）。"""

    __tablename__ = "travel_relay_post"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    destination: Mapped[str] = mapped_column(String(64), index=True)
    phase: Mapped[str] = mapped_column(String(16), index=True)  # planning/on_trip/returned
    kind: Mapped[str] = mapped_column(String(16), index=True)  # condition/route/question
    content: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True)


class TravelRelayReaction(Base):
    """接力反馈：同一用户对同一内容只有一个当前判断。"""

    __tablename__ = "travel_relay_reaction"
    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="ux_relay_reaction_user"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    post_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    reaction: Mapped[str] = mapped_column(String(16))  # useful/verified/outdated
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TravelNotification(Base):
    """统一社交通知（Phase 84）。

    公告仍使用「一条公告 + 每用户已读行」避免写放大；好友/反馈是定向事件，直接按接收者落通知。
    dedupe_key 保证同一好友关系或同一用户对同一接力只保留一个当前事件。
    """

    __tablename__ = "travel_notification"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="ux_notification_dedupe"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(128))
    body: Mapped[str] = mapped_column(String(320), default="")
    target_kind: Mapped[str] = mapped_column(String(24), default="")
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(160))
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, index=True)


class TravelTripFood(Base):
    """行程美食清单（Phase 87，PRD 模块2）。"""

    __tablename__ = "travel_trip_food"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(24), default="正餐")  # 小吃/正餐/甜点/自定义
    city: Mapped[str] = mapped_column(String(64), default="")
    price: Mapped[float | None] = mapped_column(Float, nullable=True)  # 人均参考价
    note: Mapped[str] = mapped_column(String(200), default="")
    is_top: Mapped[bool] = mapped_column(Boolean, default=False)  # TOP 排行徽章
    created_by: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True)


class TravelTripPackingItem(Base):
    """行李清单的一行物品（Phase 87，PRD 模块6）。"""

    __tablename__ = "travel_trip_packing_item"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(24), default="通用")
    order_no: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TravelTripPackingState(Base):
    """行李三态格子：一行一个 (物品, 成员)（Phase 87）。

    **刻意不把状态挂成 item 上的 JSON**：三态格是多人高频并发点击，整体覆写 JSON 会互相
    冲掉（本项目 2.5s 轮询，冲突窗口真实存在）；一行一格让并发点击落在不同行上。

    `user_id` 是**这一格属于谁**；`updated_by` 是**最后是谁改的**。允许代别人勾
    （出发前一个人统一核对是真实场景），两者不同时界面显示「由 X 代勾」。
    """

    __tablename__ = "travel_trip_packing_state"

    item_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    trip_id: Mapped[str] = mapped_column(String(32), index=True)
    state: Mapped[str] = mapped_column(String(12), default="na")  # packed/unpacked/na
    updated_by: Mapped[str] = mapped_column(String(32), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now)


class TravelTripTip(Base):
    """行程避坑提示（Phase 87，PRD 模块7）。"""

    __tablename__ = "travel_trip_tip"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(String(32), index=True)
    level: Mapped[str] = mapped_column(String(12), default="notice")  # important(红)/notice(橙)
    content: Mapped[str] = mapped_column(String(300))
    created_by: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True)


class TravelGuideObject(Base):
    """本体对象存储（Phase 86）：一条攻略消息 ↔ 一份规范化行程对象图。

    此前 poster / budget / 行程导入各自用 LLM 从攻略 Markdown 再解析一遍——三次调用、
    三份互不一致的结果、还都截断丢数据。现在只抽一次落这里，下游全部从对象图投影。

    - `message_id` 唯一：一条攻略消息只有一份对象图。
    - `source_hash` 是攻略正文的哈希：多轮修改重写了正文就重建，避免拿旧对象图配新正文。
    - `schema_version` 对不上（对象结构升级）同样重建。
    """

    __tablename__ = "travel_guide_object"
    __table_args__ = (
        UniqueConstraint("message_id", name="ux_guide_object_message"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    message_id: Mapped[str] = mapped_column(String(32), index=True)
    conversation_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    source_hash: Mapped[str] = mapped_column(String(40), default="")
    destination: Mapped[str] = mapped_column(String(64), default="")
    days_count: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now)
