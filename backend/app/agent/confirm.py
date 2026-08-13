"""对话内确认交互（Phase 7）

后台任务向对话流写「确认卡片」消息（meta.confirm），前端渲染按钮；
用户点击经 POST /api/chat/{cid}/confirm 落一条 role=action 的隐藏消息
（meta.confirm_reply）；后台轮询消息表拿决定，超时按默认值处理。

复用消息表做双向通道：无需 WebSocket，且决定有审计记录。
"""

import asyncio
import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import TravelMessage


def ask_confirm(cid: str, question: str, source: dict | None = None) -> str:
    """写确认卡片消息，返回 confirm_id。"""
    from app.db.session import get_session

    confirm_id = uuid.uuid4().hex
    meta = {"confirm": {"id": confirm_id, "question": question, "source": source or {}}}
    with get_session() as db:
        db.add(TravelMessage(
            conversation_id=cid, role="progress", content=question,
            meta_json=json.dumps(meta, ensure_ascii=False),
        ))
        db.commit()
    return confirm_id


def find_confirm_reply(db: Session, cid: str, confirm_id: str) -> str | None:
    """查用户对某次确认的回复（action 消息里的 choice），没有则 None。"""
    msgs = db.execute(
        select(TravelMessage)
        .where(TravelMessage.conversation_id == cid, TravelMessage.role == "action")
        .order_by(TravelMessage.created_at.desc())
        .limit(20)
    ).scalars().all()
    for m in msgs:
        if not m.meta_json:
            continue
        reply = (json.loads(m.meta_json) or {}).get("confirm_reply") or {}
        if reply.get("confirm_id") == confirm_id:
            return reply.get("choice")
    return None


async def wait_confirm(
    cid: str, confirm_id: str, *, timeout_s: float | None = None,
    poll_s: float = 2.0, default: str = "skip",
) -> str:
    """轮询等待用户点击确认卡片。超时返回 default。"""
    from app.db.session import get_session

    deadline = timeout_s if timeout_s is not None else settings.confirm_wait_s
    waited = 0.0
    while waited < deadline:
        await asyncio.sleep(poll_s)
        waited += poll_s
        with get_session() as db:
            choice = find_confirm_reply(db, cid, confirm_id)
        if choice:
            return choice
    return default
