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
    assert previous_injected_memories("c1").shown == {"忌口": {"吃素"}}


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
    assert previous_injected_memories("c1").shown == {"忌口": {"吃素"}}


def test_empty_memories_used_is_known_not_unknown(db):
    """上一轮确实一条记忆都没注入 → Known(空)，不该退化成 Unknown。"""
    from app.agent.memory import previous_injected_memories

    _reply(db, 1, used=[{"kind": "past_chat", "title": "t", "content": "c"}])
    assert previous_injected_memories("c1").shown == {}


# ---------- 变更渲染 ----------
#
# `previous` 现在是 InjectionHistory（shown = 全会话展示过的每个 (key, value)，
# announced = 已通知过什么）。`_h` 把简写展开成它。

def _h(shown: dict, announced: dict | None = None):
    from app.agent.memory import InjectionHistory

    return InjectionHistory(
        {k: (set(v) if isinstance(v, (set, list)) else {v}) for k, v in shown.items()},
        announced or {},
    )


def test_absent_emits_nothing():
    from app.agent.memory import format_memory_changes

    assert format_memory_changes(None, [_mem("忌口", "吃素")], {"忌口"}) == ("", {})


def test_addition_emits_nothing():
    """新增不与历史里任何表述矛盾，说了是噪声（同 Codex 不加 REPLACEMENT_NOTICE 那格）。"""
    from app.agent.memory import format_memory_changes

    assert format_memory_changes(_h({}), [_mem("忌口", "吃素")], {"忌口"}) == ("", {})


def test_update_is_announced():
    from app.agent.memory import format_memory_changes

    out, newly = format_memory_changes(_h({"忌口": "吃素"}), [_mem("忌口", "不忌口")], {"忌口"})
    assert "忌口" in out and "不忌口" in out and "已更新" in out
    assert newly == {"忌口": "不忌口"}


def test_removal_is_announced():
    """最要紧的一格：删除必须显式说，否则模型只看得到自己早前基于旧偏好写的推荐。"""
    from app.agent.memory import format_memory_changes

    out, newly = format_memory_changes(_h({"忌口": "吃素"}), [], set())
    assert "忌口" in out and "不再适用" in out
    assert newly == {"忌口": None}


def test_filtered_out_memory_is_not_reported_as_removed():
    """本轮没被 select_relevant_memories 选中 ≠ 用户撤回了偏好。

    这是最容易写错、且错了会**主动误导模型**的一格：报成删除会让模型以为用户
    推翻了自己说过的话。判据是「库里还有没有」，不是「这轮注没注入」。
    """
    from app.agent.memory import format_memory_changes

    assert format_memory_changes(_h({"忌口": "吃素"}), [], all_keys={"忌口"}) == ("", {})


def test_unknown_emits_blanket_authority_notice():
    """Unknown 往「通知」这边倒——代价不对称：多说一句只是几十 token，
    漏说则模型继续按历史里那条已被推翻的约束作答。"""
    from app.agent.memory import _UNKNOWN, format_memory_changes

    out, newly = format_memory_changes(_UNKNOWN, [_mem("忌口", "不忌口")], {"忌口"})
    assert "当前有效" in out
    assert newly == {}  # 兜底重申不进账本（它没有具体针对哪个 key）


def test_no_change_emits_nothing():
    from app.agent.memory import format_memory_changes

    assert format_memory_changes(_h({"忌口": "吃素"}), [_mem("忌口", "吃素")], {"忌口"}) == ("", {})


def test_update_and_removal_together():
    from app.agent.memory import format_memory_changes

    out, newly = format_memory_changes(
        _h({"忌口": "吃素", "预算": "3000"}), [_mem("忌口", "不忌口")], all_keys={"忌口"},
    )
    assert "已更新" in out and "不再适用" in out
    assert newly == {"忌口": "不忌口", "预算": None}


# ---------- 跨轮累积（2026-08-24 修的那个洞）----------

def test_change_is_caught_even_if_key_was_filtered_out_last_turn():
    """病灶是**跨轮累积**的，不能只跟上一轮比。

    第 1 轮展示「忌口=吃素」→ 模型写下素食推荐（病灶从此留在历史里）；
    第 2 轮用户问机场怎么走、忌口被相关性筛掉；第 3 轮忌口被删。
    只跟第 2 轮比的话 `忌口 ∉ previous` → 静默漏发，而第 1 轮那段推荐还在。
    """
    from app.agent.memory import format_memory_changes

    # shown 收的是全会话展示过的，第 2 轮没提不影响
    out, newly = format_memory_changes(_h({"忌口": "吃素", "预算": "3000"}),
                                       [_mem("预算", "3000")], all_keys={"预算"})
    assert "忌口" in out and "不再适用" in out
    assert newly == {"忌口": None}


