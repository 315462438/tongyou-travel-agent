"""记忆系统（Phase 4）单测。

DB 用 sqlite 内存库（模型可移植），LLM 用 fake 对象，全部离线。
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.memory import (
    apply_ops,
    format_memories_block,
    format_past_chats_block,
    load_memories,
    plan_memory_ops,
    recall_past_chats,
)
from app.db.models import Base, TravelConversation, TravelMemory, TravelMessage
from app.schemas.memory_schema import MemoryOp, MemoryUpdatePlan


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# ---------- apply_ops ----------

def test_apply_add(db):
    plan = MemoryUpdatePlan(ops=[MemoryOp(op="add", type="preference", content="用户爱吃辣")])
    applied = apply_ops(db, plan, "u1", source_cid="c1")
    assert len(applied) == 1 and applied[0]["op"] == "add"
    rows = load_memories(db, "u1")
    assert len(rows) == 1
    assert rows[0].content == "用户爱吃辣"
    assert rows[0].source_conversation_id == "c1"


def test_apply_update_and_delete(db):
    row = TravelMemory(user_id="u1", type="preference", content="用户爱吃辣")
    db.add(row)
    db.commit()

    plan = MemoryUpdatePlan(ops=[MemoryOp(op="update", id=row.id, type="preference", content="用户不吃辣了")])
    applied = apply_ops(db, plan, "u1")
    assert applied[0]["op"] == "update"
    assert db.get(TravelMemory, row.id).content == "用户不吃辣了"

    plan = MemoryUpdatePlan(ops=[MemoryOp(op="delete", id=row.id)])
    applied = apply_ops(db, plan, "u1")
    assert applied[0]["op"] == "delete"
    assert load_memories(db, "u1") == []


def test_apply_ops_tolerates_bad_input(db):
    plan = MemoryUpdatePlan(ops=[
        MemoryOp(op="add", content=""),  # 空内容 add
        MemoryOp(op="update", id="nonexistent", content="x"),  # 找不到 id
        MemoryOp(op="delete", id="nonexistent"),
        MemoryOp(op="explode", content="x"),  # 非法 op
        MemoryOp(op="add", type="weird_type", content="用户有一只猫"),  # 非法 type → 归一化
    ])
    applied = apply_ops(db, plan, "u1")
    assert len(applied) == 1
    assert applied[0]["type"] == "preference"  # weird_type 归一化为默认


# ---------- 注入块 ----------

def test_format_memories_block(db):
    assert format_memories_block([]) == ""
    db.add(TravelMemory(user_id="u1", type="fact", content="用户常驻上海"))
    db.commit()
    block = format_memories_block(load_memories(db, "u1"))
    assert "长期记忆" in block and "[事实] 用户常驻上海" in block


def test_format_past_chats_block():
    assert format_past_chats_block([]) == ""
    block = format_past_chats_block([{"title": "成都3日游", "snippet": "为你规划了…"}])
    assert "「成都3日游」" in block


# ---------- 历史会话检索 ----------

_LONG_GUIDE = "成都攻略如下：" + "第一天先去宽窄巷子逛吃，晚上看夜景。" * 12  # 够长，过滤阈值以上


def _seed_conv(db, title, reply=_LONG_GUIDE, destination=None):
    """建一个「已出过攻略」的会话。2026-07-31 起检索读 destination/guide_message_id
    两个索引列（finalize_guide 落盘），不再靠标题子串猜，fixture 同步。"""
    c = TravelConversation(user_id="u1", title=title, destination=destination or title)
    db.add(c)
    db.flush()
    m = TravelMessage(conversation_id=c.id, role="assistant", content=reply)
    db.add(m)
    db.flush()
    c.guide_message_id = m.id
    db.commit()
    return c


def test_recall_only_destination_match(db):
    _seed_conv(db, "我想去重庆玩2天", destination="重庆")
    target = _seed_conv(db, "成都3日游规划", destination="成都")
    chats = recall_past_chats(db, "u1", "成都", exclude_cid="none", limit=3)
    assert chats and chats[0]["conversation_id"] == target.id
    assert chats[0]["snippet"].startswith("成都攻略")


def test_recall_no_match_returns_empty(db):
    """Phase 20：无目的地命中不再倒灌最近会话（噪声）。"""
    _seed_conv(db, "我想去重庆玩2天", destination="重庆")
    _seed_conv(db, "我想去香港玩", destination="香港")
    assert recall_past_chats(db, "u1", "北海道", exclude_cid="none") == []
    assert recall_past_chats(db, "u1", "", exclude_cid="none") == []  # 无目的地 → 空


def test_recall_skips_junk_first_reply(db):
    """标题命中但首回复是停止/过短 → 跳过；有后续像样攻略则取它。"""
    # guide_message_id 留空 → 走「索引缺失退回逐条扫描」的兜底分支
    c = TravelConversation(user_id="u1", title="厦门2天路线", destination="厦门")
    db.add(c)
    db.flush()
    db.add(TravelMessage(conversation_id=c.id, role="assistant", content="已停止本轮。"))
    db.commit()
    assert recall_past_chats(db, "u1", "厦门", exclude_cid="none") == []  # 只有停止消息 → 跳过

    db.add(TravelMessage(conversation_id=c.id, role="assistant",
                         content="厦门攻略：" + "环岛路骑行看海，八市寻鲜吃海蛎煎。" * 12))
    db.commit()
    chats = recall_past_chats(db, "u1", "厦门", exclude_cid="none")
    assert len(chats) == 1 and chats[0]["snippet"].startswith("厦门攻略")


def test_recall_skips_streaming_and_poster(db):
    c = TravelConversation(user_id="u1", title="杭州3天")
    db.add(c)
    db.flush()
    db.add(TravelMessage(conversation_id=c.id, role="assistant", content="流式占位" * 40,
                         meta_json=json.dumps({"streaming": True})))
    db.add(TravelMessage(conversation_id=c.id, role="assistant", content="海报标题",
                         meta_json=json.dumps({"poster": {"title": "x"}})))
    db.commit()
    assert recall_past_chats(db, "u1", "杭州", exclude_cid="none") == []


def test_clean_snippet_strips_markdown():
    from app.agent.memory import _clean_snippet
    assert _clean_snippet("## Day 1\n**上午**：去景点") == "Day 1 上午：去景点"


def test_complete_trip_request_filters_superseded_trip_and_interest(monkeypatch, db):
    """新完整规划不能继续注入旧 13 天行程或旧「鲜花」兴趣。"""
    from contextlib import contextmanager

    from app.agent.memory import gather_context

    @contextmanager
    def fake_session():
        yield db

    monkeypatch.setattr("app.db.session.get_session", fake_session)
    db.add_all([
        TravelMemory(user_id="u1", type="trip_state", key="当前行程", content="用户正在规划拉萨13天"),
        TravelMemory(user_id="u1", type="preference", key="兴趣偏好", content="用户喜欢鲜花主题"),
        TravelMemory(user_id="u1", type="preference", key="节奏偏好", content="用户喜欢轻松节奏"),
    ])
    db.commit()
    ctx = gather_context(
        "none", "拉萨", "u1",
        user_text="规划武汉到拉萨15天轻松行程，包括路线、酒店和预算",
    )
    assert "13天" not in ctx["block"] and "鲜花" not in ctx["block"]
    assert "轻松节奏" in ctx["block"]


# ---------- 提炼 ----------

class FakeLLM:
    def __init__(self, plan):
        self.plan = plan
        self.last_prompt = ""

    def classify(self, prompt, schema, *, system=None):
        self.last_prompt = prompt
        return self.plan


def test_plan_memory_ops_includes_existing_ids(db):
    row = TravelMemory(user_id="u1", type="preference", content="用户爱吃辣")
    db.add(row)
    db.commit()
    llm = FakeLLM(MemoryUpdatePlan(ops=[]))
    plan_memory_ops(llm, load_memories(db, "u1"), "我不吃辣了", "好的")
    # 已有记忆的 id 必须进 prompt，否则模型无法给出 update/delete
    assert row.id in llm.last_prompt and "我不吃辣了" in llm.last_prompt
    assert plan_memory_ops(llm, [], "你好", "你好").ops == []
