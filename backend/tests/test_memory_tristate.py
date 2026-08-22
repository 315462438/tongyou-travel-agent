"""记忆变更三态通知（2026-08-22，移植自 Codex `PreviousSectionState`）。

## 为什么需要它

我们的上下文是**投影**：记忆每轮从库里现算，历史里不存在陈旧副本——所以 Codex
那套「重复注入 + REPLACEMENT_NOTICE」我们大半用不上。但有一格是需要的：
**对话历史本身承载旧状态**。用户第 3 轮被推荐一堆素食馆（当时记忆有「忌口=素食」），
第 8 轮说「不忌口了」→ 记忆删除。第 8 轮历史里那些素食推荐逐字还在，而记忆块里那条
没了——模型没有任何信号知道约束解除。对应 Codex `agents_md.rs` 的
`(None, previous_may_contain_instructions=true)` 那一格。

sqlite 内存库，全离线。
"""

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, TravelMemory, TravelMessage

_T0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr("app.db.session.get_session", fake_session)
    return session


def _mem(key: str, content: str) -> TravelMemory:
    return TravelMemory(user_id="u1", type="preference", key=key, content=content)


def _reply(db, n: int, used=None, **meta):
    payload = {**({"memories_used": used} if used is not None else {}), **meta}
    m = TravelMessage(
        conversation_id="c1", role="assistant", content="攻略正文",
        created_at=_T0 + timedelta(minutes=n),
        meta_json=json.dumps(payload, ensure_ascii=False) if payload else None,
    )
    db.add(m)
    db.commit()
    return m


# ---------- 三态判定 ----------

def test_absent_when_no_prior_reply(db):
    """Absent：本会话还没有过终稿回复 → 历史里没有与记忆冲突的表述。"""
    from app.agent.memory import previous_injected_memories

    assert previous_injected_memories("c1") is None


def test_known_when_prior_reply_recorded_keys(db):
    from app.agent.memory import previous_injected_memories

    _reply(db, 1, used=[{"kind": "memory", "key": "忌口", "content": "吃素"}])
    assert previous_injected_memories("c1") == {"忌口": "吃素"}


def test_unknown_when_prior_reply_has_no_record(db):
    """Unknown：有过回复但没记下注入了什么（改造前的老消息）。"""
    from app.agent.memory import _UNKNOWN, previous_injected_memories

    _reply(db, 1)  # meta 里没有 memories_used
    assert previous_injected_memories("c1") is _UNKNOWN


def test_unknown_when_old_format_lacks_key(db):
    """老格式的 memories_used 不带 key，比不出差异 → Unknown 而非"什么都没注入"。"""
    from app.agent.memory import _UNKNOWN, previous_injected_memories

    _reply(db, 1, used=[{"kind": "memory", "type": "preference", "content": "吃素"}])
    assert previous_injected_memories("c1") is _UNKNOWN


def test_poster_and_budget_messages_are_skipped(db):
    """海报/预算面板不是一次「读记忆并作答」的回合，不能被当成上一轮。"""
    from app.agent.memory import previous_injected_memories

    _reply(db, 1, used=[{"kind": "memory", "key": "忌口", "content": "吃素"}])
    _reply(db, 2, poster={"title": "x"})
    _reply(db, 3, budget={"total": 1})
    _reply(db, 4, streaming=True)
    assert previous_injected_memories("c1") == {"忌口": "吃素"}


def test_empty_memories_used_is_known_not_unknown(db):
    """上一轮确实一条记忆都没注入 → Known(空)，不该退化成 Unknown。"""
    from app.agent.memory import previous_injected_memories

    _reply(db, 1, used=[{"kind": "past_chat", "title": "t", "content": "c"}])
    assert previous_injected_memories("c1") == {}


# ---------- 变更渲染 ----------

def test_absent_emits_nothing():
    from app.agent.memory import format_memory_changes

    assert format_memory_changes(None, [_mem("忌口", "吃素")], {"忌口"}) == ""


