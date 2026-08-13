"""跨会话来源复用（2026-07-31）。

计划：docs/task_plans/跨会话历史检索索引-2026-07-31.md
小红书详情逐篇串行 19-20s×5 ≈ 首轮耗时 85%；同目的地近期会话的正文可直接拿来用。
实测约束：图片 URL 有效期 24h（20h→200 / 39h→403）、天气必重取、携程绝不复用。全部离线。
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.orchestrator import reuse_recent_xhs_sources, wants_fresh_search
from app.config import settings
from app.db.models import Base, TravelConversation, TravelMessage
from app.schemas.chat_schema import Preference


@pytest.fixture()
def db(monkeypatch):
    from app.agent import orchestrator as orch

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        class _Ctx:
            def __enter__(self):
                return session

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(orch, "get_session", lambda: _Ctx())
        yield session


def _seed(db, destination="成都", hours_ago=1, sites=("xhs", "xhs", "amap", "ctrip")):
    ts = datetime.now() - timedelta(hours=hours_ago)  # 库里存的是本地 naive（见 age_delta）
    # guide_message_id 在构造时就给：会话行的 updated_at 有 onupdate，事后再改会把它刷新，
    # 而实现读的是**消息** created_at（会话最后活跃 ≠ 攻略抓取时间）。
    c = TravelConversation(id="c-old", user_id="u1", title="旧对话", destination=destination,
                           guide_message_id="m-old", created_at=ts, updated_at=ts)
    db.add(c)
    db.flush()
    sources = []
    for i, site in enumerate(sites):
        sources.append({
            "title": {"xhs": f"小红书｜成都攻略{i}", "amap": "高德地图实时数据：成都天气与景点",
                      "ctrip": "携程｜成都酒店"}[site],
            "url": f"https://x/{i}", "summary": "正文" * 50, "site": site,
            "images": [{"name": f"图{i}", "url": f"https://sns-webpic-qc.xhscdn.com/{i}"}],
        })
    m = TravelMessage(id="m-old", conversation_id="c-old", role="assistant",
                      content="攻略正文" * 40, created_at=ts,
                      meta_json=json.dumps({"sources": sources,
                                            "preference": {"destination": destination}}))
    db.add(m)
    db.commit()
    return c


def _pref(destination="成都", **kw):
    return Preference(destination=destination, **kw)


# ---------- 命中与来源筛选 ----------

def test_reuses_only_xhs_sources(db):
    _seed(db)
    sources, note = reuse_recent_xhs_sources("c-new", _pref(), "u1")
    assert [s["site"] for s in sources] == ["xhs", "xhs"]  # 天气重取、携程绝不复用
    assert "复用了今天查过的 2 篇小红书资料" in note
    assert "重新搜索" in note  # 必须给用户一个出口


def test_images_kept_inside_window(db):
    _seed(db, hours_ago=settings.xhs_reuse_image_max_hours - 2)
    sources, note = reuse_recent_xhs_sources("c-new", _pref(), "u1")
    assert all(s["images"] for s in sources)
    assert "配图已过期" not in note


def test_images_dropped_when_expired(db):
    """图片 URL 24h 失效——超窗口必须清空，否则整版破图。"""
    _seed(db, hours_ago=settings.xhs_reuse_image_max_hours + 5)
    sources, note = reuse_recent_xhs_sources("c-new", _pref(), "u1")
    assert sources and all(s["images"] == [] for s in sources)
    assert "配图已过期" in note


def test_text_ttl_expires(db):
    _seed(db, hours_ago=24 * (settings.xhs_reuse_max_days + 1))
    assert reuse_recent_xhs_sources("c-new", _pref(), "u1") == ([], "")


# ---------- 不该复用的情形 ----------

def test_multi_city_overlap_hits(db):
    _seed(db, destination="武汉、开封")
    sources, _ = reuse_recent_xhs_sources("c-new", _pref("开封"), "u1")
    assert sources


def test_different_destination_misses(db):
    _seed(db, destination="成都")
    assert reuse_recent_xhs_sources("c-new", _pref("厦门"), "u1") == ([], "")


def test_waypoint_trip_never_reuses(db):
    """沿途中转的语料是「A到B沿途」，与终点城市攻略不是一回事。"""
    _seed(db)
    pref = _pref("成都", origin="合肥", waypoint_trip=True)
    assert reuse_recent_xhs_sources("c-new", pref, "u1") == ([], "")


def test_user_can_force_fresh_search(db):
    _seed(db)
    assert reuse_recent_xhs_sources("c-new", _pref(), "u1", "重新搜索一下") == ([], "")
    assert reuse_recent_xhs_sources("c-new", _pref(), "u1", "帮我重新查最新的") == ([], "")


def test_same_conversation_excluded(db):
    _seed(db)
    assert reuse_recent_xhs_sources("c-old", _pref(), "u1") == ([], "")


def test_other_user_excluded(db):
    _seed(db)
    assert reuse_recent_xhs_sources("c-new", _pref(), "u2") == ([], "")


def test_disabled_switch(db, monkeypatch):
    _seed(db)
    monkeypatch.setattr(settings, "xhs_reuse_enabled", False)
    assert reuse_recent_xhs_sources("c-new", _pref(), "u1") == ([], "")


def test_no_xhs_in_old_sources(db):
    _seed(db, sites=("amap", "ctrip"))
    assert reuse_recent_xhs_sources("c-new", _pref(), "u1") == ([], "")


# ---------- 关键词判定 ----------

def test_wants_fresh_search_keywords():
    for t in ("重新搜索", "帮我重新查一下", "重搜", "要最新资料", "再查一遍"):
        assert wants_fresh_search(t), t
    for t in ("帮我规划成都3天", "重新排一下第三天的顺序", ""):
        assert not wants_fresh_search(t), t


# ---------- 多城站点抓取的相关性判定（2026-08-01 线上事故） ----------

def test_dest_in_page_matches_any_city_of_multi_city_trip():
    """携程逐城抓取时页面只讲一个城市，拿整串「吉隆坡、仙本那、亚庇」比对必然判死，
    还被文案说成「可能被风控拦截」——用户以为携程封控，其实是我们自己判错。"""
    from app.agent.orchestrator import _dest_in_page

    page = "吉隆坡酒店预订_吉隆坡住宿推荐"
    body = "吉隆坡希尔顿、吉隆坡君悦……"
    assert _dest_in_page("吉隆坡、仙本那、亚庇", page, body)
    assert _dest_in_page("仙本那、亚庇", "亚庇度假村", "亚庇海边酒店")
    # 单城行为不变
    assert _dest_in_page("成都", "成都酒店", "成都春熙路")
    assert _dest_in_page("成都市", "成都酒店", "成都春熙路")
    # 完全不相干的城市仍要判死（防止携程按 profile 记忆展示别的城市）
    assert not _dest_in_page("吉隆坡、仙本那", "上海酒店预订", "上海外滩")


def test_site_relevance_message_does_not_claim_risk_control():
    """没有证据就不能说站点风控。"""
    import inspect

    from app.agent import site_router

    src = inspect.getsource(site_router.collect_via_site)
    assert "风控拦截" not in src
    assert "不是目标城市的内容" in src
