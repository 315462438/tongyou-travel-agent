import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.orchestrator import run_conversation_turn
from app.agent.site_router import handoff_screenshot_path
from app.api.deps import get_current_user
from app.config import settings
from app.db.models import TravelConversation, TravelMessage, TravelUser
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


class ConfirmRequest(BaseModel):
    confirm_id: str
    choice: str  # login / skip


def _msg_dict(m: TravelMessage) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "reasoning": m.reasoning,
        "meta": json.loads(m.meta_json) if m.meta_json else None,
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


@router.post("/{cid}/messages")
def send_message(
    cid: str, req: SendMessageRequest, background: BackgroundTasks,
    db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user),
):
    conv = _owned(db, cid, user)
    user_msg = TravelMessage(conversation_id=cid, role="user", content=req.content)
    db.add(user_msg)
    # 首条用户消息作为会话标题
    if conv.title == "新对话":
        conv.title = req.content[:30]
    db.commit()
    # turn_id = 用户消息 id，作为 checkpoint thread_id（每轮唯一，天然 fresh）
    background.add_task(
        run_conversation_turn, cid, req.content, user.id, user_msg.id,
        req.deep_reasoning, req.sandbox_enabled,
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


@router.get("/{cid}/messages")
def get_messages(cid: str, db: Session = Depends(get_db),
                 user: TravelUser = Depends(get_current_user)):
    _owned(db, cid, user)
    msgs = db.execute(
        select(TravelMessage)
        .where(TravelMessage.conversation_id == cid)
        .order_by(TravelMessage.created_at)
    ).scalars().all()
    return {"messages": [_msg_dict(m) for m in msgs], "running": _is_running(msgs)}


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
