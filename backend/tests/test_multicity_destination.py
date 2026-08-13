"""多城目的地消费点全量修复（2026-08-01）。

计划：docs/task_plans/多城目的地消费点全量修复-2026-08-01.md
`Preference.destination` 多城时是顿号连接的整串，凡把它当**单个城市名**用的地方都会错。
一天内已因此连修三处（历史检索、坐标定位、携程相关性），本文件锁住扫描出的其余五处
+ 携程选城排序。全部离线。
"""

import asyncio

from app.agent.orchestrator import (
    _build_queries, _dest_in_page, _is_relevant, decide_revision, rank_cities_by_stay_intent,
)
from app.agent.site_router import route_for_intent
from app.schemas.chat_schema import Preference

MULTI = "吉隆坡、仙本那、亚庇"


def _pref(dest=MULTI, **kw):
    return Preference(destination=dest, **kw)


# ---------- P0：多城的高德数据不能整条丢 ----------

def test_collect_amap_queries_each_city(monkeypatch):
    """线上实测：build_amap_source('武汉、开封、洛阳') → None（天气+景点全丢，且静默）。
    现在逐城取，任一城成功即有数据。"""
    from app.agent import orchestrator as orch

    asked = []

    async def fake_build(city):
        asked.append(city)
        return {"title": f"高德：{city}", "site": "amap"} if city != "仙本那" else None

    monkeypatch.setattr("app.tools.amap.build_amap_source", fake_build)
    monkeypatch.setattr("app.tools.amap.enabled", lambda: True)
    monkeypatch.setattr(orch, "_progress", lambda *a, **k: None)

    out = asyncio.run(orch._collect_amap("c1", _pref()))
    assert asked == ["吉隆坡", "仙本那", "亚庇"]
    assert [s["title"] for s in out] == ["高德：吉隆坡", "高德：亚庇"]  # 单城失败不影响其余


def test_collect_amap_single_city_unchanged(monkeypatch):
    from app.agent import orchestrator as orch

    async def fake_build(city):
        return {"title": f"高德：{city}", "site": "amap"}

    monkeypatch.setattr("app.tools.amap.build_amap_source", fake_build)
    monkeypatch.setattr("app.tools.amap.enabled", lambda: True)
    monkeypatch.setattr(orch, "_progress", lambda *a, **k: None)
    assert len(asyncio.run(orch._collect_amap("c1", _pref("成都")))) == 1


# ---------- 搜索词 / 相关性 / 复用判定 / 站点路由 ----------

def test_build_queries_splits_multi_city():
    """整串「吉隆坡、仙本那、亚庇 7天旅游攻略」当关键词，搜索引擎只给泛泛结果。"""
    qs = _build_queries(_pref(days=7), intent="general")
    assert all("、" not in q for q in qs)
    assert any(q.startswith("吉隆坡") for q in qs) and any(q.startswith("仙本那") for q in qs)

    single = _build_queries(_pref("成都", days=3), intent="general")
    assert single[0].startswith("成都") and len(single) == 2  # 单城行为不变


def test_build_queries_hotel_multi_city():
    qs = _build_queries(_pref(), intent="hotel")
    assert all("酒店" in q and "、" not in q for q in qs)


def test_is_relevant_matches_any_city():
    assert _is_relevant(MULTI, "亚庇自由行攻略", "亚庇必去景点")
    assert _dest_in_page(MULTI, "吉隆坡酒店", "吉隆坡住宿推荐")
    # 无关内容仍要靠旅行关键词兜底，而不是目的地命中
    assert not _is_relevant(MULTI, "黄金价格走势", "现货黄金今日行情分析")


def test_decide_revision_ignores_city_order():
    """模型下一轮把「吉隆坡、仙本那」写成「仙本那、吉隆坡」不应判成换了目的地。"""
    srcs = [{"title": "小红书｜攻略", "site": "xhs"}]
    assert decide_revision(srcs, "吉隆坡、仙本那", "仙本那、吉隆坡", "route")
    assert not decide_revision(srcs, "吉隆坡、仙本那", "大理、丽江", "route")


def test_route_for_intent_uses_first_city():
    """整串查不到城市 ID → route 意图直接不路由（hotel 另有逐城分支）。"""
    assert route_for_intent("hotel", "成都、重庆") is not None
    assert route_for_intent("hotel", "成都") is not None
    assert route_for_intent("hotel", "") is None


# ---------- 携程选城：住宿意图优先 ----------

def test_rank_cities_by_stay_intent_prioritises_named_city():
    """用户原话「主要想在仙本那住度假酒店」→ 仙本那必须排进前 N，
    而不是被目的地串的字面顺序挤掉。"""
    cities = ["吉隆坡", "仙本那", "亚庇"]
    text = "10.1-10.7 国庆，我想去马来西亚游玩，吉隆坡，仙本那，亚庇，主要想在仙本那住度假酒店，跳岛等等"
    assert rank_cities_by_stay_intent(cities, text, _pref())[0] == "仙本那"


def test_rank_cities_reads_special_requirements():
    cities = ["吉隆坡", "仙本那", "亚庇"]
    pref = _pref(special_requirements=["亚庇住海景酒店两晚"])
    assert rank_cities_by_stay_intent(cities, "", pref)[0] == "亚庇"


def test_rank_cities_stable_when_no_stay_intent():
    """没有住宿意图线索时保持原序（稳定排序，行为不变）。"""
    cities = ["吉隆坡", "仙本那", "亚庇"]
    assert rank_cities_by_stay_intent(cities, "帮我规划一下行程", _pref()) == cities
    assert rank_cities_by_stay_intent(cities, "", _pref()) == cities


def test_rank_cities_ignores_far_away_stay_word():
    """住宿词离城市名太远不算数，避免整段话里出现「酒店」就把第一个城市顶上去。"""
    cities = ["吉隆坡", "仙本那"]
    text = "吉隆坡玩两天然后去仙本那，另外顺便问一下当地的酒店大概什么价位"
    assert rank_cities_by_stay_intent(cities, text, _pref()) == cities
