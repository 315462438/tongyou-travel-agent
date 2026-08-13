"""停止/取消（Phase 16）单测。"""

import pytest

from app.agent.cancel import TurnCancelled, check, clear_cancel, is_cancelled, request_cancel


def test_cancel_lifecycle():
    cid = "c-cancel"
    assert not is_cancelled(cid)
    request_cancel(cid)
    assert is_cancelled(cid)
    with pytest.raises(TurnCancelled):
        check(cid)
    clear_cancel(cid)
    assert not is_cancelled(cid)
    check(cid)  # 清除后不再抛


def test_cancel_isolated_per_cid():
    request_cancel("a")
    assert is_cancelled("a") and not is_cancelled("b")
    clear_cancel("a")


def test_history_rounds_limit(monkeypatch):
    """近 N 轮 = limit N*2；改 history_rounds 生效。"""
    from app.agent import orchestrator as orch
    from app.config import settings

    captured = {}

    class FakeExec:
        def scalars(self):
            class S:
                def all(self_inner):
                    return []
            return S()

    class FakeDB:
        def execute(self, stmt):
            captured["limit"] = stmt._limit  # SQLAlchemy Select._limit
            return FakeExec()

        def get(self, model, pk):  # Phase 30：_history_text 还会取会话行拼历史摘要
            return None

    class Ctx:
        def __enter__(self):
            return FakeDB()

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(orch, "get_session", lambda: Ctx())
    monkeypatch.setattr(settings, "history_rounds", 5)
    orch._history_text("c1")
    assert captured["limit"] == 10  # 5 轮 × 2
    orch._history_text("c1", rounds=3)
    assert captured["limit"] == 6
