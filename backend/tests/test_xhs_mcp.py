"""Phase 59 小红书 MCP 客户端单测（纯解析 + 组装，全离线，不连真 MCP）。"""

import asyncio
import json

import pytest

from app.config import settings
from app.tools import xhs_mcp
from app.tools.xhs_mcp import _parse_detail, _parse_feeds, collect_xhs_sources, note_url


def test_parse_feeds_real_shape():
    """实测返回结构：feeds[].id/xsec_token（列表页 title 常为空）。"""
    text = json.dumps({"feeds": [
        {"id": "689203e6", "xsec_token": "ABfx=", "title": "",
         "note_card": {"display_title": "成都红黑榜"}},
        {"id": "", "xsec_token": "x"},  # 无 id → 丢弃
        {"id": "abc", "xsecToken": "tok2"},  # 驼峰 token 兼容
    ]})
    out = _parse_feeds(text)
    assert out == [
        {"feed_id": "689203e6", "xsec_token": "ABfx=", "title": "成都红黑榜"},
        {"feed_id": "abc", "xsec_token": "tok2", "title": ""},
    ]


def test_parse_feeds_bad_input():
    assert _parse_feeds("not json") == []
    assert _parse_feeds("{}") == []
    assert _parse_feeds('{"feeds": "oops"}') == []


def test_parse_detail_real_shape():
    text = json.dumps({"data": {"note": {
        "title": "成都8-9月景点红黑榜", "desc": "三日路线：Day1 春熙路…住宿指南…美食清单",
        "imageList": [
            {"urlDefault": "http://sns-webpic-qc.xhscdn.com/a", "width": 1440, "height": 1920},
            {"urlPre": "https://sns-webpic-qc.xhscdn.com/b", "width": 720, "height": 960},
            {"urlDefault": "javascript:alert(1)"},
        ],
    }}})
    det = _parse_detail(text)
    assert det["title"] == "成都8-9月景点红黑榜" and "三日路线" in det["desc"]
    assert det["images"] == [
        {"url": "https://sns-webpic-qc.xhscdn.com/a", "width": 1440, "height": 1920},
        {"url": "https://sns-webpic-qc.xhscdn.com/b", "width": 720, "height": 960},
    ]
    assert _parse_detail("nope") is None
    assert _parse_detail(json.dumps({"data": {"note": {"title": "t", "desc": ""}}})) is None  # 无正文


def test_note_url():
    assert note_url("abc123") == "https://www.xiaohongshu.com/explore/abc123"


def test_disabled_short_circuits(monkeypatch):
    monkeypatch.setattr(settings, "xhs_mcp_url", "")
    assert not xhs_mcp.enabled()
    assert asyncio.run(xhs_mcp.search_notes("成都")) == []
    assert asyncio.run(xhs_mcp.note_detail("a", "b")) is None
    assert asyncio.run(collect_xhs_sources("成都 旅游攻略")) == []


def test_collect_assembles_sources_and_skips_short(monkeypatch):
    monkeypatch.setattr(settings, "xhs_mcp_url", "http://fake:18060/mcp")
    monkeypatch.setattr(settings, "xhs_notes_per_turn", 2)

    async def fake_search(keyword):
        return [{"feed_id": f"f{i}", "xsec_token": f"t{i}", "title": ""} for i in range(4)]

    details = {
        "f0": {"title": "太短", "desc": "短"},  # <100 字 → 跳过
        "f1": {"title": "成都三日游", "desc": "路线详情" * 50,
               "images": [{"url": "https://sns-webpic-qc.xhscdn.com/1"}]},
        "f2": {"title": "美食清单", "desc": "美食推荐" * 50, "images": []},
        "f3": {"title": "不该读到", "desc": "x" * 200},  # 已满 2 篇不再读
    }

    async def fake_detail(fid, token):
        return details[fid]

    monkeypatch.setattr(xhs_mcp, "search_notes", fake_search)
    monkeypatch.setattr(xhs_mcp, "note_detail", fake_detail)
    out = asyncio.run(collect_xhs_sources("成都 旅游攻略"))
    assert len(out) == 2
    assert out[0]["site"] == "xhs" and out[0]["title"].startswith("小红书｜成都三日游")
    assert out[0]["url"] == "https://www.xiaohongshu.com/explore/f1"
    assert out[0]["images"] == [{
        "name": "小红书灵感·成都三日游·1",
        "url": "https://sns-webpic-qc.xhscdn.com/1",
    }]
    assert len(out[0]["summary"]) <= 1500


def test_collect_failure_returns_empty(monkeypatch):
    monkeypatch.setattr(settings, "xhs_mcp_url", "http://fake:18060/mcp")

    async def boom(keyword):
        raise RuntimeError("mcp down")

    monkeypatch.setattr(xhs_mcp, "search_notes", boom)
    with pytest.raises(RuntimeError):  # collect 本身不吞——由调用方 _collect_xhs 兜底
        asyncio.run(collect_xhs_sources("成都"))


