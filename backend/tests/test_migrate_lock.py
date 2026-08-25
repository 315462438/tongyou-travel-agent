"""启动迁移不许和在途请求抢锁（2026-08-14 线上事故的回归测试）。

事故：`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` **即使列早已存在也要拿
AccessExclusiveLock**，而 migrate.py 有 40+ 条全在一个事务里。每次重启都会与正在跑的
那一轮抢锁，PG 判定死锁后杀掉的是**用户那一轮**——用户侧表现是「思考停在第 1 步不动」，
因为后台任务已经死了，前端只能等 30 分钟的 `turn_stale_min` 兜底。

当天连炸三次（16:19 / 16:22 / 17:30），受害的都是 `SELECT travel_conversation`。

修法两条：
1. schema 已是最新时**一条 DDL 都不发**（绝大多数重启走这条路）
2. 真要跑 DDL 时设 `lock_timeout`——**迁移必须是让路的一方**：它可以下次启动再来，
   用户那一轮跑了几分钟又烧了 LLM 调用，被杀是纯损失。
"""

import re

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db.migrate import (
    _DDL_LOCK_TIMEOUT,
    _EXPECTED_INDEXES,
    migrate_and_bootstrap,
    pending_schema_changes,
)
from app.db.models import Base, TravelUser


@pytest.fixture()
def engine():
    """模拟**已经迁移过一次**的库——线上每次重启面对的就是这个状态。

    注意 `create_all` 只建模型声明的东西，手写索引要另外建；
    少了这一步，判定会正确地报「缺索引」，那是新库的正常情形、不是本测试要测的。
    """
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text("CREATE INDEX ix_conv_user ON travel_conversation (user_id)"))
        conn.execute(text("CREATE INDEX ix_mem_user ON travel_memory (user_id)"))
        conn.execute(text("CREATE INDEX ix_mem_key ON travel_memory (key)"))
        conn.execute(text("CREATE INDEX ix_conv_dest ON travel_conversation (destination)"))
    return eng


# ---------- 「无需 DDL」的判定 ----------

def test_migrated_schema_has_nothing_pending(engine):
    """迁移过一次之后模型与库一致——这就是线上每次重启的常态，必须一条 DDL 都不发。"""
    assert pending_schema_changes(engine) == []


def test_brand_new_db_still_reports_the_handwritten_indexes():
    """全新库（只跑过 create_all）要报缺索引，否则那几个索引永远建不上。"""
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    assert "index:ix_conv_user" in pending_schema_changes(eng)


def test_missing_column_is_detected(engine):
    """判据从 Base.metadata 推导，不维护平行清单：模型加了列就一定被发现。"""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE travel_user DROP COLUMN bio"))
    assert "travel_user.bio" in pending_schema_changes(engine)


def test_missing_table_is_detected(engine):
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE travel_memory"))
    assert "table:travel_memory" in pending_schema_changes(engine)


def test_missing_handwritten_index_is_detected(engine):
    """手写索引不在模型里，靠 _EXPECTED_INDEXES 登记——漏登记就会被静默跳过。"""
    assert "index:ix_conv_user" not in pending_schema_changes(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX ix_conv_user"))
    assert "index:ix_conv_user" in pending_schema_changes(engine)


# ---------- 防「加了索引忘了登记」 ----------

def test_every_handwritten_index_is_registered():
    """扫 migrate.py 源码：每条 `CREATE INDEX IF NOT EXISTS` 都要在 _EXPECTED_INDEXES 里。

    漏一条的后果很隐蔽：schema 判定会认为「已是最新」→ 整块 DDL 被跳过 →
    那个索引**永远建不上**，而且没有任何报错。
    """
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "app" / "db" / "migrate.py"
    found = set(re.findall(r"CREATE INDEX IF NOT EXISTS (\w+)", src.read_text(encoding="utf-8")))
    registered = {idx for _, idx in _EXPECTED_INDEXES}
    assert found <= registered, f"这些索引没登记进 _EXPECTED_INDEXES：{sorted(found - registered)}"
    assert registered <= found, f"_EXPECTED_INDEXES 里有已删除的条目：{sorted(registered - found)}"


# ---------- 迁移本身 ----------

def test_migration_still_bootstraps_admin_when_schema_is_current(engine, monkeypatch):
    """跳过 DDL 不能把 admin 引导一起跳掉——那会让全新部署没有管理员。"""
    monkeypatch.setattr("app.db.migrate.settings.admin_username", "admin")
    monkeypatch.setattr("app.db.migrate.settings.admin_password", "pw")

    from contextlib import contextmanager

    session = Session(engine)

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr("app.db.session.SessionLocal", lambda: session)
    monkeypatch.setattr("app.db.session.get_session", fake_session, raising=False)

    assert pending_schema_changes(engine) == []      # 前提：确实走跳过分支
    migrate_and_bootstrap(engine)
    assert session.query(TravelUser).filter(TravelUser.is_admin.is_(True)).first() is not None


def test_bootstrap_refuses_to_create_admin_without_a_configured_password(engine, monkeypatch):
    """没配 ADMIN_PASSWORD 时必须**拒绝启动**，不能悄悄用一个默认口令建管理员。

    仓库是公开的：默认口令写在代码里 = 所有照此部署的站点共用同一个管理员密码。
    而 `_must_change_password` 只是登录后的提示，token 照发、`/api/admin/*` 照开，
    拦不住任何人。所以这一格只能失败关闭。
    """
    monkeypatch.setattr("app.db.migrate.settings.admin_username", "admin")
    monkeypatch.setattr("app.db.migrate.settings.admin_password", "")

    from contextlib import contextmanager

    session = Session(engine)

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr("app.db.session.SessionLocal", lambda: session)
    monkeypatch.setattr("app.db.session.get_session", fake_session, raising=False)

    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        migrate_and_bootstrap(engine)
    assert session.query(TravelUser).filter(TravelUser.is_admin.is_(True)).first() is None


def test_config_ships_no_usable_admin_password():
    """护栏：默认值必须是空的。写回任何非空字面量都会让上面那条失败关闭形同虚设。"""
    from app.config import Settings

    assert Settings.model_fields["admin_password"].default == "", (
        "config.py 不得给 admin_password 任何默认口令——仓库公开，默认值即通用密码"
    )


def test_ddl_transaction_declares_a_lock_timeout():
    """真要跑 DDL 时必须先设 lock_timeout，否则又会把用户那一轮拖进死锁。"""
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "app" / "db" / "migrate.py"
           ).read_text(encoding="utf-8")
    assert "SET LOCAL lock_timeout" in src
    assert _DDL_LOCK_TIMEOUT.endswith("s")


def test_index_registry_matches_reality_after_create_all(engine):
    """登记表里的表名不能写错——写错了这条索引永远被判成「缺失」，每次重启都跑一遍 DDL。"""
    tables = set(inspect(engine).get_table_names())
    for tbl, idx in _EXPECTED_INDEXES:
        assert tbl in tables, f"{idx} 登记的表 {tbl} 不存在"
