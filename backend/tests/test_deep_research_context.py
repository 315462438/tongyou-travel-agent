"""Phase 33 深度研究跨轮上下文单测（sqlite 内存库 + fake，全离线）。

全量历史注入 / 超限回退窄窗 / 记忆末置 / 轮末钩子 / SummarizationMiddleware 装配。
设计见 task_plan-phase33-深度研究跨轮上下文.md。
"""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Base, TravelConversation, TravelMessage


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def seeded(monkeypatch, db):
    """两轮历史 + 本轮问题（已落库，模拟 chat_api 先写用户消息再起后台任务）。"""
    from contextlib import contextmanager

    @contextmanager
    def fake_session():
        yield db

    monkeypatch.setattr("app.agent.orchestrator.get_session", fake_session)
    monkeypatch.setattr(
        "app.agent.memory.gather_context",
        lambda cid, dest, uid, user_text="": {"block": "用户爱吃辣", "used": [{"kind": "memory", "content": "用户爱吃辣"}]},
    )
    db.add(TravelConversation(id="c1", user_id="u1", title="东北对比"))
    long_report = "哈尔滨 vs 长春对比报告：" + "内容段落。" * 300  # 长报告不截断
    db.add(TravelMessage(conversation_id="c1", role="user", content="哈尔滨和长春冬天去哪个？"))
    db.add(TravelMessage(conversation_id="c1", role="assistant", content=long_report))
    db.add(TravelMessage(conversation_id="c1", role="progress", content="不该出现"))
    db.add(TravelMessage(conversation_id="c1", role="user", content="按预算3000重新对比"))  # 本轮问题
    db.commit()
    return db


# ---------- 全量历史注入 ----------

def test_turn_messages_carry_full_history(seeded):
    from app.agent.deep_research import _build_turn_messages

    msgs, mem_ctx = _build_turn_messages("c1", "按预算3000重新对比", "u1")

    roles = [m["role"] for m in msgs]
    assert roles == ["user", "assistant", "user"]  # 历史两条 + 末条 user；重复的本轮问题被去掉
    assert "内容段落。" * 100 in msgs[1]["content"]  # 长报告逐字，没有 500 字截断
    final = msgs[-1]["content"]
    assert "<background_memory>" in final and "用户爱吃辣" in final
    assert final.rstrip().endswith("按预算3000重新对比")
    assert mem_ctx["used"]


def test_turn_messages_fallback_when_too_long(seeded, monkeypatch):
    from app.agent.deep_research import _build_turn_messages

    monkeypatch.setattr(settings, "deep_research_history_max_chars", 100)
    seeded.get(TravelConversation, "c1").history_summary = "## 用户约束\n预算3000"
    seeded.commit()

    msgs, _ = _build_turn_messages("c1", "按预算3000重新对比", "u1")
    final = msgs[-1]["content"]
    assert "<conversation_summary>" in final and "预算3000" in final
    # 回退窄窗：历史每条截 500 字
    assert all(len(m["content"]) <= 500 for m in msgs[:-1])


def test_turn_messages_carry_history_off(seeded, monkeypatch):
    from app.agent.deep_research import _build_turn_messages

    monkeypatch.setattr(settings, "deep_research_carry_history", False)
    msgs, _ = _build_turn_messages("c1", "按预算3000重新对比", "u1")
    assert len(msgs) == 1 and msgs[0]["role"] == "user"  # 旧行为：只带本轮问题（+记忆）