# ---------- Phase 59.1：澄清延续护栏 + 多城查询计划 ----------

def test_xhs_query_plan_single_and_multi():
    from app.agent.orchestrator import _xhs_query_plan
    from app.schemas.chat_schema import Preference

    # 单城：1 查询 × N 篇
    plan = _xhs_query_plan(Preference(destination="厦门", interests=["美食", "海边"]))
    assert len(plan) == 1 and plan[0][0].startswith("厦门 旅游攻略") and "美食" in plan[0][0]
    # 多城：逐城各 xhs_notes_per_city 篇（最多 3 城）——整串搜命中差
    plan = _xhs_query_plan(Preference(destination="武汉、开封、洛阳、西安"))
    assert [q for q, _ in plan] == ["武汉 旅游攻略", "开封 旅游攻略", "洛阳 旅游攻略"]
    assert all(n == settings.xhs_notes_per_city for _, n in plan)
    assert _xhs_query_plan(Preference(destination="")) == []


def test_web_search_mode_tiers(monkeypatch):
    """必应三档：小红书 ≥3 篇跳过 / ≥1 篇轻量 / 0 篇全量。"""
    from app.agent.orchestrator import _web_search_mode

    monkeypatch.setattr(settings, "xhs_skip_search_min", 3)
    monkeypatch.setattr(settings, "xhs_min_for_light_search", 1)
    assert _web_search_mode(0) == "full"
    assert _web_search_mode(1) == "light"
    assert _web_search_mode(2) == "light"
    assert _web_search_mode(3) == "skip"
    assert _web_search_mode(6) == "skip"


def test_clarify_continuation_guard(monkeypatch):
    """上一条 assistant 是澄清短问句 → True（本轮回 guide）；是长攻略 → False（正常分类）。"""
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.agent.orchestrator import _is_clarify_continuation
    from app.db.models import Base, TravelMessage

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        @contextmanager
        def fake_session():
            yield db

        monkeypatch.setattr("app.agent.orchestrator.get_session", fake_session)
        db.add(TravelMessage(conversation_id="c1", role="user", content="四城攻略"))
        db.add(TravelMessage(conversation_id="c1", role="assistant", content="请问您计划总共玩几天呢？"))
        db.add(TravelMessage(conversation_id="c1", role="user", content="10天"))  # 本轮已落库
        db.commit()
        assert _is_clarify_continuation("c1") is True

        db.add(TravelMessage(conversation_id="c2", role="assistant", content="# 厦门攻略\n" + "内容" * 100))
        db.add(TravelMessage(conversation_id="c2", role="user", content="谢谢"))
        db.commit()
        assert _is_clarify_continuation("c2") is False  # 长攻略后短回复 → 正常分类（direct 合理）
        assert _is_clarify_continuation("c-none") is False  # 无历史


def test_normalize_destination_placeholders():
    """Phase 59.2：占位词目的地一律归空（触发反问），真实地名原样保留。"""
    from app.agent.orchestrator import _normalize_destination

    assert _normalize_destination("热门目的地") == ""
    assert _normalize_destination("附近") == ""
    assert _normalize_destination(" 周边 ") == ""
    assert _normalize_destination("") == ""
    assert _normalize_destination(None) == ""
    assert _normalize_destination("黄山、庐山") == "黄山、庐山"
    assert _normalize_destination(" 成都 ") == "成都"


def test_collect_circuit_breaker_on_consecutive_failures(monkeypatch):
    """2026-08-13：MCP 垮了（500/超时）时连续 2 次详情失败 → 快速熔断，不再逐篇等超时。

    否则每篇 40s 超时 × 7 次尝试 ≈ 5 分钟纯等待，且期间停止按钮无检查点。
    """
    monkeypatch.setattr(settings, "xhs_mcp_url", "http://fake:18060/mcp")
    monkeypatch.setattr(settings, "xhs_notes_per_turn", 5)

    async def fake_search(keyword):
        return [{"feed_id": f"f{i}", "xsec_token": f"t{i}", "title": ""} for i in range(6)]

    read = []

    async def fake_detail(fid, token):
        read.append(fid)
        return None  # MCP 故障

    monkeypatch.setattr(xhs_mcp, "search_notes", fake_search)
    monkeypatch.setattr(xhs_mcp, "note_detail", fake_detail)
    out = asyncio.run(collect_xhs_sources("成都 旅游攻略"))
    assert out == []
    # 熔断：只读了前 2 篇就 break（原逻辑会读满 n+2=7 次尝试）
    assert read == ["f0", "f1"]


