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

        # 2026-08-14：先扫**所有**未终稿的流式消息，而不是只看最后一条。
        # 线上真实卡死：重复提交起了两个并发轮，一个正常出稿、另一个留下流式占位，
        # 之后又落了 progress 和报错消息 —— 最后一条不是流式的，旧实现直接 continue，
        # 那条占位就永远挂着，`_is_running` 一直判运行中，输入框和停止按钮全锁死。
        for m in db.execute(
            select(TravelMessage)
            .where(TravelMessage.conversation_id == conv.id, TravelMessage.role == "assistant")
            .order_by(TravelMessage.created_at)
        ).scalars():
            try:
                meta = json.loads(m.meta_json) if m.meta_json else {}
            except Exception:  # noqa: BLE001
                meta = {}
            if not meta.get("streaming"):
                continue
            m.content = (m.content + "\n\n" if m.content else "") + INTERRUPTED_TEXT
            m.meta_json = None
            repaired += 1

        if last.role == "assistant":
            continue  # 已终稿或刚被上面修好，不再追加中断说明
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
            (r.cid, r.turn_id, r.started_at)
            for r in rows
            if r.started_at and (now - r.started_at) < timedelta(minutes=10)  # 太老的不续跑
        ]

    def _resume_one(cid: str, turn_id: str, started_at) -> None:
        from app.agent.cancel import clear_cancel
        from app.agent.graph import resume_turn
        from app.agent.orchestrator import _clear_inflight

        def _cleanup() -> None:
            clear_cancel(cid)
            _clear_inflight(cid)

        # 2026-08-14 线上：16:18 部署重启 → 续跑旧轮，用户 16:21 已重发新轮次 →
        # 续跑失败时把「被服务重启中断」提示插进正在运行的新轮次中间，造成「老是被中断」。
        # 用户 turn 之后已发新 user 消息 = 已重发 → 放弃续跑、只清残留占位与登记，不写提示。
        if _user_sent_after(cid, started_at):
            logger.info("resume skipped for %s: user already re-sent after %s", cid, started_at)
            try:
                _delete_orphan_streaming(cid)  # 清旧轮未终稿流式占位，防 running 锁死
            except Exception:  # noqa: BLE001
                logger.warning("delete orphan streaming failed cid=%s", cid, exc_info=True)
            _cleanup()
            return

        try:
            _delete_orphan_streaming(cid)  # 删上一轮未终稿流式消息，避免续跑重复
            # 2026-08-14：续跑限时 60s——checkpoint 在 collect 中途的 guide 轮续跑要重新采集
            # （分钟级），与用户重发/新请求抢浏览器与 LLM；超时放弃，交还用户决定。
            ok = asyncio.run(asyncio.wait_for(resume_turn(turn_id), timeout=60))
            if not ok:
                _append_interrupted(cid)  # 无 checkpoint 可续 → 提示重发
        except asyncio.TimeoutError:
            logger.warning("resume turn %s timed out after 60s", turn_id)
            _maybe_interrupted(cid, started_at)
        except Exception:  # noqa: BLE001
            logger.warning("resume turn %s failed", turn_id, exc_info=True)
            _maybe_interrupted(cid, started_at)
        finally:
            _cleanup()


def _maybe_interrupted(cid: str, started_at) -> None:
    """续跑失败后的提示：用户已重发新轮次就不写，避免提示插进新轮次中间。"""
    if _user_sent_after(cid, started_at):
        logger.info("interrupted note skipped for %s: user already re-sent", cid)
        return
    _append_interrupted(cid)


def _user_sent_after(cid: str, after) -> bool:
    """会话里是否有晚于 `after` 的 user 消息（用户已重发新轮次）。纯查询，供续跑判定。"""
    from app.db.models import TravelMessage as _M
    from app.db.session import get_session

    if after is None:
        return False
    # 列无时区：aware 要剥掉 tzinfo 再与 naive 比较（与 resume_inflight_turns 的 now 一致）
    after_naive = after.replace(tzinfo=None) if after.tzinfo else after
    with get_session() as db:
        row = db.execute(
            select(_M.id)
            .where(_M.conversation_id == cid, _M.role == "user", _M.created_at > after_naive)
            .limit(1)
        ).scalar_one_or_none()
        return row is not None

    for cid, turn_id, started_at in turns:
        resuming.add(cid)
        threading.Thread(target=_resume_one, args=(cid, turn_id, started_at), daemon=True).start()

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
