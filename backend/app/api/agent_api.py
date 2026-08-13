import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from app.agent.runner import run_task_sync
from app.api.deps import get_current_user
from app.db.models import TravelTask, TravelUser
from app.db.session import get_db

router = APIRouter(prefix="/api/agent", tags=["agent"])


class RunRequest(BaseModel):
    url: HttpUrl


class RunResponse(BaseModel):
    task_id: str
    status: str


@router.post("/run", response_model=RunResponse)
def run_agent(req: RunRequest, background: BackgroundTasks, db: Session = Depends(get_db),
              user: TravelUser = Depends(get_current_user)):
    """单页分析（Phase 1）。Phase 68：补上登录校验——此前无鉴权，
    任何人可驱动服务端浏览器访问任意 URL（SSRF）。"""
    task = TravelTask(status="pending", current_url=str(req.url), user_id=user.id)
    db.add(task)
    db.commit()
    background.add_task(run_task_sync, task.id, str(req.url), user.id)
    return RunResponse(task_id=task.id, status="pending")


@router.get("/tasks/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db),
             user: TravelUser = Depends(get_current_user)):
    task = db.get(TravelTask, task_id)
    # 非本人任务一律 404（不用 403，避免泄露 task 是否存在）
    if task is None or task.user_id != user.id:
        raise HTTPException(404, "task not found")
    return {
        "task_id": task.id,
        "status": task.status,
        "current_url": task.current_url,
        "handoff_reason": task.handoff_reason,
        "error": task.error,
        "result": json.loads(task.result) if task.result else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }
