"""surface 投影（Phase 91，借鉴 dsh 的 deriveMessages）单测。

核心不变式：**压缩不删除任何东西**。摘要是追加的一条 replace 消息，
被它折叠的原始消息全部留在表里，可完整回放。

sqlite 内存库，全离线。
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import Base, TravelConversation, TravelMessage


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(TravelConversation(id="c1", user_id="u1", title="测试"))
    session.commit()

    @contextmanager
    def fake_session():
        yield session

    import app.agent.orchestrator as orch

    monkeypatch.setattr(orch, "get_session", fake_session)
    return session


_T0 = datetime(2026, 8, 14, 10, 0, 0, tzinfo=timezone.utc)


def _add(db, role: str, content: str, n: int, **kw) -> TravelMessage:
    """按固定间隔落一条消息，保证 created_at 顺序确定（sqlite 下同秒会乱序）。"""
    m = TravelMessage(
        conversation_id="c1", role=role, content=content,
        created_at=_T0 + timedelta(minutes=n), **kw,
    )
    db.add(m)
    db.commit()
    return m


def _ids(rows) -> list[str]:
    return [r.content for r in rows]


# ---------- 基本投影 ----------

def test_append_only_messages_all_enter_surface(db):
    from app.agent.orchestrator import derive_surface

    _add(db, "user", "问1", 1)
    _add(db, "assistant", "答1", 2)
    assert _ids(derive_surface("c1")) == ["问1", "答1"]


def test_replace_shadows_the_declared_range(db):
    """摘要遮蔽它折叠掉的那段，自己顶上。"""
    from app.agent.orchestrator import derive_surface

    a = _add(db, "user", "问1", 1)
    _add(db, "assistant", "答1", 2)
    b = _add(db, "user", "问2", 3)
    _add(db, "assistant", "答2", 4)
    _add(db, "summary", "摘要：问1到问2", 5,
         surface_op="replace", shadow_from_id=a.id, shadow_to_id=b.id)

    assert _ids(derive_surface("c1")) == ["答2", "摘要：问1到问2"]


def test_shadowed_rows_are_still_in_the_table(db):
    """**核心不变式**：压缩不删除任何东西，被遮蔽的原文可完整回放。"""
    from app.agent.orchestrator import derive_surface

    a = _add(db, "user", "问1", 1)
    _add(db, "assistant", "答1", 2)
    _add(db, "summary", "摘要", 3,
         surface_op="replace", shadow_from_id=a.id, shadow_to_id=a.id)

    assert "问1" not in _ids(derive_surface("c1"))          # 不在 surface 上
    all_rows = db.execute(select(TravelMessage)).scalars().all()
    assert "问1" in [r.content for r in all_rows]           # 但原文还在


def test_later_messages_are_never_shadowed(db):
    """遮蔽只能向前。区间若跨到自己之后，后面的消息不能被吞掉。"""
    from app.agent.orchestrator import derive_surface

    a = _add(db, "user", "问1", 1)
    s = _add(db, "summary", "摘要", 2,
             surface_op="replace", shadow_from_id=a.id, shadow_to_id=a.id)
    _add(db, "user", "问2", 3)  # 在摘要之后
    assert s is not None
    assert "问2" in _ids(derive_surface("c1"))


def test_invalid_range_degrades_to_plain_append(db):
    """遮蔽目标已不存在（区间无效）时退化成普通追加，不能整个投影崩掉。"""
    from app.agent.orchestrator import derive_surface

    _add(db, "user", "问1", 1)
    _add(db, "summary", "摘要", 2,
         surface_op="replace", shadow_from_id="不存在", shadow_to_id="也不存在")
    assert _ids(derive_surface("c1")) == ["问1", "摘要"]


def test_successive_summaries_shadow_the_previous_one(db):
    """第二次压缩把上一条摘要也一并遮蔽——否则两条摘要会同时进上下文。"""
    from app.agent.orchestrator import derive_surface

    a = _add(db, "user", "问1", 1)
    s1 = _add(db, "summary", "摘要1", 2,
              surface_op="replace", shadow_from_id=a.id, shadow_to_id=a.id)
    b = _add(db, "user", "问2", 3)
    _add(db, "summary", "摘要2", 4,
         surface_op="replace", shadow_from_id=s1.id, shadow_to_id=b.id)

    assert _ids(derive_surface("c1")) == ["摘要2"]


# ---------- 与历史装配的对接 ----------

def test_full_history_projects_summary_as_user_role(db):
    """summary 消息以 user 角色进模型（当背景资料读），而不是一个模型不认识的角色。"""
    from app.agent.orchestrator import _full_history_messages

    a = _add(db, "user", "问1", 1)
    _add(db, "assistant", "答1", 2)
    _add(db, "summary", "早期摘要", 3,
         surface_op="replace", shadow_from_id=a.id, shadow_to_id=a.id)

    out = _full_history_messages("c1")
    assert {m["role"] for m in out} <= {"user", "assistant"}
    assert any(m["content"] == "早期摘要" for m in out)
    assert not any(m["content"] == "问1" for m in out)


def test_progress_and_action_never_enter_surface(db):
    """进度/隐藏动作不是对话事实，不进模型上下文。"""
    from app.agent.orchestrator import derive_surface

    _add(db, "user", "问1", 1)
    _add(db, "progress", "正在搜索…", 2)
    _add(db, "action", "确认回复", 3)
    assert _ids(derive_surface("c1")) == ["问1"]


# ---------- 压缩触发条件 ----------

def test_compaction_skips_short_conversations(db, monkeypatch):
    """轮次多但字数少 → 全文装得下，不该折叠（Phase 91 保真度回归的防线）。"""
    from app.agent import orchestrator as orch
    from app.config import settings

    monkeypatch.setattr(settings, "history_rounds", 1)
    monkeypatch.setattr(settings, "history_full_max_chars", 100000)
    for i in range(8):
        _add(db, "user" if i % 2 == 0 else "assistant", f"短消息{i}", i + 1)

    called = []
    monkeypatch.setattr(orch, "get_llm", lambda: called.append(1))
    orch.update_history_summary("c1")
    assert not called  # 连 LLM 都不该调
    assert db.query(TravelMessage).filter_by(role="summary").count() == 0


# ---------- summary 不能漏进对话流 ----------

def test_summary_rows_never_reach_the_chat_api(db, monkeypatch):
    """summary 是投影产物，不是对话气泡——漏出去会在对话里多一条奇怪的消息。"""
    from app.api import chat_api
    from app.api.chat_api import SendMessageRequest

    a = _add(db, "user", "问1", 1)
    _add(db, "assistant", "答1", 2)
    _add(db, "summary", "早期摘要", 3,
         surface_op="replace", shadow_from_id=a.id, shadow_to_id=a.id)

    class _U:
        id = "u1"

    monkeypatch.setattr(chat_api, "_owned", lambda *a, **k: None)
    out = chat_api.get_messages("c1", db=db, user=_U())
    roles = [m["role"] for m in out["messages"]]
    assert "summary" not in roles
    assert roles == ["user", "assistant"]  # 被遮蔽的原文仍在对话里，只是不进模型上下文


# ---------- 并发轮防护（Phase 92） ----------

def test_second_send_while_running_is_rejected(db, monkeypatch):
    """发送按钮连点两下不能起两个并发轮。

    没有这道门时：两条用户消息 + 两个 run_conversation_turn 同时写一个会话——
    各建流式占位、进度交错、记忆提炼跑两遍，停止按钮也说不清停的是哪一轮。
    """
    from fastapi import HTTPException

    from app.api import chat_api
    from app.api.chat_api import SendMessageRequest

    class _U:
        id = "u1"

    class _BG:
        def __init__(self): self.tasks = []
        def add_task(self, *a, **k): self.tasks.append(a)

    monkeypatch.setattr(chat_api, "_owned", lambda d, c, u: db.get(TravelConversation, "c1"))

    bg = _BG()
    req = SendMessageRequest(content="帮我规划三亚三天")
    out = chat_api.send_message("c1", req, bg, db=db, user=_U())
    assert out["status"] == "running" and len(bg.tasks) == 1

    # 第一轮还没有任何 assistant 回复 → _is_running 为真 → 第二次必须被挡
    with pytest.raises(HTTPException) as ei:
        chat_api.send_message("c1", req, bg, db=db, user=_U())
    assert ei.value.status_code == 409           # 状态冲突，前端据此静默忽略
    assert len(bg.tasks) == 1                    # 没有起第二个后台任务
    assert db.query(TravelMessage).filter_by(role="user").count() == 1  # 也没落第二条消息


def test_send_allowed_again_after_the_turn_finishes(db, monkeypatch):
    """终稿之后必须能继续发，否则输入框就锁死了。"""
    from app.api import chat_api
    from app.api.chat_api import SendMessageRequest

    class _U:
        id = "u1"

    class _BG:
        def __init__(self): self.tasks = []
        def add_task(self, *a, **k): self.tasks.append(a)

    monkeypatch.setattr(chat_api, "_owned", lambda d, c, u: db.get(TravelConversation, "c1"))

    bg = _BG()
    chat_api.send_message("c1", SendMessageRequest(content="问1"), bg, db=db, user=_U())
    _add(db, "assistant", "答1", 50)  # 终稿（非流式）
    chat_api.send_message("c1", SendMessageRequest(content="问2"), bg, db=db, user=_U())
    assert len(bg.tasks) == 2
