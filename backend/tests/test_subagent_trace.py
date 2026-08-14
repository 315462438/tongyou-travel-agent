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


# ---------- 完整输入输出（Phase 94：面板可点开看详情） ----------

def test_full_prompt_is_kept_not_only_the_preview(tracker):
    """列表行只放 60 字摘要，但点开要能看到派给子代理的**完整**任务描述。"""
    t, _ = tracker
    rid = _uuid()
    long_desc = "你是资深前端工程师。" + "请分析以下文件：" * 200
    _start_task(t, rid, long_desc)
    row = t.snapshot()[0]
    assert len(row["prompt"]) <= 62                # 摘要仍是短的
    assert len(row["prompt_full"]) > 1000          # 全文留着
    assert row["prompt_full"].startswith("你是资深前端工程师。")


def test_output_is_captured_on_success(tracker):
    t, _ = tracker
    rid = _uuid()
    _start_task(t, rid, "查天气")
    t.on_tool_end("亚庇 10 月多雨，降雨概率约 60%。", run_id=rid)
    assert "降雨概率" in t.snapshot()[0]["output"]


def test_output_captures_the_error_when_the_subagent_fails(tracker):
    """失败时点开要能看到**为什么**失败，而不是一个空白的回复页。"""
    t, _ = tracker
    rid = _uuid()
    _start_task(t, rid, "查天气")
    t.on_tool_error(RuntimeError("boom"), run_id=rid)
    row = t.snapshot()[0]
    assert row["status"] == "failed" and "boom" in row["output"]


@pytest.mark.parametrize("payload,expect", [
    ("纯字符串结果", "纯字符串结果"),
    ({"messages": [{"content": "第一条"}, {"content": "最后一条"}]}, "最后一条"),
    ({"output": "取 output 字段"}, "取 output 字段"),
    (None, ""),
])
def test_output_shapes_from_deepagents_are_all_handled(tracker, payload, expect):
    """deepagents 子代理的返回形态不固定：字符串 / 子图状态 / 消息对象都可能。"""
    t, _ = tracker
    rid = _uuid()
    _start_task(t, rid, "查天气")
    t.on_tool_end(payload, run_id=rid)
    assert t.snapshot()[0]["output"] == expect


def test_absurdly_long_output_is_clipped_with_a_notice(tracker):
    """截断要**说明自己截断了**，否则读的人会以为子代理就回了这么多。"""
    t, _ = tracker
    rid = _uuid()
    _start_task(t, rid, "查天气")
    t.on_tool_end("字" * 50000, run_id=rid)
    out = t.snapshot()[0]["output"]
    assert len(out) < 50000 and "已截断" in out and "50000" in out


def test_polling_payload_drops_the_heavy_fields():
    """`/messages` 是 800ms 一轮的轮询接口，不该每次都拖着几十 KB 全文。

    详情走 `/subagents/{run_id}` 按需取——库里存的那份**必须**仍是全的，
    剥离只发生在返回给前端的路上。
    """
    from app.api.chat_api import _light_meta

    meta = {"subagents": [{"id": "r1", "title": "t", "prompt": "摘要",
                           "prompt_full": "很长的全文", "output": "很长的回复"}]}
    slim = _light_meta(meta)
    row = slim["subagents"][0]
    assert row["prompt"] == "摘要" and row["title"] == "t"
    assert "prompt_full" not in row and "output" not in row
    # 原对象不能被就地改坏——它可能还要被别处读
    assert meta["subagents"][0]["prompt_full"] == "很长的全文"


def test_light_meta_passes_through_unrelated_metas():
    from app.api.chat_api import _light_meta

    assert _light_meta(None) is None
    assert _light_meta({"poster": {"x": 1}}) == {"poster": {"x": 1}}
    assert _light_meta({"subagents": "坏数据"}) == {"subagents": "坏数据"}
