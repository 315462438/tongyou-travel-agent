"""Phase 34 全链路全文历史单测（sqlite 内存库，全离线）。

direct/guide 与研究链路对齐：未超限全文逐字注入；超限回退「近 5 轮全文 +
conversation_summary」（Claude Code 分段压缩形态）。
设计见 task_plan-phase34-全链路全文历史.md。
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Base, TravelConversation, TravelMessage

LONG_GUIDE = "哈尔滨攻略：" + "第三天推荐伏尔加庄园，理由是…" * 100  # 远超 500 字


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def seeded(monkeypatch, db):
    from contextlib import contextmanager

    @contextmanager
    def fake_session():
        yield db

    monkeypatch.setattr("app.agent.orchestrator.get_session", fake_session)
    db.add(TravelConversation(id="c1", user_id="u1", title="哈尔滨",
                              history_summary="## 用户约束\n预算3000"))
    db.add(TravelMessage(conversation_id="c1", role="user", content="哈尔滨有什么玩的"))
    db.add(TravelMessage(conversation_id="c1", role="assistant", content=LONG_GUIDE))
    db.add(TravelMessage(conversation_id="c1", role="user", content="解释一下上一轮的推荐"))  # 本轮，已落库
    db.commit()
    return db


def test_assemble_history_full_verbatim(seeded):
    """未超限：全文逐字（长攻略不截 500），与本轮重复的用户消息去重，无摘要。"""
    from app.agent.orchestrator import _assemble_history

    msgs, summary = _assemble_history("c1", current_user_text="解释一下上一轮的推荐")
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"] == LONG_GUIDE  # 逐字，追问能看到攻略后半段
    assert summary == ""


def test_assemble_history_folds_inline_when_over_limit(seeded, monkeypatch):
    """超限：就地折叠一次（写 replace 事件）而不是静默按 history_rounds 切窗。

    2026-08-22 改造前这里断言的是滑动窗口 `msgs[-history_rounds*2:]`——那个窗口砍掉的
    消息没有摘要覆盖、无记录、且边界每轮都会移动。现在唯一能改变边界的是折叠，
    而折叠一定在日志里留下一条 replace。见 docs/task_plans/移除历史滑动窗口-2026-08-22.md。
    """
    from app.agent.orchestrator import _assemble_history

    class _FakeLLM:  # 装配期折叠会真的调 LLM，单测必须挡住（离线 + 可断言）
        def classify(self, listing, model, system=""):
            return model(summary="## 用户约束\n预算3000")

    monkeypatch.setattr("app.llm.client.get_llm", lambda: _FakeLLM())
    monkeypatch.setattr(settings, "history_full_max_chars", 100)
    monkeypatch.setattr(settings, "history_rounds", 1)

    msgs, summary = _assemble_history("c1", current_user_text="解释一下上一轮的推荐")
    assert msgs and msgs[-1]["content"] == LONG_GUIDE  # 近窗仍是全文，不截 500
    assert "预算3000" in summary
    folded = [m for m in seeded.query(TravelMessage).all() if m.surface_op == "replace"]
    assert len(folded) == 1, "折叠必须在日志里留痕，可回放"


def test_guide_messages_carry_full_history(seeded):
    """build_guide_messages 走全文装配：长攻略逐字进轨迹，本轮问题只出现在末条 user。"""
    from app.agent.orchestrator import build_guide_messages

    msgs = build_guide_messages("SYS", "c1", "解释一下上一轮的推荐", "{}", "", [])
    roles = [m["role"] for m in msgs]
    assert roles == ["system", "user", "assistant", "user"]
    assert msgs[2]["content"] == LONG_GUIDE
    assert msgs[3]["content"].count("解释一下上一轮的推荐") == 1  # 去重后只在末条出现


def test_guide_messages_extra_user_kept_out_of_system(seeded):
    """Phase 58 KV 友好：每轮会变的 directive 落在**末条 user**、system 保持静态（吃前缀缓存）。"""
    from app.agent.orchestrator import build_guide_messages

    directive = "【实时数据纪律】用户未给日期，标参考价"
    msgs = build_guide_messages("STATIC_SYS", "c1", "查酒店", "{}", "", [], extra_user=directive)
    assert msgs[0] == {"role": "system", "content": "STATIC_SYS"}  # system 不含 directive
    assert directive in msgs[-1]["content"]  # directive 在末条 user
    assert msgs[-1]["content"].rstrip().endswith("查酒店")  # 问题仍在最后


def test_strip_toolcall_leak():
    """模型把 collect_source 工具调用以 DSML 标记吐进正文 → 从首个标记处剥掉，正文不受影响。"""
    from app.agent.orchestrator import _embed_images, _strip_toolcall_leak

    good = "# 成都攻略\n第一天去宽窄巷子，晚上吃火锅。"
    leaked = good + '\n<｜｜DSML｜｜tool_calls> <｜｜DSML｜｜invoke name="collect_source">开封攻略</｜｜DSML｜｜invoke>'
    assert _strip_toolcall_leak(leaked) == good
    assert "DSML" not in _embed_images(leaked, {})  # 走图片嵌入也顺带剥掉
    assert _strip_toolcall_leak(good) == good  # 无泄漏不动


def test_guide_messages_forbid_more_tools_when_sources(seeded):
    """有来源时轨迹末尾追加「资料备齐、禁工具调用」的 user 指令，防模型继续 tool-loop。"""
    from app.agent.orchestrator import build_guide_messages

    srcs = [{"url": "http://x", "title": "T", "summary": "开封资料"}]
    msgs = build_guide_messages("SYS", "c1", "解释一下上一轮的推荐", "{}", "", srcs)
    assert msgs[-1]["role"] == "user"
    assert "全部" in msgs[-1]["content"] and "工具" in msgs[-1]["content"]
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in msgs)  # 合成 tool_calls
    assert any(m.get("role") == "tool" for m in msgs)  # tool 结果


def test_direct_and_guide_share_threshold_setting():
    """direct/guide 用 history_full_max_chars，研究链路用自己的上限——各自可调。"""
    assert settings.history_full_max_chars > 0
    assert settings.deep_research_history_max_chars > 0


# ---------- P0（Phase 50）：截断检测 ----------

def test_stream_finish_reason_surfaced(monkeypatch):
    """stream_generate_with_reasoning 末块 yield ('finish', reason)——供调用方判断截断。"""
    from app.llm.client import LLMClient

    class _Delta:
        def __init__(self, content=None, reasoning_content=None):
            self.content = content
            self.reasoning_content = reasoning_content

    class _Choice:
        def __init__(self, delta, finish=None):
            self.delta = delta
            self.finish_reason = finish

    class _Chunk:
        def __init__(self, choice):
            self.choices = [choice]

    def fake_create(**kw):
        return iter([
            _Chunk(_Choice(_Delta(content="酒店介绍到一半"))),
            _Chunk(_Choice(_Delta(content=""), finish="length")),  # 截断
        ])

    client = LLMClient.__new__(LLMClient)
    client._client = type("C", (), {"chat": type("Ch", (), {"completions": type("Co", (), {"create": staticmethod(fake_create)})()})()})()

    events = list(client.stream_generate_with_reasoning(messages=[{"role": "user", "content": "x"}]))
    assert ("content", "酒店介绍到一半") in events
    assert ("finish", "length") in events  # 截断信号被抛出