def test_collect_short_note_does_not_trigger_breaker(monkeypatch):
    """太短的笔记（纯图/广告位）不算 MCP 故障，不累计熔断。"""
    monkeypatch.setattr(settings, "xhs_mcp_url", "http://fake:18060/mcp")
    monkeypatch.setattr(settings, "xhs_notes_per_turn", 1)

    async def fake_search(keyword):
        return [{"feed_id": f"f{i}", "xsec_token": f"t{i}", "title": ""} for i in range(3)]

    read = []

    async def fake_detail(fid, token):
        read.append(fid)
        return {"title": "短", "desc": "短" if fid != "f2" else "x" * 200, "images": []}

    monkeypatch.setattr(xhs_mcp, "search_notes", fake_search)
    monkeypatch.setattr(xhs_mcp, "note_detail", fake_detail)
    out = asyncio.run(collect_xhs_sources("成都 旅游攻略"))
    assert len(out) == 1  # f2 正常收录
    assert read == ["f0", "f1", "f2"]  # 短笔记不熔断，继续读到合格的一篇


def test_collect_total_budget_exceeded(monkeypatch):
    """2026-08-14：整轮总预算——MCP 半死（每篇卡在超时边缘）时整轮放弃，不无限等待。"""
    monkeypatch.setattr(settings, "xhs_mcp_url", "http://fake:18060/mcp")
    monkeypatch.setattr(settings, "xhs_collect_timeout_s", 0.05)
    monkeypatch.setattr(settings, "xhs_notes_per_turn", 3)

    async def fake_search(keyword):
        return [{"feed_id": f"f{i}", "xsec_token": f"t{i}", "title": ""} for i in range(3)]

    async def slow_detail(fid, token):
        await asyncio.sleep(0.2)  # 单篇远慢于预算 → wait_for 取消
        return {"title": "慢", "desc": "x" * 200, "images": []}

    monkeypatch.setattr(xhs_mcp, "search_notes", fake_search)
    monkeypatch.setattr(xhs_mcp, "note_detail", slow_detail)
    out = asyncio.run(collect_xhs_sources("成都 旅游攻略"))
    assert out == []  # 超预算整轮放弃，必应兜底


def test_collect_total_budget_sufficient_for_normal(monkeypatch):
    """预算内正常采集不受影响（默认 150s 对 3 篇 × 20s 富余）。"""
    monkeypatch.setattr(settings, "xhs_mcp_url", "http://fake:18060/mcp")
    monkeypatch.setattr(settings, "xhs_collect_timeout_s", 150)
    monkeypatch.setattr(settings, "xhs_notes_per_turn", 2)

    async def fake_search(keyword):
        return [{"feed_id": "f1", "xsec_token": "t1", "title": ""}]

    async def fake_detail(fid, token):
        return {"title": "成都", "desc": "路线" * 100, "images": []}

    monkeypatch.setattr(xhs_mcp, "search_notes", fake_search)
    monkeypatch.setattr(xhs_mcp, "note_detail", fake_detail)
    out = asyncio.run(collect_xhs_sources("成都 旅游攻略"))
    assert len(out) == 1


def test_collect_breaker_is_consecutive_not_cumulative(monkeypatch):
    """2026-08-14 名实修复：失败→成功→失败 不熔断（成功重置计数）。

    旧代码漏了重置 → 累计 2 次失败就熔断；健康 MCP 下删帖/登录墙等零星失败会误判故障丢料。
    """
    monkeypatch.setattr(settings, "xhs_mcp_url", "http://fake:18060/mcp")
    monkeypatch.setattr(settings, "xhs_notes_per_turn", 5)

    async def fake_search(keyword):
        return [{"feed_id": f"f{i}", "xsec_token": f"t{i}", "title": ""} for i in range(6)]

    read = []

    async def fake_detail(fid, token):
        read.append(fid)
        if fid in ("f0", "f2"):  # 零星失败（删帖/登录墙）
            return None
        if fid == "f1":
            return {"title": "成都", "desc": "路线" * 100, "images": []}
        if fid in ("f3",):  # 连续第二次失败 → 熔断
            return None
        return {"title": "成都2", "desc": "美食" * 100, "images": []}

    monkeypatch.setattr(xhs_mcp, "search_notes", fake_search)
    monkeypatch.setattr(xhs_mcp, "note_detail", fake_detail)
    out = asyncio.run(collect_xhs_sources("成都 旅游攻略"))
    # f0 失败（连续1）→ f1 成功（重置）→ f2 失败（连续1）→ f3 失败（连续2 → 熔断 break）
    assert read == ["f0", "f1", "f2", "f3"]
    assert len(out) == 1 and out[0]["title"].startswith("小红书｜成都")  # f1 被保留
