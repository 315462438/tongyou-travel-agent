import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.orchestrator import run_conversation_turn
from app.agent.site_router import handoff_screenshot_path
from app.api.deps import get_current_user
from app.config import settings
from app.db.models import TravelConversation, TravelMessage, TravelUpload, TravelUser
from app.db.session import get_db

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _owned(db: Session, cid: str, user: TravelUser) -> TravelConversation:
    """取会话并校验归属当前用户，否则 404（不泄露他人会话存在与否）。"""
    conv = db.get(TravelConversation, cid)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "conversation not found")
    return conv


class CreateConvResponse(BaseModel):
    conversation_id: str


class SendMessageRequest(BaseModel):
    content: str
    deep_reasoning: bool = False  # 深度推理开关（Phase 23）：开则本轮强制走研究模式
    sandbox_enabled: bool = False  # 沙箱执行开关（Phase 27c）：本轮深度研究是否给 agent 代码执行能力
    # （最终是否生效还要看服务器 docker_sandbox_enabled 是否开启，见 _build_backend）
    image_ids: list[str] = Field(default_factory=list)  # Phase 105：随消息带的图（复用 Phase 74 上传）


class ConfirmRequest(BaseModel):
    confirm_id: str
    choice: str  # login / skip


# 子代理面板里**只在点开详情时才需要**的重字段（Phase 94）。
# 完整输入输出加起来一个子代理能有两万字，4 个就是几十 KB；`/messages` 是
# 800ms 一轮的轮询接口，全带上纯属浪费带宽。详情走 `/subagents/{run_id}` 按需取。
_SUBAGENT_HEAVY = ("prompt_full", "output")


def _light_meta(meta: dict | None) -> dict | None:
    if not isinstance(meta, dict):
        return meta
    runs = meta.get("subagents")
    if not isinstance(runs, list):
        return meta
    slim = [{k: v for k, v in r.items() if k not in _SUBAGENT_HEAVY}
            if isinstance(r, dict) else r for r in runs]
    return {**meta, "subagents": slim}