def test_turn_messages_failure_falls_back_to_bare_question(monkeypatch):
    from app.agent.deep_research import _build_turn_messages

    monkeypatch.setattr(
        "app.agent.memory.gather_context",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    msgs, mem_ctx = _build_turn_messages("c1", "问题", "u1")
    assert msgs == [{"role": "user", "content": "问题"}]
    assert mem_ctx == {"block": "", "used": []}


# ---------- 轮末钩子 ----------

def test_run_deep_research_calls_turn_end_hooks(monkeypatch):
    from app.agent import deep_research

    called = {}
    monkeypatch.setattr(settings, "docker_sandbox_enabled", False)
    monkeypatch.setattr(settings, "deep_research_stream", False)  # 本例测轮末钩子，走非流式路径
    monkeypatch.setattr(deep_research, "_build_agent", lambda *a, **kw: "fake-agent")
    monkeypatch.setattr(
        deep_research, "_build_turn_messages",
        lambda cid, text, uid: ([{"role": "user", "content": text}], {"block": "", "used": [{"kind": "memory", "content": "m"}]}),
    )

    class _AI:
        type = "ai"
        content = "最终报告"

    async def fake_invoke(cid, agent, user_text, user_id, skill_files=None, turn_messages=None, stream_msg_id=None, stream_state=None):
        called["turn_messages"] = turn_messages
        return {"messages": [_AI()]}

    monkeypatch.setattr(deep_research, "_invoke_with_cancel", fake_invoke)

    class FakeBrowserSession:
        def __init__(self, cid, user_id): ...

        async def close(self): ...

    captured_meta = {}
    monkeypatch.setattr("app.agent.research_tools.BrowserSession", FakeBrowserSession)
    monkeypatch.setattr("app.agent.orchestrator._add_message",
                        lambda cid, role, content, meta=None: captured_meta.update(meta or {}))
    monkeypatch.setattr("app.agent.orchestrator._progress", lambda *a, **kw: None)
    monkeypatch.setattr("app.agent.orchestrator.clear_plain_progress", lambda *a, **kw: None)
    monkeypatch.setattr("app.agent.memory.extract_and_save",
                        lambda cid, text, head, uid: called.setdefault("extract", True) and [{"op": "add"}])
    monkeypatch.setattr("app.agent.orchestrator.update_history_summary",
                        lambda cid: called.setdefault("summary", True))

    asyncio.run(deep_research.run_deep_research("c1", "对比一下", "u1"))

    assert called.get("extract") and called.get("summary")
    assert called["turn_messages"] == [{"role": "user", "content": "对比一下"}]
    assert captured_meta.get("memories_used") == [{"kind": "memory", "content": "m"}]
    assert captured_meta.get("memories_saved") == [{"op": "add"}]


def test_run_deep_research_streaming_finalizes(monkeypatch):
    """Phase 56：流式路径——astream 增量落 streaming 占位，收尾用最终 state 的干净终稿定稿。"""
    from app.agent import deep_research

    monkeypatch.setattr(settings, "docker_sandbox_enabled", False)
    monkeypatch.setattr(settings, "deep_research_stream", True)
    # 2026-08-14：快答先行（Phase 71）会真实调 LLM + _add_message，与「只走 finalize」的
    # 断言冲突（本机网络通时 LLM 返回内容即触发）。本测试只关心流式终稿路径，关闭无关增强。
    monkeypatch.setattr(settings, "deep_research_quick_take", False)

    class _Chunk:
        def __init__(self, content, id="m1", type="ai", reasoning=""):
            self.content, self.id, self.type = content, id, type
            self.additional_kwargs = {"reasoning_content": reasoning} if reasoning else {}

    class _FakeAgent:
        async def astream(self, inputs, config=None, stream_mode=None):
            yield ("messages", (_Chunk("", id="plan", reasoning="先查三城天气"), {}))  # 采集期：只有思考
            yield ("messages", (_Chunk("最终", id="m1", reasoning="开始汇总"), {}))     # 报告 token1 + 思考
            yield ("messages", (_Chunk("报告", id="m1"), {}))                          # 报告 token2
            yield ("messages", (_Chunk("工具结果", id="t1", type="tool"), {}))          # 工具消息不入流
            yield ("values", {"messages": [_Chunk("最终报告", id="m1")]})               # 最终 state

    monkeypatch.setattr(deep_research, "_build_agent", lambda *a, **kw: _FakeAgent())
    monkeypatch.setattr(deep_research, "_build_turn_messages",
                        lambda cid, text, uid: ([{"role": "user", "content": text}], {"block": "", "used": []}))

    captured = {}
    monkeypatch.setattr("app.agent.orchestrator._add_streaming_message", lambda cid: "sid")
    monkeypatch.setattr("app.agent.orchestrator._update_streaming_message",
                        lambda mid, content, reasoning: captured.setdefault("reasoning_seen", []).append(reasoning))
    monkeypatch.setattr("app.agent.orchestrator._finalize_streaming_message",
                        lambda mid, content, reasoning, meta: captured.update({"mid": mid, "final": content, "final_reasoning": reasoning}))
    monkeypatch.setattr("app.agent.orchestrator._add_message",
                        lambda *a, **kw: captured.setdefault("add_message_called", True))
    monkeypatch.setattr("app.agent.orchestrator._progress", lambda *a, **kw: None)
    monkeypatch.setattr("app.agent.orchestrator.clear_plain_progress", lambda *a, **kw: None)
    monkeypatch.setattr("app.agent.orchestrator.update_history_summary", lambda cid: None)
    monkeypatch.setattr("app.agent.memory.extract_and_save", lambda *a, **kw: [])

    class FakeBrowserSession:
        def __init__(self, cid, user_id): ...

        async def close(self): ...

    monkeypatch.setattr("app.agent.research_tools.BrowserSession", FakeBrowserSession)

    asyncio.run(deep_research.run_deep_research("c1", "对比一下", "u1"))
    assert captured.get("mid") == "sid"
    assert captured.get("final") == "最终报告"  # 定稿用最终 state 的干净报告，不含工具结果
    assert "add_message_called" not in captured  # 流式路径走 finalize，不再 _add_message


def test_chunk_text_filters_tool_and_extracts(monkeypatch):
    """_chunk_text/_chunk_reasoning：AI 文本+思考入流；工具消息不入流；list content 拼接。"""
    from app.agent.deep_research import _chunk_reasoning, _chunk_text

    class _M:
        def __init__(self, content, type="ai", reasoning=""):
            self.content, self.type = content, type
            self.additional_kwargs = {"reasoning_content": reasoning} if reasoning else {}

    assert _chunk_text(_M("报告片段")) == "报告片段"
    assert _chunk_text(_M("工具输出", type="tool")) == ""  # 工具结果不入流
    assert _chunk_text(_M([{"type": "text", "text": "A"}, {"type": "text", "text": "B"}])) == "AB"
    assert _chunk_text(_M(None)) == ""
    # 思考链：采集期正文空但有思考 → 取得到；工具消息不取
    assert _chunk_reasoning(_M("", reasoning="正在查天气")) == "正在查天气"
    assert _chunk_reasoning(_M("", type="tool", reasoning="x")) == ""
    assert _chunk_reasoning(_M("正文")) == ""


# ---------- 真实构建冒烟（防复发） ----------

def test_build_agent_real_construction_smoke(monkeypatch):
    """不 mock deepagents，真实构建一次图。

    教训（线上踩坑）：langchain 按中间件名判重，deepagents 内置 SummarizationMiddleware，
    我们再挂同名实例线上直接 "Please remove duplicate middleware instances"——单测全部
    mock create_deep_agent 所以没拦住。此后任何 middleware/参数改动必须过这条真实构建。
    """
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")

    class _S:
        async def call(self, *a, **kw): ...

    from app.agent.deep_research import _build_agent

    agent = _build_agent("c1", "u1", session=_S(), sources=[], user_skills=False)
    assert type(agent).__name__ == "CompiledStateGraph"