def test_addition_emits_nothing():
    """新增不与历史里任何表述矛盾，说了是噪声（同 Codex 不加 REPLACEMENT_NOTICE 那格）。"""
    from app.agent.memory import format_memory_changes

    out = format_memory_changes({}, [_mem("忌口", "吃素")], {"忌口"})
    assert out == ""


def test_update_is_announced():
    from app.agent.memory import format_memory_changes

    out = format_memory_changes({"忌口": "吃素"}, [_mem("忌口", "不忌口")], {"忌口"})
    assert "忌口" in out and "不忌口" in out and "已更新" in out


def test_removal_is_announced():
    """最要紧的一格：删除必须显式说，否则模型只看得到自己早前基于旧偏好写的推荐。"""
    from app.agent.memory import format_memory_changes

    out = format_memory_changes({"忌口": "吃素"}, [], set())
    assert "忌口" in out and "不再适用" in out


def test_filtered_out_memory_is_not_reported_as_removed():
    """本轮没被 select_relevant_memories 选中 ≠ 用户撤回了偏好。

    这是最容易写错、且错了会**主动误导模型**的一格：报成删除会让模型以为用户
    推翻了自己说过的话。判据是「库里还有没有」，不是「这轮注没注入」。
    """
    from app.agent.memory import format_memory_changes

    out = format_memory_changes({"忌口": "吃素"}, [], all_keys={"忌口"})
    assert out == ""


def test_unknown_emits_blanket_authority_notice():
    """Unknown 往「通知」这边倒——代价不对称：多说一句只是几十 token，
    漏说则模型继续按历史里那条已被推翻的约束作答。"""
    from app.agent.memory import _UNKNOWN, format_memory_changes

    out = format_memory_changes(_UNKNOWN, [_mem("忌口", "不忌口")], {"忌口"})
    assert out and "以此为准" not in out or "为准" in out
    assert "当前有效" in out


def test_no_change_emits_nothing():
    from app.agent.memory import format_memory_changes

    out = format_memory_changes({"忌口": "吃素"}, [_mem("忌口", "吃素")], {"忌口"})
    assert out == ""


def test_update_and_removal_together():
    from app.agent.memory import format_memory_changes

    out = format_memory_changes(
        {"忌口": "吃素", "预算": "3000"},
        [_mem("忌口", "不忌口")],
        all_keys={"忌口"},
    )
    assert "已更新" in out and "不再适用" in out


# ---------- 「恰好通知一次」 ----------

def test_notice_fires_exactly_once_after_a_change():
    """变更通知只在变更后的**那一轮**出现，下一轮自动消失。

    它是投影产物（拼在本轮 <background_memory> 里，不落库），而下一轮的 previous
    已经是新值 → diff 为空。写错成「持续提醒」的话，模型会在之后每一轮都被同一条
    「已更新」骚扰，还可能反复道歉修正。
    """
    from app.agent.memory import format_memory_changes

    now = [_mem("忌口", "不忌口")]
    turn_n = format_memory_changes({"忌口": "吃素"}, now, {"忌口"})
    assert "已更新" in turn_n

    # 第 N 轮的 memories_used 记下的就是新值 → 第 N+1 轮的 previous
    turn_n1 = format_memory_changes({"忌口": "不忌口"}, now, {"忌口"})
    assert turn_n1 == ""


def test_removal_notice_fires_exactly_once():
    from app.agent.memory import format_memory_changes

    assert "不再适用" in format_memory_changes({"忌口": "吃素"}, [], set())
    assert format_memory_changes({}, [], set()) == ""  # 下一轮 previous 里已经没有它


def test_unknown_notice_fires_exactly_once():
    """老会话第一轮发整体重申；那一轮的 memories_used 带上 key 后转入 Known，不再重申。"""
    from app.agent.memory import _UNKNOWN, format_memory_changes

    mems = [_mem("忌口", "吃素")]
    assert "当前有效" in format_memory_changes(_UNKNOWN, mems, {"忌口"})
    assert format_memory_changes({"忌口": "吃素"}, mems, {"忌口"}) == ""
