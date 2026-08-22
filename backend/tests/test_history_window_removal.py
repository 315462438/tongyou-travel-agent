"""移除历史装配滑动窗口（2026-08-22）回归测试。

核心不变式：**模型可见的历史边界只由日志里的 replace 事件决定。**
`_assemble_history` 不再自己截取近 N 轮——那个窗口砍掉的消息没有摘要覆盖、
无记录、且边界每轮都会移动（毁前缀缓存）。

计划见 docs/task_plans/移除历史滑动窗口-2026-08-22.md，sqlite 内存库，全离线。
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Base, TravelConversation, TravelMessage

_T0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=timezone.utc)  # 必须早于 now()——replace 行用 DB 默认时间，排在最后才遮蔽得到前面的消息


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


def _add(db, role: str, content: str, n: int, **kw) -> TravelMessage:
    m = TravelMessage(
        conversation_id="c1", role=role, content=content,
        created_at=_T0 + timedelta(minutes=n), **kw,
    )
    db.add(m)
    db.commit()
    return m


def _seed_rounds(db, count: int, chars: int = 100, start: int = 1) -> list[TravelMessage]:
    """落 count 轮问答，每条 assistant 正文 chars 字。"""
    out = []
    for i in range(count):
        out.append(_add(db, "user", f"问{start + i}", (start + i) * 2))
        out.append(_add(db, "assistant", f"答{start + i}" + "内容" * (chars // 2), (start + i) * 2 + 1))
    return out


def _replace_count(db) -> int:
    return len([
        m for m in db.execute(select(TravelMessage)).scalars().all()
        if m.surface_op == "replace"
    ])


def _history_chars_of(msgs) -> int:
    return sum(len(m["content"]) for m in msgs)


def _working_llm(monkeypatch):
    """能正常产出摘要的假 LLM。"""

    class _FakeLLM:
        def classify(self, listing, model, system=""):
            return model(summary="## 用户约束\n早期都在聊哈尔滨")

    monkeypatch.setattr("app.llm.client.get_llm", lambda: _FakeLLM())


def _no_fold(monkeypatch):
    """让轮末折叠成为 no-op（模拟旁路失败 / 只想看装配行为）。"""
    import app.agent.orchestrator as orch

    calls = []
    monkeypatch.setattr(orch, "update_history_summary", lambda cid: calls.append(cid))
    return calls


# ---------- 1. 未超限：全量逐字（原行为不变） ----------

def test_under_limit_returns_full_surface(db, monkeypatch):
    from app.agent.orchestrator import _assemble_history

    _seed_rounds(db, 8)  # 16 条，远超 history_rounds*2=10
    monkeypatch.setattr(settings, "history_full_max_chars", 10**6)

    msgs, summary = _assemble_history("c1")
    assert len(msgs) == 16, "未超限就必须全量逐字——不再按 history_rounds 截窗"
    assert summary == ""


def test_history_rounds_no_longer_affects_assembly(db, monkeypatch):
    """改 history_rounds 不再追溯性移动装配边界（Phase 89 docstring 点名的那个问题）。"""
    from app.agent.orchestrator import _assemble_history

    _seed_rounds(db, 8)
    monkeypatch.setattr(settings, "history_full_max_chars", 10**6)

    monkeypatch.setattr(settings, "history_rounds", 1)
    few, _ = _assemble_history("c1")
    monkeypatch.setattr(settings, "history_rounds", 20)
    many, _ = _assemble_history("c1")
    assert few == many


# ---------- 2. 核心性质：无 replace 写入时，边界不移动 ----------

def test_boundary_moves_only_when_a_replace_event_is_written(db, monkeypatch):
    """核心不变式：历史边界**只**由日志里的 replace 事件推动。

    没有新 replace 的那一轮，上一轮的历史必须是这一轮的**逐条前缀**——这正是前缀缓存
    能命中的条件，也是滑动窗口破坏掉的性质（它在超限后每轮左移一格、且不留任何记录）。
    """
    from app.agent.orchestrator import _assemble_history

    _working_llm(monkeypatch)
    _seed_rounds(db, 10)  # 20 条，约 1040 字
    monkeypatch.setattr(settings, "history_full_max_chars", 500)
    monkeypatch.setattr(settings, "history_rounds", 5)

    first, _ = _assemble_history("c1")          # 超限 → 折叠一次，写 1 条 replace
    assert _replace_count(db) == 1

    _seed_rounds(db, 1, start=11)               # 新一轮：折叠后已在预算内，不该再折
    second, _ = _assemble_history("c1")

    assert _replace_count(db) == 1, "没超限就不该再产生 replace 事件"
    assert second[: len(first)] == first, "无 replace 却移动了边界——历史不再是 append-only"


def test_fold_shrinks_keep_when_recent_window_itself_too_big(db, monkeypatch):
    """近窗自己就超字数时，折叠必须收窄 keep 把预算压下来。

    否则 `update_history_summary` 永远在 `len(live) <= keep` 处早退，装配端只能靠
    紧急降级丢消息——那就是被删掉的滑动窗口原样回来了。
    """
    from app.agent.orchestrator import _assemble_history, update_history_summary

    _working_llm(monkeypatch)
    _seed_rounds(db, 6, chars=400)              # 6 轮，每条 assistant ~402 字
    monkeypatch.setattr(settings, "history_rounds", 5)   # keep=10 ≥ live=12？不，live=12>10
    monkeypatch.setattr(settings, "history_full_max_chars", 600)

    update_history_summary("c1")
    msgs, summary = _assemble_history("c1")
    assert summary, "应当折叠出了摘要"
    assert _history_chars_of(msgs) <= 600, "折叠后必须真的落进预算内"


# ---------- 3. 超限：就地折叠一次，而不是静默砍 ----------

def test_over_limit_triggers_inline_fold(db, monkeypatch):
    from app.agent.orchestrator import _assemble_history

    calls = _no_fold(monkeypatch)
    _seed_rounds(db, 10)
    monkeypatch.setattr(settings, "history_full_max_chars", 500)

    _assemble_history("c1")
    assert calls == ["c1"], "超限必须先补一次折叠（写 replace 事件），不能直接砍"


def test_inline_fold_shrinks_history_and_leaves_replace_event(db, monkeypatch):
    """折叠真的发生时：历史变短、日志里多一条 replace、原文一条不少。"""
    import app.agent.orchestrator as orch
    from app.agent.orchestrator import _assemble_history

    _seed_rounds(db, 10)
    monkeypatch.setattr(settings, "history_full_max_chars", 500)
    monkeypatch.setattr(settings, "history_rounds", 2)

    class _FakeLLM:
        def classify(self, listing, model, system=""):
            return model(summary="## 用户约束\n早期都在聊哈尔滨")

    monkeypatch.setattr("app.llm.client.get_llm", lambda: _FakeLLM())

    before_rows = db.execute(select(TravelMessage)).scalars().all()
    msgs, summary = _assemble_history("c1")

    after_rows = db.execute(select(TravelMessage)).scalars().all()
    assert len(after_rows) == len(before_rows) + 1, "折叠只追加一条 replace，不删原文"
    replace = [m for m in after_rows if m.surface_op == "replace"]
    assert len(replace) == 1 and replace[0].role == "summary"
    assert "哈尔滨" in summary
    assert len(msgs) < 20, "折叠后模型可见的历史应当变短"


def test_fold_failure_does_not_break_turn(db, monkeypatch):
    """折叠抛异常也不能让本轮挂掉（旁路是增强，不是前置条件）。"""
    import app.agent.orchestrator as orch
    from app.agent.orchestrator import _assemble_history

    def boom(cid):
        raise RuntimeError("deepseek 429")

    monkeypatch.setattr(orch, "update_history_summary", boom)
    _seed_rounds(db, 10)
    monkeypatch.setattr(settings, "history_full_max_chars", 500)

    msgs, _ = _assemble_history("c1")
    assert msgs, "折叠失败仍要返回可用的历史"


# ---------- 4. 紧急降级：可以丢，但必须有记录 ----------

def test_emergency_drop_is_logged_not_silent(db, monkeypatch, caplog):
    """折叠没能压下来时才丢最早的消息，且必打 error——改造前是完全静默的。"""
    from app.agent.orchestrator import _assemble_history

    _no_fold(monkeypatch)  # 折叠 no-op → 必然仍超限
    _seed_rounds(db, 10)
    monkeypatch.setattr(settings, "history_full_max_chars", 500)

    with caplog.at_level("ERROR"):
        msgs, _ = _assemble_history("c1")

    assert len(msgs) < 20
    assert any("still over limit" in r.message for r in caplog.records), \
        "丢消息必须留痕，否则又变回那个偶发、自愈、无日志的静默 bug"


def test_emergency_drop_keeps_at_least_one_message(db, monkeypatch):
    """单条消息就超限时也不能返回空历史（否则模型连本轮上文都没有）。"""
    from app.agent.orchestrator import _assemble_history

    _no_fold(monkeypatch)
    _add(db, "user", "问", 1)
    _add(db, "assistant", "答" * 5000, 2)
    monkeypatch.setattr(settings, "history_full_max_chars", 10)

    msgs, _ = _assemble_history("c1")
    assert len(msgs) == 1 and msgs[0]["role"] == "assistant"


# ---------- 5. 存量兼容 ----------

def test_legacy_conversation_summary_still_read(db, monkeypatch):
    """老会话日志里没有 summary 消息，摘要写在 conversation.history_summary 上。"""
    from app.agent.orchestrator import _assemble_history

    _no_fold(monkeypatch)
    conv = db.get(TravelConversation, "c1")
    conv.history_summary = "## 用户约束\n预算3000"
    db.commit()
    _seed_rounds(db, 10)
    monkeypatch.setattr(settings, "history_full_max_chars", 500)

    _, summary = _assemble_history("c1")
    assert "预算3000" in summary


def test_legacy_summary_not_injected_when_under_limit(db, monkeypatch):
    """没超限就没有遮蔽，注入存量摘要只会与全文重复。"""
    from app.agent.orchestrator import _assemble_history

    conv = db.get(TravelConversation, "c1")
    conv.history_summary = "## 用户约束\n预算3000"
    db.commit()
    _seed_rounds(db, 2)
    monkeypatch.setattr(settings, "history_full_max_chars", 10**6)

    _, summary = _assemble_history("c1")
    assert summary == ""


# ---------- 6. 去重仍然生效 ----------

def test_current_user_message_deduped(db, monkeypatch):
    from app.agent.orchestrator import _assemble_history

    monkeypatch.setattr(settings, "history_full_max_chars", 10**6)
    _add(db, "user", "问1", 1)
    _add(db, "assistant", "答1", 2)
    _add(db, "user", "解释一下", 3)  # 本轮，已落库

    msgs, _ = _assemble_history("c1", current_user_text="解释一下")
    assert [m["content"] for m in msgs] == ["问1", "答1"]
