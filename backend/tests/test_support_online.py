"""Phase 73：在线状态 + 客服会话。

sqlite 内存库，直接调路由函数，全部离线。
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import support_api
from app.api.deps import is_online, touch_last_seen
from app.config import settings
from app.db.models import Base, TravelSupportMessage, TravelUser


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _user(db, name="alice", admin=False):
    u = TravelUser(username=name, password_hash="x", is_admin=admin)
    db.add(u)
    db.commit()
    return u


def _send(content):
    return support_api.SendSupportMessage(content=content)


# ---------- 在线判定 ----------

def test_online_within_window():
    now = datetime.now(timezone.utc)
    assert is_online(now - timedelta(seconds=settings.online_window_s - 5), now) is True


def test_offline_outside_window():
    now = datetime.now(timezone.utc)
    assert is_online(now - timedelta(seconds=settings.online_window_s + 5), now) is False


def test_never_seen_is_not_online():
    """存量用户 last_seen_at 为 NULL —— 不能当成在线，也不能当成刚活跃。"""
    assert is_online(None) is False


def test_naive_datetime_from_db_does_not_explode():
    """Postgres TIMESTAMP 取回来是 naive，与 aware 相减会 TypeError 打挂鉴权。"""
    naive = datetime.now(timezone.utc).replace(tzinfo=None)
    assert is_online(naive) is True


# ---------- last_seen 节流 ----------

def test_touch_sets_last_seen_when_never_seen(db):
    u = _user(db)
    assert u.last_seen_at is None
    touch_last_seen(db, u)
    assert u.last_seen_at is not None


def test_touch_is_throttled(db):
    """鉴权是最热路径：距上次不足节流窗口不得再写库。"""
    u = _user(db)
    touch_last_seen(db, u)
    first = u.last_seen_at
    touch_last_seen(db, u)
    assert u.last_seen_at == first, "节流失效会造成每请求一次 UPDATE 的写放大"


def test_touch_writes_again_after_throttle_window(db):
    u = _user(db)
    u.last_seen_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.online_touch_throttle_s + 5)
    db.commit()
    stale = u.last_seen_at
    touch_last_seen(db, u)
    assert u.last_seen_at > stale


# ---------- 客服会话 ----------

def test_user_sends_and_admin_sees_unread(db):
    u = _user(db)
    _user(db, "root", admin=True)
    support_api.send_message(_send("攻略生成卡住了"), db=db, user=u)

    threads = support_api.list_threads(db=db)
    assert threads["unread_total"] == 1
    t = threads["threads"][0]
    assert t["username"] == "alice" and t["unread"] == 1
    assert t["last_sender"] == "user" and "卡住" in t["last_excerpt"]


def test_admin_reading_marks_user_messages_read(db):
    u = _user(db)
    support_api.send_message(_send("问题一"), db=db, user=u)
    support_api.thread_messages(u.id, db=db)  # 读取即已读
    assert support_api.list_threads(db=db)["unread_total"] == 0


def test_admin_reply_creates_user_unread(db):
    u = _user(db)
    support_api.send_message(_send("问题一"), db=db, user=u)
    support_api.reply(u.id, _send("已收到，正在看"), db=db)
    assert support_api.my_unread(db=db, user=u)["unread"] == 1


def test_user_reading_marks_admin_reply_read(db):
    u = _user(db)
    support_api.reply(u.id, _send("主动关怀"), db=db)
    msgs = support_api.my_messages(db=db, user=u)["messages"]
    assert len(msgs) == 1 and msgs[0]["sender"] == "admin"
    assert support_api.my_unread(db=db, user=u)["unread"] == 0


def test_unread_is_symmetric_and_does_not_count_own_messages(db):
    """自己发的消息永远不算自己的未读——两个方向都要成立。"""
    u = _user(db)
    support_api.send_message(_send("我的问题"), db=db, user=u)
    assert support_api.my_unread(db=db, user=u)["unread"] == 0
    support_api.thread_messages(u.id, db=db)
    support_api.reply(u.id, _send("回复"), db=db)
    assert support_api.list_threads(db=db)["unread_total"] == 0


def test_thread_is_isolated_per_user(db):
    a, b = _user(db, "alice"), _user(db, "bob")
    support_api.send_message(_send("alice 的问题"), db=db, user=a)
    support_api.send_message(_send("bob 的问题"), db=db, user=b)
    a_msgs = support_api.my_messages(db=db, user=a)["messages"]
    assert len(a_msgs) == 1 and a_msgs[0]["content"] == "alice 的问题"


def test_reply_to_unknown_user_404(db):
    with pytest.raises(HTTPException) as e:
        support_api.reply("nope", _send("hi"), db=db)
    assert e.value.status_code == 404


def test_empty_message_rejected(db):
    u = _user(db)
    with pytest.raises(HTTPException) as e:
        support_api.send_message(_send("   "), db=db, user=u)
    assert e.value.status_code == 400


def test_long_message_truncated(db):
    u = _user(db)
    out = support_api.send_message(_send("x" * (settings.support_message_max_chars + 500)),
                                   db=db, user=u)
    assert len(out["content"]) == settings.support_message_max_chars


def test_threads_empty_when_no_messages(db):
    _user(db)
    assert support_api.list_threads(db=db) == {"threads": [], "unread_total": 0}


def test_thread_carries_online_flag(db):
    u = _user(db)
    u.last_seen_at = datetime.now(timezone.utc)
    db.add(TravelSupportMessage(user_id=u.id, sender="user", content="在线时发的"))
    db.commit()
    assert support_api.list_threads(db=db)["threads"][0]["online"] is True


# ---------- 时区：本次上线真实翻车的形态 ----------

def test_new_time_columns_are_timezone_aware():
    """**必须 TIMESTAMPTZ**。

    线上翻车实录（2026-08-04）：服务器 TimeZone=Asia/Shanghai，列是
    `timestamp without time zone`。往里写 aware UTC 值时 Postgres 按会话时区折算成
    本地时间落库（07:03Z → 存 15:03），读回来是 naive 又被当 UTC 解读 →
    `now - last` 为负 → `<= 300` 成立 → **所有人永远显示在线**，而且离线时间越久越像刚活跃。

    sqlite 单测抓不到（不做时区折算），所以这里直接锁列类型。
    """
    from app.db.models import TravelSupportMessage, TravelUser

    assert TravelUser.__table__.c.last_seen_at.type.timezone is True
    assert TravelSupportMessage.__table__.c.created_at.type.timezone is True
    assert TravelSupportMessage.__table__.c.read_at.type.timezone is True


def test_future_timestamp_is_not_reported_as_online():
    """时区折算一旦出错，last_seen 会跑到未来。未来时间**不该**被当成在线。

    这是上面那个 bug 的行为兜底：即使又有哪列被建成 naive，也不至于全员常亮。
    """
    now = datetime.now(timezone.utc)
    assert is_online(now + timedelta(hours=8), now) is False


def test_small_clock_skew_still_counts_as_online():
    """但几秒级的时钟偏差是正常的，不能误判成离线。"""
    now = datetime.now(timezone.utc)
    assert is_online(now + timedelta(seconds=20), now) is True
