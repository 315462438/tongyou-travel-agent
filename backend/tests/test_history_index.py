"""跨会话历史检索索引（2026-07-31）。

计划：docs/task_plans/跨会话历史检索索引-2026-07-31.md
改造前用**标题子串**猜目的地 + 对每个命中会话再查一次它的全部消息（N+1）。
现在读 travel_conversation.destination / guide_message_id，固定 2 次查询。全部离线。
"""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.agent.memory import recall_past_chats
from app.db.models import Base, TravelConversation, TravelMessage

GUIDE = "成都攻略：" + "铁像寺水街喝盖碗茶，玉林街扫串串。" * 12


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _conv(db, title, destination, guide=GUIDE, link_index=True):
    c = TravelConversation(user_id="u1", title=title, destination=destination)
    db.add(c)
    db.flush()
    m = TravelMessage(conversation_id=c.id, role="assistant", content=guide)
    db.add(m)
    db.flush()
    if link_index:
        c.guide_message_id = m.id
    db.commit()
    return c


# ---------- 正确性：标题不再参与判定 ----------

def test_finds_conversation_whose_title_lacks_city(db):
    """改造前的核心漏检：第一句没报城市 → 标题里没有 → 永远检索不到。"""
    target = _conv(db, "帮我规划十一去玩", destination="成都")
    chats = recall_past_chats(db, "u1", "成都", exclude_cid="none")
    assert [c["conversation_id"] for c in chats] == [target.id]


def test_multi_city_overlap_match(db):
    """改造前 "武汉、开封、洛阳" in title 几乎必然失败；现在按城市重叠匹配。"""
    target = _conv(db, "动车游", destination="武汉、开封、洛阳")
    assert recall_past_chats(db, "u1", "开封", exclude_cid="none")[0]["conversation_id"] == target.id
    assert recall_past_chats(db, "u1", "洛阳、西安", exclude_cid="none")[0]["conversation_id"] == target.id
    assert recall_past_chats(db, "u1", "西安", exclude_cid="none") == []


def test_city_suffix_normalized(db):
    """复用 site_router.split_cities：剥「市」后缀，成都市 == 成都。"""
    _conv(db, "旧对话", destination="成都市")
    assert recall_past_chats(db, "u1", "成都", exclude_cid="none")


def test_excludes_current_and_other_users(db):
    cur = _conv(db, "本轮", destination="成都")
    other = TravelConversation(user_id="u2", title="别人的", destination="成都")
    db.add(other)
    db.commit()
    assert recall_past_chats(db, "u1", "成都", exclude_cid=cur.id) == []


def test_unindexed_conversation_ignored(db):
    """没出过攻略的会话（destination 为空）不参与检索。"""
    _conv(db, "只是闲聊", destination=None)
    assert recall_past_chats(db, "u1", "成都", exclude_cid="none") == []


def test_falls_back_to_scan_when_index_missing(db):
    """老会话回填不到 guide_message_id → 退回逐条扫描，仍能取到正文。"""
    _conv(db, "老会话", destination="成都", link_index=False)
    chats = recall_past_chats(db, "u1", "成都", exclude_cid="none")
    assert len(chats) == 1 and chats[0]["snippet"].startswith("成都攻略")


# ---------- 性能：查询次数与会话数无关 ----------

def test_query_count_is_constant(db):
    """N+1 消失：无论命中几个会话，都只有 2 次查询（会话列表 + 批量取正文）。"""
    engine = db.get_bind()
    for i in range(6):
        _conv(db, f"第{i}次成都行", destination="成都")

    counted = []
    event.listen(engine, "before_cursor_execute",
                 lambda *a, **k: counted.append(a[2] if len(a) > 2 else ""))
    chats = recall_past_chats(db, "u1", "成都", exclude_cid="none", limit=3)
    selects = [s for s in counted if s.strip().upper().startswith("SELECT")]
    assert len(chats) == 3
    assert len(selects) == 2, f"期望 2 次查询，实际 {len(selects)}：{selects}"


# ---------- 写入点 ----------

def test_index_conversation_writes_and_keeps_first_guide(db, monkeypatch):
    from app.agent import orchestrator as orch

    c = TravelConversation(user_id="u1", title="成都")
    db.add(c)
    db.commit()

    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(orch, "get_session", lambda: _Ctx())
    orch._index_conversation(c.id, "成都", "msg-1")
    assert (c.destination, c.guide_message_id) == ("成都", "msg-1")

    # 多轮改目的地：destination 刷新，guide_message_id 保留首条
    orch._index_conversation(c.id, "重庆", "msg-2")
    assert (c.destination, c.guide_message_id) == ("重庆", "msg-1")

    # 空目的地不写
    orch._index_conversation(c.id, "  ", "msg-3")
    assert c.destination == "重庆"
