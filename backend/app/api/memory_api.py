from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import TravelMemory, TravelUser
from app.db.session import get_db

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("")
def list_memories(db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    rows = db.execute(
        select(TravelMemory)
        .where(TravelMemory.user_id == user.id)
        .order_by(TravelMemory.updated_at.desc())
    ).scalars().all()
    return [
        {
            "id": m.id,
            "type": m.type,
            "key": m.key,
            "explicit": bool(m.explicit),
            "content": m.content,
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        }
        for m in rows
    ]


@router.post("/consolidate")
def consolidate(db: Session = Depends(get_db), user: TravelUser = Depends(get_current_user)):
    """整理当前用户记忆：去重合并成规范三元组（Phase 17）。"""
    from app.agent.memory import consolidate_memories
    from app.llm.client import get_llm

    result = consolidate_memories(db, user.id, get_llm())
    return {"status": "ok", **result}


@router.delete("/{mid}")
def delete_memory(mid: str, db: Session = Depends(get_db),
                  user: TravelUser = Depends(get_current_user)):
    row = db.get(TravelMemory, mid)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "memory not found")
    db.delete(row)
    db.commit()
    return {"status": "deleted"}
