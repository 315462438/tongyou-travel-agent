"""启动期数据修复。

后台任务（BackgroundTasks）会被部署重启 / 进程崩溃杀死，此时会话的最后一条消息
停留在 user/progress，前端 running 永远为 true、输入框锁死。
服务启动时不可能有真正在跑的任务，所以把所有这种「悬挂会话」补一条中断说明。
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import TravelConversation, TravelMessage

logger = logging.getLogger(__name__)

INTERRUPTED_TEXT = "⚠️ 上一轮处理被服务重启中断了，内容没有生成完整，请把需求重新发一次。"


def repair_interrupted_conversations(db: Session, skip_cids: set[str] | None = None) -> int:
    """给所有悬挂会话补中断说明。返回修复条数。

    悬挂形态：最后一条是 user/progress/action（后台任务被杀死），
    或流式生成中的 assistant（meta.streaming 未终稿）。
    skip_cids：正在从 checkpoint 续跑的会话，交给续跑处理，别在这里误判修复。
    """
    skip_cids = skip_cids or set()
    convs = db.execute(select(TravelConversation)).scalars().all()
    repaired = 0
    for conv in convs:
        if conv.id in skip_cids:
            continue
        last = db.execute(
            select(TravelMessage)
            .where(TravelMessage.conversation_id == conv.id)
            .order_by(TravelMessage.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last is None:
            continue
        if last.role == "assistant":
            try:
                meta = json.loads(last.meta_json) if last.meta_json else {}
            except Exception:  # noqa: BLE001
                meta = {}
            if not meta.get("streaming"):
                continue
            # 被打断的流式消息：就地终稿（保留已生成内容 + 中断说明）
            last.content = (last.content + "\n\n" if last.content else "") + INTERRUPTED_TEXT
            last.meta_json = None
            repaired += 1
            continue
        db.add(TravelMessage(
            conversation_id=conv.id, role="assistant", content=INTERRUPTED_TEXT,
        ))
        repaired += 1
    if repaired:
        db.commit()
        logger.info("repaired %d interrupted conversations", repaired)
    return repaired


# ---------- Phase 16：从 checkpoint 续跑在途对话 ----------

def resume_inflight_turns() -> set[str]:
    """扫描在途登记，对每个近期的轮次在后台线程从 checkpoint 续跑。
    返回正在续跑的 cid 集合（供 repair 跳过）。过期/失败的清登记 + 交回 repair。"""
    import asyncio
    import threading
    from datetime import datetime, timedelta, timezone

    from app.db.models import TravelInflightTurn
    from app.db.session import get_session

    resuming: set[str] = set()
    with get_session() as db:
        rows = db.execute(select(TravelInflightTurn)).scalars().all()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        turns = [
            (r.cid, r.turn_id)
            for r in rows
            if r.started_at and (now - r.started_at) < timedelta(minutes=10)  # 太老的不续跑
        ]

    def _resume_one(cid: str, turn_id: str) -> None:
        from app.agent.cancel import clear_cancel
        from app.agent.graph import resume_turn
        from app.agent.orchestrator import _clear_inflight

        try:
            _delete_orphan_streaming(cid)  # 删上一轮未终稿流式消息，避免续跑重复
            ok = asyncio.run(resume_turn(turn_id))
            if not ok:
                _append_interrupted(cid)  # 无 checkpoint 可续 → 提示重发
        except Exception:  # noqa: BLE001
            logger.warning("resume turn %s failed", turn_id, exc_info=True)
            _append_interrupted(cid)
        finally:
            clear_cancel(cid)
            _clear_inflight(cid)

    for cid, turn_id in turns:
        resuming.add(cid)
        threading.Thread(target=_resume_one, args=(cid, turn_id), daemon=True).start()

    # 过期的在途登记直接清掉（交给 repair 提示重发）
    if rows:
        with get_session() as db:
            db.query(TravelInflightTurn).filter(
                ~TravelInflightTurn.cid.in_(resuming) if resuming else True
            ).delete(synchronize_session=False)
            db.commit()
    return resuming


def _delete_orphan_streaming(cid: str) -> None:
    from app.db.session import get_session

    with get_session() as db:
        msgs = db.execute(
            select(TravelMessage).where(
                TravelMessage.conversation_id == cid, TravelMessage.role == "assistant"
            )
        ).scalars().all()
        for m in msgs:
            try:
                if m.meta_json and (json.loads(m.meta_json) or {}).get("streaming"):
                    db.delete(m)
            except Exception:  # noqa: BLE001
                pass
        db.commit()


def _append_interrupted(cid: str) -> None:
    from app.db.session import get_session

    with get_session() as db:
        db.add(TravelMessage(conversation_id=cid, role="assistant", content=INTERRUPTED_TEXT))
        db.commit()
