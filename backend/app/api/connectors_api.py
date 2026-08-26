"""连接管理（Phase 109）：查看本系统连了哪些外部站点、各自能做什么、断开。

计划见 docs/task_plans/连接管理页-2026-08-26.md。

本期**不动 orchestrator**：只是把既有状态（`travel_site_login`）暴露出来，
外加一个真正有效的断开。连接仍走原来的路径（查酒店时命中登录墙 → 扫码卡片）。
"""

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import connect_session

from app.agent.connectors import disconnect as _disconnect
from app.agent.connectors import get_connector, list_status
from app.api.deps import get_current_user
from app.db.models import TravelSiteLogin, TravelUser
from app.db.session import get_db

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


def _logged_sites(db: Session, user_id: str) -> dict:
    rows = db.execute(
        select(TravelSiteLogin).where(TravelSiteLogin.user_id == user_id)
    ).scalars().all()
    return {r.site: r.logged_in_at for r in rows}


@router.get("")
def list_connectors(db: Session = Depends(get_db),
                    user: TravelUser = Depends(get_current_user)):
    """连接器清单 + 本用户的连接状态。按 user_id 隔离（同 Phase 15）。"""
    return {"connectors": list_status(_logged_sites(db, user.id))}


@router.delete("/{key}")
def disconnect_connector(key: str, db: Session = Depends(get_db),
                         user: TravelUser = Depends(get_current_user)):
    """断开某个连接器：清浏览器登录态 + 删登录记录。

    ⚠️ 会连带清掉该用户浏览器上的**其他**站点登录（cookie 在同一个 profile 目录里）。
    前端文案已如实说明——见 connectors.disconnect 的 docstring 里为什么不做精细版。
    """
    conn = get_connector(key)
    if conn is None:
        raise HTTPException(404, "connector not found")
    if not conn.connectable:
        # builtin 类（高德/小红书）是平台设施，用户既没连过也断不了
        raise HTTPException(400, f"{conn.name} 是平台内置连接器，无需也无法断开")
    _disconnect(db, user.id, key)
    return {"status": "ok", "key": key}


# ---------- 独立扫码连接（第二期） ----------

@router.post("/{key}/connect")
def start_connect(key: str, user: TravelUser = Depends(get_current_user)):
    """发起扫码连接。同一用户已有进行中的会话就返回它，不新建（防连点耗光池槽）。"""
    conn = get_connector(key)
    if conn is None:
        raise HTTPException(404, "connector not found")
    if not conn.connectable:
        raise HTTPException(400, f"{conn.name} 是平台内置连接器，无需连接")
    return connect_session.start(user.id, key).view()


@router.get("/connect/status")
def connect_status(user: TravelUser = Depends(get_current_user)):
    """当前连接会话状态。没有会话返回 state=idle（不是 404——前端轮询不该看错误码）。"""
    sess = connect_session.current(user.id)
    return sess.view() if sess is not None else {"state": "idle"}


@router.delete("/connect")
def cancel_connect(user: TravelUser = Depends(get_current_user)):
    return {"cancelled": connect_session.cancel(user.id)}


@router.get("/connect/{token}/screenshot")
def connect_screenshot(token: str):
    """登录页实时截图，供前端 <img> 轮询展示二维码。

    **故意不鉴权**：`<img>` 加载不能带 Authorization 头（同 Phase 5 的
    handoff-screenshot、Phase 74 的 uploads）。防护靠 token 是 uuid4 不可枚举，
    且会话一结束就删文件——窗口最长只有 connect_wait_s(90s)。
    刻意**不用 user_id 当 key**：那是长期标识，泄露一次就长期可探测；
    每次会话新生成的 token 用完即弃。
    """
    path = connect_session.screenshot_path(token)
    if not os.path.exists(path):
        raise HTTPException(404, "no active screenshot")
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})
