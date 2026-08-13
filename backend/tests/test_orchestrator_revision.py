"""多轮修改判定（decide_revision）单测。

背景 bug：先查酒店（来源只有携程），再说「规划一下行程」时复用了酒店来源，
没有走小红书路由和搜索，导致攻略只引用携程。
"""

import asyncio

from app.agent.orchestrator import (
    _dest_in_page,
    decide_revision,
    merge_refreshed_image_sources,
    wants_image_refresh,
)

CTRIP = {"site": "ctrip", "title": "携程酒店", "url": "https://hotels.ctrip.com/x"}
GUIDE = {"title": "成都3日游攻略", "url": "https://example.com/guide"}


def test_guide_revision_reuses_guide_sources():
    assert decide_revision([GUIDE], "成都", "成都", "route") is True
    assert decide_revision([GUIDE], "成都", "成都", "general") is True


def test_route_after_hotel_must_research():
    # 用户反馈的 bug 场景：只有携程酒店来源时要行程规划 → 不能复用
    assert decide_revision([CTRIP], "成都", "成都", "route") is False
    assert decide_revision([CTRIP], "成都", "成都", "general") is False


def test_hotel_after_guide_must_research():
    assert decide_revision([GUIDE], "成都", "成都", "hotel") is False
    assert decide_revision([CTRIP], "成都", "成都", "hotel") is True
    assert decide_revision([CTRIP, GUIDE], "成都", "成都", "hotel") is True


def test_destination_change_never_reuses():
    assert decide_revision([GUIDE, CTRIP], "成都", "重庆", "route") is False
    assert decide_revision([GUIDE], "", "成都", "route") is False  # 旧目的地未知
    assert decide_revision([GUIDE], "成都", "", "route") is False  # 新目的地未知


def test_no_existing_sources():
    assert decide_revision([], "", "成都", "route") is False


def test_image_refresh_intent_is_explicit():
    assert wants_image_refresh("补一下各个行程中的图片") is True
    assert wants_image_refresh("给我做成图文版，再多放几张配图") is True
    assert wants_image_refresh("推荐几个拍照机位") is False


def test_refreshed_images_merge_into_old_sources_without_duplicates():
    existing = [
        {"site": "xhs", "title": "旧笔记", "url": "https://xhs/a", "summary": "旧摘要"},
        {"site": "web", "title": "网页", "url": "https://web/b", "summary": "保留"},
    ]
    refreshed = [
        {"site": "xhs", "title": "新标题", "url": "https://xhs/a",
         "images": [{"name": "图1", "url": "https://img/1"}]},
        {"site": "xhs", "title": "新笔记", "url": "https://xhs/c",
         "images": [{"name": "图2", "url": "https://img/2"}]},
        {"site": "xhs", "title": "空图", "url": "https://xhs/d", "images": []},
    ]
    merged = merge_refreshed_image_sources(existing, refreshed)
    assert len(merged) == 3
    assert merged[0]["summary"] == "旧摘要"
    assert merged[0]["images"][0]["name"] == "图1"
    assert merged[1]["title"] == "网页"
    assert merged[2]["url"] == "https://xhs/c"


def test_collect_revision_with_image_request_forces_xhs_refresh(monkeypatch):
    import app.agent.orchestrator as orch
    from app.schemas.chat_schema import Preference

    old = [{"site": "xhs", "title": "旧笔记", "url": "https://xhs/old", "summary": "旧资料"}]
    fresh = [{"site": "xhs", "title": "新图", "url": "https://xhs/new", "summary": "新资料",
              "images": [
                  {"name": "小红书灵感·吉隆坡·1", "url": "https://img/1"},
                  {"name": "小红书灵感·吉隆坡·2", "url": "https://img/2"},
              ]}]
    calls = []
    monkeypatch.setattr(orch, "_last_sources_and_dest", lambda cid: (old, "吉隆坡"))
    monkeypatch.setattr(orch, "_progress", lambda cid, text: calls.append(text))

    async def fake_xhs(cid, pref):
        return fresh

    monkeypatch.setattr(orch, "_collect_xhs", fake_xhs)
    sources, revision = asyncio.run(orch.collect_sources(
        "cid", Preference(destination="吉隆坡"), "general", False, "uid",
        "补一下各个行程中的图片",
    ))
    assert revision is True
    assert sum(len(s.get("images") or []) for s in sources) == 2
    assert any("刷新小红书图片" in text for text in calls)


def test_mixed_request_requires_both_source_types():
    """复合需求（路线+酒店）：只有攻略来源不够，必须也有酒店来源才复用。"""
    assert decide_revision([GUIDE], "香港", "香港", "route", wants_hotel=True) is False
    assert decide_revision([CTRIP], "香港", "香港", "route", wants_hotel=True) is False
    assert decide_revision([GUIDE, CTRIP], "香港", "香港", "route", wants_hotel=True) is True
    # 不带酒店需求的路线请求维持原判定
    assert decide_revision([GUIDE], "香港", "香港", "route", wants_hotel=False) is True


def test_dest_in_page_rejects_wrong_city():
    """用户反馈的 bug：查成都酒店，携程按 profile 记忆开到了上海页 → 必须拒绝。"""
    shanghai_page = "上海酒店预订，携程为您提供上海酒店实时价格…"
    assert _dest_in_page("成都", "酒店预订【携程酒店】", shanghai_page) is False
    assert _dest_in_page("上海", "酒店预订【携程酒店】", shanghai_page) is True
    assert _dest_in_page("上海市", "酒店预订【携程酒店】", shanghai_page) is True  # 后缀归一化
    assert _dest_in_page("", "酒店预订", shanghai_page) is False  # 无目的地不放行


def test_excerpt_cleans_snapshot_noise():
    """摘录清洗：去掉 a11y 树的 uid/角色噪声，保留正文。"""
    from app.agent.orchestrator import _excerpt
    raw = '\n'.join([
        'uid=1_2 heading "成都三日游攻略"',
        'uid=1_3 StaticText "第一天去宽窄巷子，人均消费约100元。"',
        'uid=1_4 link "登录"',
        'uid=1_5 generic ""',
    ])
    out = _excerpt(raw)
    assert "成都三日游攻略" in out and "宽窄巷子" in out
    assert "uid=" not in out and "StaticText" not in out
    assert _excerpt("x" * 5000, limit=100).__len__() == 100