def _msg_dict(m: TravelMessage) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "reasoning": m.reasoning,
        "meta": _light_meta(json.loads(m.meta_json) if m.meta_json else None),
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.post("/conversations", response_model=CreateConvResponse)
def create_conversation(db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    conv = TravelConversation(user_id=user.id)
    db.add(conv)
    db.commit()
    return CreateConvResponse(conversation_id=conv.id)


@router.delete("/conversations/{cid}")
def delete_conversation(cid: str, db: Session = Depends(get_db),
                        user: TravelUser = Depends(get_current_user)):
    _owned(db, cid, user)
    db.query(TravelMessage).filter(TravelMessage.conversation_id == cid).delete()
    db.query(TravelConversation).filter(TravelConversation.id == cid).delete()
    db.commit()
    return {"status": "deleted"}


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """当前用户的会话列表。按最后一条消息时间排序（conv.updated_at 不随发消息刷新）。"""
    from sqlalchemy import func

    last_msg = (
        select(
            TravelMessage.conversation_id,
            func.max(TravelMessage.created_at).label("last_active"),
        )
        .group_by(TravelMessage.conversation_id)
        .subquery()
    )
    rows = db.execute(
        select(TravelConversation, last_msg.c.last_active)
        .outerjoin(last_msg, last_msg.c.conversation_id == TravelConversation.id)
        .where(TravelConversation.user_id == user.id)
        .order_by(func.coalesce(last_msg.c.last_active, TravelConversation.updated_at).desc())
    ).all()
    # Phase 51 批6：标题去重——同名会话（如多份「成都攻略」）从第 2 个起附日期区分，避免侧栏一片同名
    out = []
    seen: dict[str, int] = {}
    for c, last_active in rows:
        ts = last_active or c.updated_at
        title = c.title or "新对话"
        n = seen.get(title, 0)
        seen[title] = n + 1
        disp = title if n == 0 else f"{title} · {ts.strftime('%m-%d')}"
        out.append({"id": c.id, "title": disp, "updated_at": ts.isoformat()})
    return out


def _own_image_ids(db: Session, ids: list[str], user: TravelUser) -> list[str]:
    """过滤出**属于当前用户**的上传 id，并截到上限。

    不抛异常而是静默丢弃越权/不存在的 id：前端不会构造这种请求，构造了的是攻击者，
    给他一个明确的 403 反而是在确认「这个 id 存在但不是你的」。
    """
    wanted = [i for i in (ids or []) if i][: settings.vision_max_user_images]
    if not wanted:
        return []
    rows = db.execute(
        select(TravelUpload).where(
            TravelUpload.id.in_(wanted), TravelUpload.user_id == user.id)
    ).scalars().all()
    owned = {r.id for r in rows}
    return [i for i in wanted if i in owned]


@router.post("/{cid}/messages")
def send_message(
    cid: str, req: SendMessageRequest, background: BackgroundTasks,
    db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user),
):
    conv = _owned(db, cid, user)
    # 并发轮防护（Phase 92）：同一会话同时只允许一轮在跑。
    # 没有这道门时，发送按钮连点两下 = 两条用户消息 + **两个并发的 run_conversation_turn**：
    # 各建各的流式占位、进度交错、记忆提炼跑两遍、finalize 互相覆盖，
    # 而 cancel 是按 cid 的，停止按钮也说不清停的是哪一轮（线上实测双发）。
    # 复用 `_is_running`——它自带 turn_stale_min 过期兜底，后台任务被杀不会永久锁死输入框。
    existing = db.execute(
        select(TravelMessage)
        .where(TravelMessage.conversation_id == cid, TravelMessage.role != "summary")
        .order_by(TravelMessage.created_at)
    ).scalars().all()
    if _is_running(existing):
        # 409 而不是 400：这是**状态冲突**，前端据此静默忽略重复点击（不弹错误吓人）
        raise HTTPException(409, "这轮还在进行中，等它结束再发下一条")

    # Phase 105：带图消息。**必须校验归属**——只能引用自己名下的 upload，
    # 否则拿别人的 uuid 就能让模型读别人的图（`GET /api/uploads/{id}` 故意不鉴权，
    # 防护本来只靠 id 不可枚举；这里是第二道，也是真正按用户隔离的那道）。
    image_ids = _own_image_ids(db, req.image_ids, user)

    user_msg = TravelMessage(conversation_id=cid, role="user", content=req.content)
    if image_ids:
        user_msg.meta_json = json.dumps({"images": image_ids}, ensure_ascii=False)
    db.add(user_msg)
    # 首条用户消息作为会话标题。带图但没打字时用占位，不留「新对话」
    if conv.title == "新对话":
        conv.title = (req.content[:30] or ("图片消息" if image_ids else "新对话"))
    db.commit()
    # turn_id = 用户消息 id，作为 checkpoint thread_id（每轮唯一，天然 fresh）
    background.add_task(
        run_conversation_turn, cid, req.content, user.id, user_msg.id,
        req.deep_reasoning, req.sandbox_enabled, image_ids,
    )
    return {"status": "running", "user_message_id": user_msg.id}