def test_aggregates_shown_values_across_the_whole_conversation(db):
    """previous_injected_memories 聚合全会话，不是只读最近一条。"""
    from app.agent.memory import previous_injected_memories

    _reply(db, 1, used=[{"kind": "memory", "key": "忌口", "content": "吃素"},
                        {"kind": "memory", "key": "预算", "content": "3000"}])
    _reply(db, 2, used=[{"kind": "memory", "key": "预算", "content": "3000"}])  # 忌口被筛掉
    hist = previous_injected_memories("c1")
    assert hist.shown == {"忌口": {"吃素"}, "预算": {"3000"}}


def test_shown_keeps_every_historical_value_not_just_the_latest(db):
    """同一个 key 展示过多个值时全都要留——历史里可能有基于任意一个值写下的内容。"""
    from app.agent.memory import previous_injected_memories

    _reply(db, 1, used=[{"kind": "memory", "key": "预算", "content": "3000"}])
    _reply(db, 2, used=[{"kind": "memory", "key": "预算", "content": "8000"}])
    assert previous_injected_memories("c1").shown == {"预算": {"3000", "8000"}}


def test_older_legacy_message_does_not_pin_conversation_to_unknown(db):
    """只用**最近**那条判 Unknown：一条老消息不该让整个会话永远发兜底重申。"""
    from app.agent.memory import previous_injected_memories

    _reply(db, 1)  # 老消息，没有 memories_used
    _reply(db, 2, used=[{"kind": "memory", "key": "忌口", "content": "吃素"}])
    hist = previous_injected_memories("c1")
    assert hist is not None and hasattr(hist, "shown")
    assert hist.shown == {"忌口": {"吃素"}}


# ---------- 「恰好通知一次」 ----------

def test_notice_fires_exactly_once_after_an_update():
    """并集里旧值永远在，所以「只说一遍」靠的是 announced 账本，不是 diff 自然消失。"""
    from app.agent.memory import format_memory_changes

    now = [_mem("忌口", "不忌口")]
    shown = {"忌口": {"吃素", "不忌口"}}  # 第 N 轮通知后，新值也进了 shown

    out1, newly = format_memory_changes(_h({"忌口": "吃素"}), now, {"忌口"})
    assert "已更新" in out1 and newly == {"忌口": "不忌口"}

    # 第 N+1 轮：announced 记着已经说过 → 不再重复
    out2, newly2 = format_memory_changes(_h(shown, announced=newly), now, {"忌口"})
    assert (out2, newly2) == ("", {})


def test_removal_notice_fires_exactly_once():
    from app.agent.memory import format_memory_changes

    out1, newly = format_memory_changes(_h({"忌口": "吃素"}), [], set())
    assert "不再适用" in out1 and newly == {"忌口": None}

    out2, newly2 = format_memory_changes(_h({"忌口": "吃素"}, announced=newly), [], set())
    assert (out2, newly2) == ("", {})


def test_second_change_is_announced_again():
    """「只说一遍」是针对**同一次**变更；再次变更必须再说。

    账本记的是「上次通知的新值」而不是「这个 key 通知过了」，就是为了这个。
    """
    from app.agent.memory import format_memory_changes

    prev = _h({"预算": {"3000", "8000"}}, announced={"预算": "8000"})
    out, newly = format_memory_changes(prev, [_mem("预算", "12000")], {"预算"})
    assert "12000" in out and newly == {"预算": "12000"}


def test_readded_memory_after_removal_is_announced():
    """通知过移除（announced=None）之后又加回来 → 与账本不一致，要再说一次。"""
    from app.agent.memory import format_memory_changes

    prev = _h({"忌口": "吃素"}, announced={"忌口": None})
    out, newly = format_memory_changes(prev, [_mem("忌口", "不吃辣")], {"忌口"})
    assert "已更新" in out and newly == {"忌口": "不吃辣"}


def test_announced_ledger_accumulates_across_turns(db):
    """announced 由旧到新回放合并，新的覆盖旧的。"""
    from app.agent.memory import previous_injected_memories

    _reply(db, 1, used=[{"kind": "memory", "key": "预算", "content": "3000"}],
           memories_changed={"预算": "3000"})
    _reply(db, 2, used=[{"kind": "memory", "key": "预算", "content": "8000"}],
           memories_changed={"预算": "8000"})
    assert previous_injected_memories("c1").announced == {"预算": "8000"}
