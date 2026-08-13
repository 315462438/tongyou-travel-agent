"""Phase 68：/api/agent 路由鉴权与归属校验。

背景：这两条 Phase 1 遗留路由此前**完全没有鉴权**，公网任何人可驱动服务端浏览器
访问任意 URL（SSRF）。这里锁死回归。sqlite 内存库，直接调路由函数，全部离线。
"""

import ast
import glob
import os

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import agent_api
from app.db.models import Base, TravelTask, TravelUser


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _user(db, name="alice"):
    u = TravelUser(username=name, password_hash="x")
    db.add(u)
    db.commit()
    return u


class _BG:
    """假的 BackgroundTasks：只记录，不真跑浏览器。"""

    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **kw):
        self.calls.append((fn, a, kw))


# ---------- 归属 ----------

def test_run_records_owner(db):
    u = _user(db)
    bg = _BG()
    out = agent_api.run_agent(agent_api.RunRequest(url="https://example.com"), bg, db, u)
    task = db.get(TravelTask, out.task_id)
    assert task.user_id == u.id
    assert len(bg.calls) == 1  # 后台任务已排队


def test_owner_can_read_own_task(db):
    u = _user(db)
    bg = _BG()
    out = agent_api.run_agent(agent_api.RunRequest(url="https://example.com"), bg, db, u)
    got = agent_api.get_task(out.task_id, db, u)
    assert got["task_id"] == out.task_id


def test_other_user_cannot_read_task(db):
    owner = _user(db, "alice")
    other = _user(db, "bob")
    bg = _BG()
    out = agent_api.run_agent(agent_api.RunRequest(url="https://example.com"), bg, db, owner)
    with pytest.raises(HTTPException) as e:
        agent_api.get_task(out.task_id, db, other)
    # 404 而非 403：不泄露 task 是否存在
    assert e.value.status_code == 404


def test_missing_task_is_404(db):
    u = _user(db)
    with pytest.raises(HTTPException) as e:
        agent_api.get_task("nope", db, u)
    assert e.value.status_code == 404


def test_orphan_task_not_readable(db):
    """迁移前的历史任务 user_id 为空——不能被任意登录用户读到。"""
    u = _user(db)
    t = TravelTask(status="done", current_url="https://x.com", user_id=None)
    db.add(t)
    db.commit()
    with pytest.raises(HTTPException) as e:
        agent_api.get_task(t.id, db, u)
    assert e.value.status_code == 404


# ---------- 全局：路由不得漏鉴权 ----------

# 有意公开的端点（改动需在此显式登记，评审时能看见）
PUBLIC_ROUTES = {
    ("auth_api", "register"),      # 注册必须公开
    ("auth_api", "login"),         # 登录必须公开
    ("chat_api", "handoff_screenshot"),   # <img> 不能带 header，cid 不可猜
    ("img_api", "proxy_image"),           # 同上，已有 SSRF 白名单
    ("staticmap_api", "staticmap"),       # 同上，key 不进前端
    ("sandbox_artifacts_api", "download_artifact"),  # 段校验 + abspath 双重保险
    ("trip_api", "shared_preview"),       # 分享链接设计即公开，token 不可猜
    ("trip_api", "short_link"),           # 分享短链
    ("upload_api", "fetch_image"),        # <img> 不能带 header，id 是 uuid4 不可枚举
}


def _route_handlers():
    root = os.path.join(os.path.dirname(__file__), "..", "app", "api")
    for path in sorted(glob.glob(os.path.join(root, "*_api.py"))):
        mod = os.path.basename(path)[:-3]
        src = open(path, encoding="utf-8").read()
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # 2026-08-04 修：原判据是「装饰器挂在名为 `router` 的变量上」，于是
            # `support_router` / `admin_manage_router` 这类命名的路由**整个被跳过**，
            # 扫描给出的是虚假的安全感。改为凡是 *router 结尾的变量都算路由。
            is_route = any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and isinstance(d.func.value, ast.Name)
                and d.func.value.id.endswith("router")
                for d in node.decorator_list
            )
            if not is_route:
                continue
            # require_admin 内部就是 Depends(get_current_user)，同样算已鉴权
            guarded = any(
                isinstance(sub, ast.Name) and sub.id in ("get_current_user", "require_admin")
                for dflt in list(node.args.defaults) + list(node.args.kw_defaults)
                if dflt is not None
                for sub in ast.walk(dflt)
            )
            yield mod, node.name, guarded


def test_no_unguarded_routes():
    """任何新增路由默认必须带 get_current_user；有意公开的要登记到 PUBLIC_ROUTES。"""
    unguarded = {
        (mod, name) for mod, name, guarded in _route_handlers() if not guarded
    }
    leaked = unguarded - PUBLIC_ROUTES
    assert not leaked, f"以下路由缺少鉴权（如确需公开请登记到 PUBLIC_ROUTES）：{sorted(leaked)}"


def test_public_route_registry_has_no_stale_entries():
    """PUBLIC_ROUTES 里不该留已经加了鉴权/已删除的条目，避免登记表变成摆设。"""
    unguarded = {(mod, name) for mod, name, guarded in _route_handlers() if not guarded}
    stale = PUBLIC_ROUTES - unguarded
    assert not stale, f"PUBLIC_ROUTES 有过期条目：{sorted(stale)}"
