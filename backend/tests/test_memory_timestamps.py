"""记忆三个时间戳的语义边界（2026-08-24）。

背景见 docs/task_plans/记忆时间戳语义修复-2026-08-24.md：
`updated_at` 声明了 `onupdate=_now`，而它对本行的**任何** UPDATE 都生效——于是
`_bump_hit_count` 这种纯记账写把 updated_at 推成了「最后注入时间」，
prompt 里的年龄标签（Phase 30）因此对活跃用户永远显示「今天」。

⚠️ **两个方向的断言都必须在**：只钉「记账时 updated_at 不动」的话，
把整列 onupdate 删掉也能过——那会让真正的内容变更也不再更新时间。
"""

import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.agent.memory import _bump_hit_count, _age_label
from app.db.models import Base, TravelMemory


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _mem(db, **kw):
    row = TravelMemory(user_id="u1", type="preference", key="口味偏好",
                       content="用户爱吃辣", **kw)
    db.add(row)
    db.commit()
    return row


# ---------- 方向一：纯记账写不能碰 updated_at ----------

def test_bump_does_not_touch_updated_at(db):
    m = _mem(db)
    before = m.updated_at
    time.sleep(0.01)
    _bump_hit_count(db, [m])
    db.expire_all()
    row = db.get(TravelMemory, m.id)
    assert row.updated_at == before, "注入是记账，不是内容变化，updated_at 必须纹丝不动"


def test_bump_advances_hit_count_and_last_used_at(db):
    m = _mem(db)
    assert m.last_used_at is None, "从未注入过时应为 NULL，前端据此显示「从未」"
    _bump_hit_count(db, [m])
    db.expire_all()
    row = db.get(TravelMemory, m.id)
    assert row.hit_count == 1
    assert row.last_used_at is not None


def test_bump_is_cumulative_across_turns(db):
    m = _mem(db)
    for _ in range(3):
        _bump_hit_count(db, [m])
    db.expire_all()
    assert db.get(TravelMemory, m.id).hit_count == 3


def test_bump_uses_sql_side_increment_not_read_modify_write(db):
    """SQL 侧自增：并发轮次不会互相覆盖计数。

    模拟两个会话各自持有同一行的**陈旧**副本（都以为 hit_count=0）先后记账。
    读改写实现下结果是 1（后写的覆盖前写的），SQL 自增下是 2。
    """
    m = _mem(db)
    stale_a = db.get(TravelMemory, m.id)
    _bump_hit_count(db, [stale_a])          # 落库后 hit_count=1
    _bump_hit_count(db, [stale_a])          # 副本仍以为是 0
    db.expire_all()
    assert db.get(TravelMemory, m.id).hit_count == 2


def test_bump_guards_null_hit_count_with_coalesce(db):
    """`hit_count` 是后加的列，自增必须过 coalesce，否则 NULL+1 = NULL 静默清零计数。

    NULL 值本身在这里造不出来（模型声明的是 NOT NULL，PG 那边 `ADD COLUMN ... DEFAULT 0`
    也把存量行填成了 0），所以直接钉**发出去的 SQL**——这样有人把它改回裸 `+ 1` 会当场红。
    """
    import inspect

    src = inspect.getsource(_bump_hit_count)
    assert "coalesce" in src.lower(), "自增丢了 coalesce 保护"

    m = _mem(db)
    _bump_hit_count(db, [m])
    db.expire_all()
    assert db.get(TravelMemory, m.id).hit_count == 1


def test_bump_empty_list_is_noop(db):
    _bump_hit_count(db, [])   # 不应抛


# ---------- 方向二：真的改内容时 updated_at 必须动 ----------

def test_content_change_does_advance_updated_at(db):
    """反向断言：把整列 onupdate 删掉能让方向一通过，这条会立刻红。"""
    m = _mem(db)
    before = m.updated_at
    time.sleep(0.01)
    m.content = "用户爱吃辣，忌香菜"
    db.commit()
    db.refresh(m)
    assert m.updated_at > before


