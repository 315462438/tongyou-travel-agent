"""子代理面板（Phase 88）单测：run 树 token 归属 / 生命周期 / 落库节流。

全离线：sqlite 内存库 + 手工构造的 callback 事件序列。
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.subagent_trace import SubagentTracker, _title_of
from app.db.models import Base, TravelConversation, TravelMessage


@pytest.fixture()
def tracker(monkeypatch):
    """把落库指向 sqlite 内存库；返回 (tracker, session)。"""
    from contextlib import contextmanager

    import app.agent.subagent_trace as mod

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(TravelConversation(id="c1", user_id="u1", title="研究"))
    session.commit()

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr("app.db.session.get_session", fake_session)
    monkeypatch.setattr(mod, "_FLUSH_INTERVAL_S", 0)  # 测试里不节流
    return SubagentTracker("c1"), session


def _uuid() -> UUID:
    return uuid4()


class _Resp:
    """模拟 LLM 响应的用量载体。"""

    def __init__(self, total: int, style: str = "llm_output"):
        if style == "llm_output":
            self.llm_output = {"token_usage": {"total_tokens": total}}
            self.generations = []
        else:  # 新版 LangChain 挂在 message.usage_metadata
            self.llm_output = None
            msg = type("M", (), {"usage_metadata": {"total_tokens": total}})()
            gen = type("G", (), {"message": msg})()
            self.generations = [[gen]]


def _start_task(t: SubagentTracker, run_id: UUID, desc: str, sub_type="api-researcher"):
    t.on_tool_start({"name": "task"}, "", run_id=run_id,
                    inputs={"description": desc, "subagent_type": sub_type})


# ---------- 生命周期 ----------

def test_task_start_creates_a_visible_run(tracker):
    t, _ = tracker
    rid = _uuid()
    _start_task(t, rid, "查一下亚庇的天气和海岛门票。需要给出每天的降雨概率。")
    rows = t.snapshot()
    assert len(rows) == 1
    assert rows[0]["name"] == "api-researcher"
    assert rows[0]["status"] == "running"
    assert "亚庇" in rows[0]["title"]


def test_non_task_tools_are_ignored(tracker):
    """只跟踪子代理派发；普通工具调用不该出现在面板上。"""
    t, _ = tracker
    t.on_tool_start({"name": "web_search"}, "亚庇", run_id=_uuid(), inputs={"query": "亚庇"})
    assert t.snapshot() == []


def test_tool_end_marks_done_and_freezes_elapsed(tracker):
    t, _ = tracker
    rid = _uuid()
    _start_task(t, rid, "查天气")
    t.on_tool_end("结果", run_id=rid)
    row = t.snapshot()[0]
    assert row["status"] == "done"
    frozen = row["elapsed_s"]
    assert t.snapshot()[0]["elapsed_s"] == frozen  # 结束后不再走时


def test_tool_error_marks_failed(tracker):
    t, _ = tracker
    rid = _uuid()
    _start_task(t, rid, "查天气")
    t.on_tool_error(RuntimeError("boom"), run_id=rid)
    assert t.snapshot()[0]["status"] == "failed"


def test_finalize_closes_stragglers(tracker):
    """被取消/超时的一轮，不能在历史里留下永远转圈的绿点。"""
    t, _ = tracker
    _start_task(t, _uuid(), "查天气")
    t.finalize()
    assert t.snapshot()[0]["status"] == "done"


# ---------- token 归属（run 树） ----------

def test_tokens_attributed_through_run_tree(tracker):
    """子代理内部的 LLM 调用挂在几层 chain 之下，要顺 parent 链归回派发它的 task。"""
    t, _ = tracker
    task_run = _uuid()
    _start_task(t, task_run, "查天气")

    chain = _uuid()
    t.on_chain_start({}, {}, run_id=chain, parent_run_id=task_run)
    llm = _uuid()
    t.on_chat_model_start({}, [], run_id=llm, parent_run_id=chain)
    t.on_llm_end(_Resp(1500), run_id=llm, parent_run_id=chain)

    assert t.snapshot()[0]["tokens"] == 1500


def test_tokens_accumulate_across_calls(tracker):
    t, _ = tracker
    task_run = _uuid()
    _start_task(t, task_run, "查天气")
    for _ in range(3):
        llm = _uuid()
        t.on_chat_model_start({}, [], run_id=llm, parent_run_id=task_run)
        t.on_llm_end(_Resp(1000), run_id=llm, parent_run_id=task_run)
    assert t.snapshot()[0]["tokens"] == 3000


def test_main_agent_tokens_are_not_attributed(tracker):
    """主 agent 自己的 LLM 调用不属于任何子代理，不能计进面板。"""
    t, _ = tracker
    _start_task(t, _uuid(), "查天气")
    orphan = _uuid()
    t.on_chat_model_start({}, [], run_id=orphan, parent_run_id=_uuid())
    t.on_llm_end(_Resp(9999), run_id=orphan, parent_run_id=_uuid())
    assert t.snapshot()[0]["tokens"] == 0


def test_parallel_subagents_keep_separate_token_counts(tracker):
    """并发派多个子代理时，token 不能互相串（这正是面板要回答的问题）。"""
    t, _ = tracker
    a, b = _uuid(), _uuid()
    _start_task(t, a, "查天气", "api-researcher")
    _start_task(t, b, "读小红书", "api-researcher")
    for run, tok in ((a, 500), (b, 1200)):
        llm = _uuid()
        t.on_chat_model_start({}, [], run_id=llm, parent_run_id=run)
        t.on_llm_end(_Resp(tok), run_id=llm, parent_run_id=run)
    by_title = {r["title"]: r["tokens"] for r in t.snapshot()}
    assert by_title["查天气"] == 500 and by_title["读小红书"] == 1200


def test_usage_metadata_style_is_also_counted(tracker):
    """新版 LangChain 把用量挂在 message.usage_metadata，两种形态都要能取到。"""
    t, _ = tracker
    rid = _uuid()
    _start_task(t, rid, "查天气")
    llm = _uuid()
    t.on_chat_model_start({}, [], run_id=llm, parent_run_id=rid)
    t.on_llm_end(_Resp(777, style="usage_metadata"), run_id=llm, parent_run_id=rid)
    assert t.snapshot()[0]["tokens"] == 777


def test_missing_usage_does_not_break(tracker):
    """取不到用量就记 0——面板少个数字可以，抛异常打断研究不行。"""
    t, _ = tracker
    rid = _uuid()
    _start_task(t, rid, "查天气")
    llm = _uuid()
    t.on_chat_model_start({}, [], run_id=llm, parent_run_id=rid)
    t.on_llm_end(object(), run_id=llm, parent_run_id=rid)
    assert t.snapshot()[0]["tokens"] == 0


def test_cyclic_parent_chain_terminates(tracker):
    """parent 链理论上不该成环，但走树的代码必须自带深度上限。"""
    t, _ = tracker
    a, b = str(_uuid()), str(_uuid())
    t._parent[a] = b
    t._parent[b] = a
    assert t._owning_run(None, UUID(a)) is None  # 不死循环


# ---------- 落库 ----------

def test_panel_is_written_as_progress_message_with_meta(tracker):
    t, session = tracker
    _start_task(t, _uuid(), "查亚庇天气")
    rows = session.query(TravelMessage).filter_by(conversation_id="c1").all()
    assert len(rows) == 1
    assert rows[0].role == "progress"
    assert "subagents" in (rows[0].meta_json or "")


def test_panel_updates_in_place_not_appended(tracker):
    """面板是一条会更新的消息，不是每次变化都新增一条——否则会把对话刷爆。"""
    t, session = tracker
    rid = _uuid()
    _start_task(t, rid, "查天气")
    t.on_tool_end("ok", run_id=rid)
    _start_task(t, _uuid(), "读小红书")
    assert session.query(TravelMessage).filter_by(conversation_id="c1").count() == 1


def test_write_failure_does_not_propagate(tracker, monkeypatch):
    """观测失败绝不能影响研究主流程。"""
    t, _ = tracker

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(t, "_write", boom)
    _start_task(t, _uuid(), "查天气")  # 不抛异常即通过
    assert t.snapshot()[0]["status"] == "running"


# ---------- 标题提炼 ----------

@pytest.mark.parametrize("desc,expect", [
    ("查一下亚庇的天气。需要每天降雨概率", "查一下亚庇的天气"),
    ("读小红书攻略；重点看避坑", "读小红书攻略"),
    ("", "api-researcher"),
])
def test_title_extraction(desc, expect):
    assert _title_of(desc, "api-researcher") == expect
