"""Phase 15 迁移与引导（启动时幂等执行）

- 给存量表加 user_id 列（Postgres ADD COLUMN IF NOT EXISTS）；
- travel_site_login 改为 (user_id, site) 复合主键：数据是临时登录时间戳，直接重建；
- 引导 admin 账号；把无主的历史会话/记忆归到 admin。
"""

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.auth import hash_password
from app.config import settings
from app.db.models import Base, TravelUser, _uuid

logger = logging.getLogger(__name__)


# 手写的索引（不由模型声明）。新增 `CREATE INDEX IF NOT EXISTS` 必须登记在这里，
# 否则「schema 已是最新」的判定会漏掉它、整块 DDL 被跳过 —— 有测试钉住这条
# （`test_migrate_lock.py::test_every_handwritten_index_is_registered` 扫本文件源码核对）。
_EXPECTED_INDEXES: tuple[tuple[str, str], ...] = (
    ("travel_conversation", "ix_conv_user"),
    ("travel_memory", "ix_mem_user"),
    ("travel_memory", "ix_mem_key"),
    ("travel_conversation", "ix_conv_dest"),
)

# DDL 抢不到锁时等多久就放弃。**迁移必须是让路的一方**：它可以下次启动再来，
# 用户那一轮跑了几分钟、还烧了 LLM 调用，被杀掉是纯损失。
_DDL_LOCK_TIMEOUT = "5s"


def pending_schema_changes(engine: Engine) -> list[str]:
    """列出「模型里有、库里还没有」的表/列/索引。空 = 这次启动一条 DDL 都不用跑。

    2026-08-14 线上事故：`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` **即使列早已存在
    也要拿 AccessExclusiveLock**，而这里有 40+ 条、全在一个事务里。于是每次重启都会
    和正在跑的那一轮抢锁 —— PG 判定死锁，杀掉的是**用户那一轮**（当天连炸三次，
    用户侧表现是「思考卡在第 1 步不动」，因为后台任务已经死了）。

    判据从 `Base.metadata` 推导，不维护平行清单：migrate.py 里每条 ADD COLUMN 之所以
    存在，就是因为模型上有那一列。索引是手写的，另用 `_EXPECTED_INDEXES` 登记。
    """
    from sqlalchemy import inspect

    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    pending: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            pending.append(f"table:{table.name}")
            continue
        cols = {c["name"] for c in insp.get_columns(table.name)}
        pending += [f"{table.name}.{c.name}" for c in table.columns if c.name not in cols]
    for tbl, idx in _EXPECTED_INDEXES:
        if tbl in existing_tables and idx not in {i["name"] for i in insp.get_indexes(tbl)}:
            pending.append(f"index:{idx}")
    return pending