@router.post("/{cid}/stop")
def stop_turn(cid: str, db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """停止本轮生成（Phase 16）。协作式取消：在下一个检查点生效。"""
    from app.agent.cancel import request_cancel

    _owned(db, cid, user)
    request_cancel(cid)
    return {"status": "stopping"}


class PosterRequest(BaseModel):
    message_id: str


@router.post("/{cid}/poster")
def make_poster(cid: str, req: PosterRequest, background: BackgroundTasks,
                db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """从某条攻略消息生成手账海报（Phase 13）。后台任务，前端轮询取结果。"""
    from app.agent.poster import generate_poster

    _owned(db, cid, user)
    if db.get(TravelMessage, req.message_id) is None:
        raise HTTPException(404, "message not found")
    background.add_task(generate_poster, cid, req.message_id)
    return {"status": "running"}


class BudgetRequest(BaseModel):
    message_id: str


@router.post("/{cid}/budget")
def make_budget(cid: str, req: BudgetRequest, background: BackgroundTasks,
                db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """从某条攻略消息统计预算明细 + 预约提醒（Phase 67）。后台任务，前端轮询取结果。"""
    from app.agent.budget import generate_budget

    _owned(db, cid, user)
    if db.get(TravelMessage, req.message_id) is None:
        raise HTTPException(404, "message not found")
    background.add_task(generate_budget, cid, req.message_id)
    return {"status": "running"}


@router.post("/{cid}/confirm")
def confirm_choice(cid: str, req: ConfirmRequest, db: Session = Depends(get_db),
                   user: TravelUser = Depends(get_current_user)):
    """用户对确认卡片（需登录来源等）的选择。落 role=action 隐藏消息，后台轮询读取。"""
    _owned(db, cid, user)
    if req.choice not in ("login", "skip"):
        raise HTTPException(400, "choice must be login or skip")
    db.add(TravelMessage(
        conversation_id=cid, role="action", content="",
        meta_json=json.dumps({"confirm_reply": {"confirm_id": req.confirm_id, "choice": req.choice}}),
    ))
    db.commit()
    return {"status": "ok"}


@router.get("/{cid}/handoff-screenshot")
def handoff_screenshot(cid: str, db: Session = Depends(get_db)):
    """登录墙接管期间的登录页实时截图（Phase 5，前端 4s 轮询展示扫码）"""
    if db.get(TravelConversation, cid) is None:
        raise HTTPException(404, "conversation not found")
    path = handoff_screenshot_path(cid)
    if not os.path.exists(path):
        raise HTTPException(404, "no active handoff screenshot")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# 逐条预览长度：够看清是哪一条即可，全文去对话流看（被遮蔽的原文也还在那儿）
_SURFACE_PREVIEW = 300


@router.get("/{cid}/surface")
def get_surface_stats(cid: str, db: Session = Depends(get_db),
                      user: TravelUser = Depends(get_current_user)):
    """日志 vs 投影（Phase 91）：这个会话记了多少条、其中多少条进了模型上下文。

    回答的是「压缩到底压掉了什么」——只追加日志里被遮蔽的消息仍然在，
    但不再进上下文。前端把这两个数并排显示，压缩是否生效一眼可见。
    """
    from app.agent.orchestrator import derive_surface
    from app.db.models import TravelMessage

    _owned(db, cid, user)
    rows = db.execute(
        select(TravelMessage)
        .where(TravelMessage.conversation_id == cid)
        .order_by(TravelMessage.created_at)
    ).scalars().all()

    logged = [m for m in rows if m.role in ("user", "assistant", "summary")]
    surface = derive_surface(cid)
    surface_ids = {m.id for m in surface}
    shadowed = [m for m in logged if m.id not in surface_ids]
    summaries = [m for m in surface if m.role == "summary"]

    # 谁被谁遮蔽：把 replace 事件的区间摊平成 消息id → 遮蔽它的摘要id
    order = {m.id: i for i, m in enumerate(logged)}
    shadowed_by: dict[str, str] = {}
    for m in logged:
        if m.surface_op != "replace":
            continue
        lo, hi = order.get(m.shadow_from_id or "", 0), order.get(m.shadow_to_id or "", -1)
        for i in range(lo, min(hi, order.get(m.id, 0) - 1) + 1):
            shadowed_by[logged[i].id] = m.id

    return {
        # 日志侧：只追加，永不删除
        "logged": len(logged),
        "loggedChars": sum(len(m.content or "") for m in logged),
        # 投影侧：模型实际看到的
        "surface": len(surface),
        "surfaceChars": sum(len(m.content or "") for m in surface),
        # 被遮蔽的（压缩掉的原文，仍可回放）
        "shadowed": len(shadowed),
        "shadowedChars": sum(len(m.content or "") for m in shadowed),
        "summaries": [
            {"id": m.id, "chars": len(m.content or ""), "preview": (m.content or "")[:120]}
            for m in summaries
        ],
        # 其余角色（进度/隐藏动作）不参与上下文，单独计数避免看起来「丢了」
        "nonContext": len(rows) - len(logged),
        # 逐条明细：展开后能看到日志里到底有什么、哪几条被谁遮蔽了
        "entries": [
            {
                "id": m.id,
                "role": m.role,
                "chars": len(m.content or ""),
                "surfaceOp": m.surface_op or "append",
                "inSurface": m.id in surface_ids,
                "shadowedBy": shadowed_by.get(m.id),
                "at": m.created_at.isoformat() if m.created_at else "",
                # 预览够看清是哪一条；要读全文去对话流（被遮蔽的原文也还在那儿）
                "preview": (m.content or "")[:_SURFACE_PREVIEW],
                "truncated": len(m.content or "") > _SURFACE_PREVIEW,
            }
            for m in logged
        ],
    }


@router.get("/{cid}/messages")
def get_messages(cid: str, db: Session = Depends(get_db),
                 user: TravelUser = Depends(get_current_user)):
    _owned(db, cid, user)
    msgs = db.execute(
        select(TravelMessage)
        .where(TravelMessage.conversation_id == cid,
               # Phase 91：summary 是投影产物（压缩摘要），不是对话气泡。
               # 不排掉的话它会当成一条消息渲染进对话流里。要看它去「轨迹」页。
               TravelMessage.role != "summary")
        .order_by(TravelMessage.created_at)
    ).scalars().all()
    return {"messages": [_msg_dict(m) for m in msgs], "running": _is_running(msgs)}


@router.get("/{cid}/subagents/{run_id}")
def get_subagent_detail(cid: str, run_id: str, db: Session = Depends(get_db),
                        user: TravelUser = Depends(get_current_user)):
    """某个子代理的**完整**派发内容与回复（Phase 94，点开面板某一条时才调）。

    数据源就是 `SubagentTracker` 写的那条 progress 消息的 meta——不另建表：
    子代理详情的生命周期与那条消息完全一致（会话删了它也就没了），
    单独存一张表只会多一处要同步删除的地方。
    """
    _owned(db, cid, user)
    rows = db.execute(
        select(TravelMessage)
        .where(TravelMessage.conversation_id == cid, TravelMessage.role == "progress")
        .order_by(TravelMessage.created_at.desc())
    ).scalars().all()
    for m in rows:
        if not m.meta_json:
            continue
        try:
            runs = (json.loads(m.meta_json) or {}).get("subagents")
        except Exception:  # noqa: BLE001 — 坏 meta 不该让整个接口 500
            continue
        if not isinstance(runs, list):
            continue
        for r in runs:
            if isinstance(r, dict) and r.get("id") == run_id:
                return r
    raise HTTPException(status_code=404, detail="subagent run not found")


def _streaming(m: TravelMessage) -> bool:
    try:
        return bool((json.loads(m.meta_json) or {}).get("streaming")) if m.meta_json else False
    except Exception:  # noqa: BLE001
        return False


def _preliminary(m: TravelMessage) -> bool:
    """Phase 71：深度研究的「初步回答」——是先给用户垫场的，不是本轮终稿。"""
    try:
        return bool((json.loads(m.meta_json) or {}).get("preliminary")) if m.meta_json else False
    except Exception:  # noqa: BLE001
        return False


def _is_running(msgs: list[TravelMessage]) -> bool:
    """本轮（最后一条 user 之后）是否还在处理。

    判定「已完成」= 出现了一条**已终稿**（非流式）的 assistant 消息。
    反思循环会在攻略消息之后再插「正在自检」等 progress，所以不能只看最后一条
    （踩过坑：那样终稿后仍显示运行中直到超时）。
    未终稿则视为处理中，带 turn_stale_min 分钟兜底（后台任务被杀死时不锁死输入框）。"""
    if not msgs:
        return False
    last_user = max((i for i, m in enumerate(msgs) if m.role == "user"), default=-1)
    after = msgs[last_user + 1:]
    # 有流式 assistant 进行中（攻略生成中、或海报占位）→ 处理中
    if any(m.role == "assistant" and _streaming(m) for m in after):
        return True
    # 无流式，但已有终稿 assistant（攻略/海报/闲聊回复）→ 完成
    # （反思循环会在终稿后留下「补搜/重排」等 progress，不能因此判为运行中——踩过坑）
    # Phase 71：初步回答（meta.preliminary）不算终稿——它落在完整版之前，
    # 若按终稿处理会让前端立刻停止轮询，用户永远等不到完整分析（同 Phase 14 那个坑）。
    if any(m.role == "assistant" and not _streaming(m) and not _preliminary(m) for m in after):
        return False
    # 还没有任何回应（刚发消息、采集中）：处理中，带过期兜底
    ref = after[-1] if after else msgs[last_user] if last_user >= 0 else msgs[-1]
    ts = ref.created_at
    if ts is None:
        return True
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        now = now.replace(tzinfo=None)
    return (now - ts) < timedelta(minutes=settings.turn_stale_min)