def test_upsert_by_key_advances_updated_at(db):
    """走真实写路径（Phase 17 归槽 upsert）而不是裸赋值。"""
    from app.agent.memory import _upsert_by_key

    m = _mem(db)
    before = m.updated_at
    time.sleep(0.01)
    _upsert_by_key(db, "u1", "口味偏好", "preference", "用户爱吃辣，也吃酸", False, "", [])
    db.commit()
    db.expire_all()
    row = db.get(TravelMemory, m.id)
    assert row.content.endswith("也吃酸")
    assert row.updated_at > before


# ---------- 年龄标签：修复要真的传导到 prompt ----------

def test_prompt_age_label_reflects_content_age_not_injection(db):
    """端到端：一条 30 天前建立、天天被注入的记忆，prompt 里必须写「30 天前」而不是「今天」。

    这是整个改造的**目的**——Phase 30 的过期意识信号此前对活跃用户完全失效。
    """
    from datetime import datetime, timedelta

    from app.agent.memory import format_memories_block

    m = _mem(db)
    old = datetime.now() - timedelta(days=30)
    db.execute(
        text("UPDATE travel_memory SET created_at = :t, updated_at = :t WHERE id = :i"),
        {"t": old, "i": m.id},
    )
    db.commit()
    db.expire_all()

    row = db.get(TravelMemory, m.id)
    for _ in range(5):                      # 连着 5 轮注入
        _bump_hit_count(db, [row])
    db.expire_all()
    row = db.get(TravelMemory, m.id)

    assert _age_label(row.updated_at) == "30 天前"
    assert "（30 天前）" in format_memories_block([row])


# ---------- 回填幂等 ----------

def test_backfill_is_idempotent_by_predicate(db):
    """回填靠 `last_used_at IS NULL` 这道谓词幂等，不靠"只跑一次"——
    整块 DDL 在将来任何一次新增列时都会重新执行。"""
    from datetime import datetime, timedelta

    m = _mem(db)
    created = datetime.now() - timedelta(days=25)
    injected = datetime.now() - timedelta(days=2)
    db.execute(
        text("UPDATE travel_memory SET created_at = :c, updated_at = :u, last_used_at = NULL "
             "WHERE id = :i"),
        {"c": created, "u": injected, "i": m.id},
    )
    db.commit()

    backfill = ("UPDATE travel_memory SET last_used_at = updated_at, updated_at = created_at "
                "WHERE last_used_at IS NULL")
    db.execute(text(backfill))
    db.commit()
    db.expire_all()
    row = db.get(TravelMemory, m.id)
    first = (row.created_at, row.updated_at, row.last_used_at)

    # 旧 updated_at（=最后注入）搬进 last_used_at；updated_at 回落到保守下界 created_at
    assert abs((row.last_used_at - injected).total_seconds()) < 1
    assert abs((row.updated_at - created).total_seconds()) < 1

    db.execute(text(backfill))              # 再跑一次
    db.commit()
    db.expire_all()
    row = db.get(TravelMemory, m.id)
    assert (row.created_at, row.updated_at, row.last_used_at) == first, "重复执行必须无变化"