def migrate_and_bootstrap(engine: Engine) -> None:
    with engine.begin() as conn:
        # 站点登录表结构变了（加 user_id 进主键）→ 重建（临时数据可弃）
        conn.execute(text("DROP TABLE IF EXISTS travel_site_login"))

    Base.metadata.create_all(engine)  # 建新表（user/session/site_login）+ 补缺表

    pending = pending_schema_changes(engine)
    if not pending:
        # 绝大多数重启走这条路：一条 ALTER 都不发，也就不存在和在途请求抢锁
        logger.info("schema is up to date, skipping DDL")
        _bootstrap_admin_and_backfill(engine)
        return
    logger.info("applying schema changes (%d): %s", len(pending), pending[:12])

    with engine.begin() as conn:
        # 抢不到锁就放弃这一轮迁移（下次启动重来），不要把用户那一轮拖进死锁
        conn.execute(text(f"SET LOCAL lock_timeout = '{_DDL_LOCK_TIMEOUT}'"))
        # 存量表补 user_id 列
        conn.execute(text("ALTER TABLE travel_conversation ADD COLUMN IF NOT EXISTS user_id VARCHAR(32)"))
        conn.execute(text("ALTER TABLE travel_memory ADD COLUMN IF NOT EXISTS user_id VARCHAR(32)"))
        # Phase 68：单页分析任务归属（此前 /api/agent/run 无鉴权，补上后按 user_id 校验）
        conn.execute(text("ALTER TABLE travel_task ADD COLUMN IF NOT EXISTS user_id VARCHAR(32)"))
        # Phase 17：三元组归槽（key）+ 明确表达标记（explicit）
        conn.execute(text("ALTER TABLE travel_memory ADD COLUMN IF NOT EXISTS key VARCHAR(64)"))
        conn.execute(text("ALTER TABLE travel_memory ADD COLUMN IF NOT EXISTS explicit BOOLEAN DEFAULT FALSE"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_conv_user ON travel_conversation (user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_mem_user ON travel_memory (user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_mem_key ON travel_memory (key)"))
        # Phase 45：记忆访问频率（重要性评分补第四根柱子）
        conn.execute(text("ALTER TABLE travel_memory ADD COLUMN IF NOT EXISTS hit_count INTEGER DEFAULT 0"))
        # Phase 57：睡眠整合门控时间
        conn.execute(text("ALTER TABLE travel_user ADD COLUMN IF NOT EXISTS memory_consolidated_at TIMESTAMP"))
        # 2026-07-31：退役「当前行程」(trip_state) 记忆槽——时点事实伪装成长期偏好，
        # 会把旧行程的日期/预算泄漏进新行程（线上真实 bug）。跨会话指代消解改由
        # memory.recent_plan_hint 确定性提供。存量行清掉（幂等）。
        conn.execute(text("DELETE FROM travel_memory WHERE type = 'trip_state'"))
        # 2026-07-31 跨会话检索索引：会话级 destination + 首条攻略消息 id
        conn.execute(text("ALTER TABLE travel_conversation ADD COLUMN IF NOT EXISTS destination VARCHAR(64)"))
        conn.execute(text(
            "ALTER TABLE travel_conversation ADD COLUMN IF NOT EXISTS guide_message_id VARCHAR(32)"
        ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_conv_dest ON travel_conversation (destination)"))
        # 存量回填：每个会话取**最早**一条带 sources 的 assistant 消息（那就是首版攻略）。
        # 只填空值，幂等；meta_json 全部由 json.dumps 写出，但仍加 '{%' 前缀防脏数据炸 cast。
        conn.execute(text("""
            UPDATE travel_conversation c
               SET destination = sub.dest, guide_message_id = sub.mid
              FROM (
                    SELECT DISTINCT ON (m.conversation_id)
                           m.conversation_id AS cid, m.id AS mid,
                           (m.meta_json::json -> 'preference' ->> 'destination') AS dest
                      FROM travel_message m
                     WHERE m.role = 'assistant'
                       AND m.meta_json LIKE '{%'
                       AND m.meta_json LIKE '%"sources"%'
                     ORDER BY m.conversation_id, m.created_at ASC
                   ) sub
             WHERE c.id = sub.cid
               AND sub.dest IS NOT NULL AND sub.dest <> ''
               AND (c.destination IS NULL OR c.destination = '')
        """))
        # Phase 27b：zip 多文件技能包，旧的纯文本单文件行 files_json 留空即可（见模型注释）
        conn.execute(text("ALTER TABLE travel_user_skill ADD COLUMN IF NOT EXISTS files_json TEXT"))
        # Phase 30：历史压缩（早期轮次折叠成结构化摘要）
        conn.execute(text("ALTER TABLE travel_conversation ADD COLUMN IF NOT EXISTS history_summary TEXT"))
        conn.execute(text(
            "ALTER TABLE travel_conversation ADD COLUMN IF NOT EXISTS history_summary_count INTEGER DEFAULT 0"
        ))
        # Phase 35b：邀请确认流（存量成员默认已接受）
        conn.execute(text(
            "ALTER TABLE travel_trip_member ADD COLUMN IF NOT EXISTS status VARCHAR(16) DEFAULT 'accepted'"
        ))
        # Phase 36：行程预算/日期/来源联动 + 条目卡片字段
        for ddl in (
            "ALTER TABLE travel_trip ADD COLUMN IF NOT EXISTS budget FLOAT",
            "ALTER TABLE travel_trip ADD COLUMN IF NOT EXISTS start_date VARCHAR(10)",
            "ALTER TABLE travel_trip ADD COLUMN IF NOT EXISTS source_conversation_id VARCHAR(32)",
            "ALTER TABLE travel_trip ADD COLUMN IF NOT EXISTS source_message_id VARCHAR(32)",
            "ALTER TABLE travel_trip_stop ADD COLUMN IF NOT EXISTS start_time VARCHAR(5)",
            "ALTER TABLE travel_trip_stop ADD COLUMN IF NOT EXISTS stay_min INTEGER",
            "ALTER TABLE travel_trip_stop ADD COLUMN IF NOT EXISTS transport VARCHAR(16)",
            "ALTER TABLE travel_trip_stop ADD COLUMN IF NOT EXISTS ticket_price FLOAT",
            "ALTER TABLE travel_trip_stop ADD COLUMN IF NOT EXISTS tags VARCHAR(128)",
            # Phase 38：presence
            "ALTER TABLE travel_trip_member ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP",
            "ALTER TABLE travel_trip_member ADD COLUMN IF NOT EXISTS editing_day INTEGER",
            # Phase 42：分享链接
            "ALTER TABLE travel_trip ADD COLUMN IF NOT EXISTS invite_token VARCHAR(32)",
            # Phase 51：结构化导入——计划预算按类别拆分
            "ALTER TABLE travel_trip ADD COLUMN IF NOT EXISTS budget_breakdown_json TEXT",
            # Phase 54：结构化逐日性质/过夜城市 + 攻略酒店候选
            "ALTER TABLE travel_trip ADD COLUMN IF NOT EXISTS day_plan_json TEXT",
            "ALTER TABLE travel_trip ADD COLUMN IF NOT EXISTS hotel_recommendations_json TEXT",
            # Phase 73：admin 在线状态。存量用户留 NULL（= 从未活跃），不回填伪造时间。
            # **必须 TIMESTAMPTZ**：服务器 TimeZone=Asia/Shanghai，往 naive TIMESTAMP 列写
            # aware UTC 值时，Postgres 会按会话时区折算成本地时间存进去；读回来又被当 UTC 解读，
            # 凭空多出 8 小时 → `now - last` 为负 → 所有人永远显示「在线」。见 pitfalls。
            "ALTER TABLE travel_user ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ",
            # Phase 81：个人主页与社交资料。新表由 Base.metadata.create_all 创建；存量用户表补列。
            "ALTER TABLE travel_user ADD COLUMN IF NOT EXISTS display_name VARCHAR(40)",
            "ALTER TABLE travel_user ADD COLUMN IF NOT EXISTS avatar_upload_id VARCHAR(32)",
            "ALTER TABLE travel_user ADD COLUMN IF NOT EXISTS bio VARCHAR(240)",
            "ALTER TABLE travel_user ADD COLUMN IF NOT EXISTS home_city VARCHAR(64)",
            "ALTER TABLE travel_user ADD COLUMN IF NOT EXISTS travel_styles_json TEXT",
            "ALTER TABLE travel_user ADD COLUMN IF NOT EXISTS profile_public BOOLEAN DEFAULT TRUE",
            # Phase 87：行李格「是谁勾的」。**表本身已由 create_all 建过**，加列必须显式写在
            # 这里——`create_all` 只补缺失的表，不给已存在的表加列（本次上线即中招：
            # 先部署了不带该列的版本，第二次部署时模型有了列、库里却没有）。
            "ALTER TABLE travel_trip_packing_state ADD COLUMN IF NOT EXISTS updated_by VARCHAR(32) DEFAULT ''",
            # Phase 87b：记账支持「花费日期」（补记昨天的账很常见）。同上，表已存在必须显式加列。
            "ALTER TABLE travel_trip_expense ADD COLUMN IF NOT EXISTS spent_at VARCHAR(10) DEFAULT ''",
            # Phase 91 surface 投影：压缩改为「追加遮蔽事件」而非覆盖会话字段。
            # 老规矩——表已存在，create_all 不会加列，必须显式写在这里。
            "ALTER TABLE travel_message ADD COLUMN IF NOT EXISTS surface_op VARCHAR(12) DEFAULT 'append'",
            "ALTER TABLE travel_message ADD COLUMN IF NOT EXISTS shadow_from_id VARCHAR(32)",
            "ALTER TABLE travel_message ADD COLUMN IF NOT EXISTS shadow_to_id VARCHAR(32)",
            # 已按 naive 建过列的部署（本次上线即中招）就地转换：Postgres 会按会话时区
            # 把 naive 值解读成本地时间再转 UTC，正好把之前存歪的值掰回来。
            """DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='travel_user' AND column_name='last_seen_at'
                             AND data_type='timestamp without time zone') THEN
                    ALTER TABLE travel_user
                        ALTER COLUMN last_seen_at TYPE TIMESTAMPTZ;
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name='travel_support_message' AND column_name='created_at'
                             AND data_type='timestamp without time zone') THEN
                    ALTER TABLE travel_support_message
                        ALTER COLUMN created_at TYPE TIMESTAMPTZ,
                        ALTER COLUMN read_at TYPE TIMESTAMPTZ;
                END IF;
            END $$;""",
        ):
            conn.execute(text(ddl))

    _bootstrap_admin_and_backfill(engine)


def _bootstrap_admin_and_backfill(engine: Engine) -> None:
    """引导 admin，并把无主历史归给它。

    只写数据不改结构（行级锁），所以和 DDL 分开、无论有没有 schema 变更都要跑：
    新用户注册后这些回填仍需保证「不留无主行」。
    """
    from app.db.session import get_session

    with get_session() as db:
        admin = db.query(TravelUser).filter(TravelUser.is_admin.is_(True)).first()
        if admin is None:
            admin = TravelUser(
                id=_uuid(), username=settings.admin_username,
                password_hash=hash_password(settings.admin_password), is_admin=True,
            )
            db.add(admin)
            db.commit()
            logger.info("bootstrapped admin user '%s'", settings.admin_username)
        admin_id = admin.id

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE travel_conversation SET user_id=:uid WHERE user_id IS NULL"),
            {"uid": admin_id},
        )
        conn.execute(
            text("UPDATE travel_memory SET user_id=:uid WHERE user_id IS NULL"),
            {"uid": admin_id},
        )
        # Phase 68：存量单页分析任务（无鉴权时期产生的）一律归 admin，避免变成人人可读的孤儿
        conn.execute(
            text("UPDATE travel_task SET user_id=:uid WHERE user_id IS NULL"),
            {"uid": admin_id},
        )
