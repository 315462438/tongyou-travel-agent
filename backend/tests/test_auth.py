"""登录/注册 + 数据隔离（Phase 15）单测。sqlite 内存库，直接调路由函数，全部离线。"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import auth_api
from app.api.chat_api import list_conversations
from app.api.deps import get_current_user, require_admin
from app.api.memory_api import list_memories
from app.auth import hash_password, verify_password
from app.db.models import Base, TravelConversation, TravelMemory, TravelUser


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# ---------- 密码 ----------

def test_password_hash_roundtrip():
    h = hash_password("hunter2")
    assert h.startswith("pbkdf2$") and h != "hunter2"
    assert verify_password("hunter2", h)
    assert not verify_password("wrong", h)


# ---------- 注册/登录 ----------

def test_register_then_login(db):
    out = auth_api.register(auth_api.AuthRequest(username="alice", password="secret1"), db)
    assert out["username"] == "alice" and out["token"] and out["is_admin"] is False
    # 用 token 能解析出用户
    user = get_current_user(f"Bearer {out['token']}", db)
    assert user.username == "alice"
    # 登录
    login = auth_api.login(auth_api.AuthRequest(username="alice", password="secret1"), db)
    assert login["token"]


def test_register_rejects_dupe_and_bad_input(db):
    auth_api.register(auth_api.AuthRequest(username="bob", password="secret1"), db)
    with pytest.raises(HTTPException):  # 重名
        auth_api.register(auth_api.AuthRequest(username="bob", password="secret1"), db)
    with pytest.raises(HTTPException):  # 短密码
        auth_api.register(auth_api.AuthRequest(username="carol", password="123"), db)


def test_login_wrong_password(db):
    auth_api.register(auth_api.AuthRequest(username="dan", password="secret1"), db)
    with pytest.raises(HTTPException):
        auth_api.login(auth_api.AuthRequest(username="dan", password="nope"), db)


def test_bad_token_rejected(db):
    with pytest.raises(HTTPException):
        get_current_user("Bearer nonexistent", db)
    with pytest.raises(HTTPException):
        get_current_user(None, db)


# ---------- 数据隔离 ----------

def test_conversations_and_memory_isolated(db):
    a = auth_api.register(auth_api.AuthRequest(username="ua", password="secret1"), db)
    b = auth_api.register(auth_api.AuthRequest(username="ub", password="secret1"), db)
    ua = get_current_user(f"Bearer {a['token']}", db)
    ub = get_current_user(f"Bearer {b['token']}", db)
    db.add_all([
        TravelConversation(id="ca", user_id=ua.id, title="A的行程"),
        TravelConversation(id="cb", user_id=ub.id, title="B的行程"),
        TravelMemory(user_id=ua.id, type="preference", content="A爱吃辣"),
        TravelMemory(user_id=ub.id, type="preference", content="B爱吃甜"),
    ])
    db.commit()

    assert [c["title"] for c in list_conversations(db, ua)] == ["A的行程"]
    assert [c["title"] for c in list_conversations(db, ub)] == ["B的行程"]
    assert [m["content"] for m in list_memories(db, ua)] == ["A爱吃辣"]
    assert [m["content"] for m in list_memories(db, ub)] == ["B爱吃甜"]


def test_conversation_title_dedup(db):
    """Phase 51 批6：同名会话从第 2 个起附日期区分。"""
    u = auth_api.register(auth_api.AuthRequest(username="uc", password="secret1"), db)
    user = get_current_user(f"Bearer {u['token']}", db)
    db.add_all([
        TravelConversation(id="c1", user_id=user.id, title="成都攻略"),
        TravelConversation(id="c2", user_id=user.id, title="成都攻略"),
        TravelConversation(id="c3", user_id=user.id, title="重庆攻略"),
    ])
    db.commit()
    titles = [c["title"] for c in list_conversations(db, user)]
    # 首个「成都攻略」保持原样，第二个带 · 日期后缀；重庆唯一不变
    assert titles.count("成都攻略") == 1
    assert any(t.startswith("成都攻略 · ") for t in titles)
    assert "重庆攻略" in titles


# ---------- Phase 51 批6：admin 默认口令强改 ----------

def test_must_change_password_flag(db):
    # admin 用默认口令 admin123 → must_change_password=True
    admin = TravelUser(id="ad", username="admin", is_admin=True,
                       password_hash=hash_password("admin123"))
    db.add(admin)
    db.commit()
    assert auth_api._must_change_password(admin) is True
    # 改成别的口令后 → False
    admin.password_hash = hash_password("newsecret")
    assert auth_api._must_change_password(admin) is False
    # 普通用户即便用 admin123 也不提示（非 admin）
    normal = TravelUser(id="n", username="n", is_admin=False,
                        password_hash=hash_password("admin123"))
    assert auth_api._must_change_password(normal) is False


def test_change_password(db):
    admin = TravelUser(id="ad", username="admin", is_admin=True,
                       password_hash=hash_password("admin123"))
    db.add(admin)
    db.commit()
    # 原密码错 → 400
    with pytest.raises(HTTPException):
        auth_api.change_password(
            auth_api.ChangePasswordRequest(old_password="wrong", new_password="brandnew"), db, admin)
    # 新密码太短 → 400
    with pytest.raises(HTTPException):
        auth_api.change_password(
            auth_api.ChangePasswordRequest(old_password="admin123", new_password="123"), db, admin)
    # admin 新密码不能仍是默认 → 400
    with pytest.raises(HTTPException):
        auth_api.change_password(
            auth_api.ChangePasswordRequest(old_password="admin123", new_password="admin123"), db, admin)
    # 正常改密 → 返回新 token 且不再要求改密
    out = auth_api.change_password(
        auth_api.ChangePasswordRequest(old_password="admin123", new_password="brandnew"), db, admin)
    assert out["token"] and out["must_change_password"] is False
    assert verify_password("brandnew", admin.password_hash)


# ---------- 管理员 ----------

def test_require_admin(db):
    normal = TravelUser(id="n", username="n", password_hash="x", is_admin=False)
    admin = TravelUser(id="ad", username="ad", password_hash="x", is_admin=True)
    with pytest.raises(HTTPException):
        require_admin(normal)
    assert require_admin(admin) is admin


def test_admin_list_users(db):
    admin = TravelUser(id="ad", username="admin", password_hash="x", is_admin=True)
    db.add(admin)
    db.add(TravelConversation(id="c1", user_id="ad", title="x"))
    db.add(TravelMemory(user_id="ad", type="preference", content="y"))
    db.commit()
    out = auth_api.list_users(admin, db)
    assert out["total"] == 1
    row = out["users"][0]
    assert row["username"] == "admin" and row["conversations"] == 1 and row["memories"] == 1


# ---------- Phase 70：邀请码注册 ----------

def test_register_blocked_without_invite_code(db, monkeypatch):
    monkeypatch.setattr(auth_api.settings, "register_invite_code", "SECRET2026")
    with pytest.raises(HTTPException) as e:
        auth_api.register(auth_api.AuthRequest(username="bob", password="secret1"), db)
    assert e.value.status_code == 403


def test_register_blocked_with_wrong_invite_code(db, monkeypatch):
    monkeypatch.setattr(auth_api.settings, "register_invite_code", "SECRET2026")
    with pytest.raises(HTTPException) as e:
        auth_api.register(
            auth_api.AuthRequest(username="bob", password="secret1", invite_code="nope"), db)
    assert e.value.status_code == 403


def test_register_ok_with_invite_code(db, monkeypatch):
    monkeypatch.setattr(auth_api.settings, "register_invite_code", "SECRET2026")
    out = auth_api.register(
        auth_api.AuthRequest(username="bob", password="secret1", invite_code=" SECRET2026 "), db)
    assert out["username"] == "bob" and out["token"]


def test_register_open_when_no_code_configured(db, monkeypatch):
    """留空 = 不校验（本地开发/存量行为不变）。"""
    monkeypatch.setattr(auth_api.settings, "register_invite_code", "")
    out = auth_api.register(auth_api.AuthRequest(username="carol", password="secret1"), db)
    assert out["token"]


def test_login_ignores_invite_code(db, monkeypatch):
    """邀请码只管注册，登录不受影响（老用户不会被锁在外面）。"""
    monkeypatch.setattr(auth_api.settings, "register_invite_code", "")
    auth_api.register(auth_api.AuthRequest(username="dave", password="secret1"), db)
    monkeypatch.setattr(auth_api.settings, "register_invite_code", "SECRET2026")
    out = auth_api.login(auth_api.AuthRequest(username="dave", password="secret1"), db)
    assert out["token"]