def test_real_migration_backfills_and_stays_idempotent(tmp_path, monkeypatch):
    """跑**真实**的 `migrate_and_bootstrap`，不是手写 SQL——回填是这次改动风险最高的一段。

    模拟迁移前的库：没有 last_used_at 列，且 updated_at 已被注入污染
    （建于 25 天前、最后注入 2 天前）。
    """
    from datetime import datetime, timedelta

    from sqlalchemy.orm import sessionmaker

    import app.db.session as db_session
    from app.db.migrate import migrate_and_bootstrap

    url = f"sqlite:///{tmp_path}/old.db"
    engine = create_engine(url)
    # `_bootstrap_admin_and_backfill` 用的是模块级 get_session()，不是传进去的 engine
    # （既有实现，本次不动），所以这里得把 SessionLocal 也指到临时库上。
    monkeypatch.setattr(db_session, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    created = datetime.now() - timedelta(days=25)
    injected = datetime.now() - timedelta(days=2)
    with engine.begin() as c:
        c.execute(text("""CREATE TABLE travel_memory (
            id VARCHAR(32) PRIMARY KEY, user_id VARCHAR(32), type VARCHAR(16), key VARCHAR(64),
            content TEXT, weight FLOAT, explicit BOOLEAN, hit_count INTEGER,
            source_conversation_id VARCHAR(32), created_at TIMESTAMP, updated_at TIMESTAMP)"""))
        c.execute(
            text("INSERT INTO travel_memory VALUES "
                 "('m1','u1','preference','口味偏好','爱吃辣',1.0,0,84,NULL,:c,:u)"),
            {"c": created, "u": injected},
        )

    def snap():
        with engine.begin() as c:
            return c.execute(text(
                "SELECT created_at, updated_at, last_used_at FROM travel_memory WHERE id='m1'"
            )).one()

    migrate_and_bootstrap(engine)
    first = snap()
    assert str(first[1])[:19] == str(first[0])[:19], "updated_at 应回落到 created_at（保守下界）"
    assert str(first[2])[:16] == str(injected)[:16], "last_used_at 应接住旧 updated_at"

    migrate_and_bootstrap(engine)     # 模拟下次重启
    assert snap() == first, "回填必须靠谓词幂等——这块 DDL 将来每加一列都会重跑一遍"


# ---------- 「✨ 整理记忆」按 key 继承历史（2026-08-24） ----------
#
# consolidate_memories 是"删旧建新"，默认会把每条记忆的历史清零——用户点一次整理，
# 半年前的偏好就变成「建立 刚刚 · 最后使用 从未」，亲述标记也被 LLM 重新臆断。
# key 是 Phase 17 归槽的主键，也是唯一不含猜测的祖先映射。

class _FakeLLM:
    """按 (key, content, explicit) 三元组返回整理结果。"""

    def __init__(self, triples):
        self._triples = triples

    def classify(self, _text, _schema, system=""):  # noqa: ARG002
        from app.agent.memory import MemoryConsolidation

        return MemoryConsolidation(memories=[
            {"key": k, "type": "preference", "content": c, "explicit": e}
            for k, c, e in self._triples
        ])


def _aged(db, row, *, days_old, hit, used_days_ago, content=None):
    """把一行改造成"很久以前建立、最近被用过"的样子。"""
    from datetime import datetime, timedelta

    db.execute(
        text("UPDATE travel_memory SET created_at=:c, updated_at=:c, hit_count=:h, "
             "last_used_at=:l WHERE id=:i"),
        {
            "c": datetime.now() - timedelta(days=days_old),
            "h": hit,
            "l": datetime.now() - timedelta(days=used_days_ago),
            "i": row.id,
        },
    )
    if content is not None:
        db.execute(text("UPDATE travel_memory SET content=:t WHERE id=:i"),
                   {"t": content, "i": row.id})
    db.commit()
    db.expire_all()
    return db.get(TravelMemory, row.id)


def test_consolidate_inherits_history_by_key(db):
    from app.agent.memory import consolidate_memories

    m = _aged(db, _mem(db), days_old=180, hit=84, used_days_ago=2)
    born, used = m.created_at, m.last_used_at

    consolidate_memories(db, "u1", _FakeLLM([("口味偏好", "用户爱吃辣和海鲜", False)]))
    db.expire_all()
    row = db.query(TravelMemory).filter_by(user_id="u1").one()

    assert row.content == "用户爱吃辣和海鲜"
    assert row.created_at == born, "半年前形成的偏好，整理后不该变成「建立 刚刚」"
    assert row.hit_count == 84, "命中数不该被清零"
    assert row.last_used_at == used, "最后使用不该变成「从未」"


def test_consolidate_keeps_updated_at_when_content_unchanged(db):
    """整理常常只是原样带过某个 key——那不是内容变更，年龄标签不能回到「今天」。

    否则刚修好的「prompt 年龄永远显示今天」会从整理这扇门重新进来。
    """
    from app.agent.memory import consolidate_memories

    m = _aged(db, _mem(db), days_old=30, hit=10, used_days_ago=1)
    consolidate_memories(db, "u1", _FakeLLM([("口味偏好", m.content, False)]))
    db.expire_all()
    row = db.query(TravelMemory).filter_by(user_id="u1").one()
    assert _age_label(row.updated_at) == "30 天前"


def test_consolidate_advances_updated_at_when_content_changed(db):
    """反向：内容真的被改写了，updated_at 就该推到当下。"""
    from app.agent.memory import consolidate_memories

    m = _aged(db, _mem(db), days_old=30, hit=10, used_days_ago=1)
    consolidate_memories(db, "u1", _FakeLLM([("口味偏好", "用户爱吃辣，另外忌香菜", False)]))
    db.expire_all()
    row = db.query(TravelMemory).filter_by(user_id="u1").one()
    assert row.updated_at > m.updated_at
    assert row.created_at == m.created_at, "内容变了，但建立时间仍该继承"


def test_consolidate_never_downgrades_explicit(db):
    """explicit 只升不降：LLM 只看得到内容，判不出用户当初是不是亲口说的，
    而 CONSOLIDATE_SYSTEM 还让它"拿不准填 false" —— 不继承就等于每次整理都在
    悄悄剥夺 Phase 17 的「明确表达优先」（weight 2.0→1.0，还会丢掉
    select_relevant_memories 里「explicit 始终注入」的保底）。"""
    from app.agent.memory import consolidate_memories

    m = _mem(db, explicit=True, weight=2.0)
    consolidate_memories(db, "u1", _FakeLLM([("口味偏好", m.content, False)]))
    db.expire_all()
    row = db.query(TravelMemory).filter_by(user_id="u1").one()
    assert row.explicit is True
    assert row.weight == 2.0


def test_consolidate_upgrades_explicit_when_llm_says_so(db):
    """反向：旧行不是亲述、LLM 判定是，则升上去（or 的另一半）。"""
    from app.agent.memory import consolidate_memories

    _mem(db, explicit=False)
    consolidate_memories(db, "u1", _FakeLLM([("口味偏好", "用户爱吃辣", True)]))
    db.expire_all()
    row = db.query(TravelMemory).filter_by(user_id="u1").one()
    assert row.explicit is True
    assert row.weight == 2.0


def test_consolidate_new_key_starts_fresh(db):
    """LLM 新合成的 key 在旧行里没有祖先——那就是真的新记忆，不能凭空捏造历史。"""
    from app.agent.memory import consolidate_memories

    _aged(db, _mem(db), days_old=180, hit=84, used_days_ago=2)
    consolidate_memories(db, "u1", _FakeLLM([("规划习惯", "用户习惯先定酒店再排景点", False)]))
    db.expire_all()
    row = db.query(TravelMemory).filter_by(user_id="u1").one()
    assert row.key == "规划习惯"
    assert row.hit_count == 0
    assert row.last_used_at is None
    assert _age_label(row.created_at) == "今天"


def test_consolidate_merges_duplicate_keys_deterministically(db):
    """归槽保证一个 key 一行，但真撞上重复也要有确定归宿：
    建立时间取最早（祖先只会更老）、命中数与最后使用取最大（别把用量算没了）。"""
    from app.agent.memory import consolidate_memories

    a = _aged(db, _mem(db), days_old=200, hit=5, used_days_ago=30)
    b = _aged(db, _mem(db), days_old=50, hit=90, used_days_ago=1)

    consolidate_memories(db, "u1", _FakeLLM([("口味偏好", "用户爱吃辣", False)]))
    db.expire_all()
    row = db.query(TravelMemory).filter_by(user_id="u1").one()
    assert row.created_at == a.created_at      # 最早
    assert row.hit_count == 90                 # 最大
    assert row.last_used_at == b.last_used_at  # 最近


def test_consolidate_empty_llm_result_keeps_memories(db):
    """既有兜底不能被这次改动破坏：LLM 空结果时一条都不能删。"""
    from app.agent.memory import consolidate_memories

    _mem(db)
    out = consolidate_memories(db, "u1", _FakeLLM([]))
    assert out == {"before": 1, "after": 1}
    assert db.query(TravelMemory).filter_by(user_id="u1").count() == 1
