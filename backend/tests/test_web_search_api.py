"""2026-10-15 联网搜索 API：解析清洗、多查询合并去重、未配置时回退浏览器。"""

import asyncio

from app.agent import orchestrator as orch
from app.config import settings
from app.schemas.chat_schema import Preference
from app.tools import web_search_api


def test_parse_results_strips_highlight_tags_and_bad_links():
    data = {"result": {"search_result": [
        {"title": "成都<em>三</em>日攻略", "link": "https://a.com/1", "content": "第一天 <em>宽窄巷子</em> &amp; 人民公园",
         "meta_info": {"publishedTime": "2026-06-14T00:00:00+08:00"}},
        {"title": "坏链接", "link": "javascript:alert(1)", "content": "x"},
        {"title": "只有摘要", "link": "https://a.com/2", "snippet": "摘要文本", "content": None, "meta_info": None},
    ]}}
    out = web_search_api.parse_results(data)
    assert out[0] == {"title": "成都三日攻略", "url": "https://a.com/1",
                      "content": "第一天 宽窄巷子 & 人民公园", "published": "2026-06-14"}
    assert [o["url"] for o in out] == ["https://a.com/1", "https://a.com/2"]
    assert out[1]["content"] == "摘要文本"
    assert web_search_api.parse_results({}) == [] and web_search_api.parse_results({"result": {"search_result": "x"}}) == []


def test_disabled_without_key_or_host(monkeypatch):
    monkeypatch.setattr(settings, "aliyun_search_api_key", "")
    assert not web_search_api.enabled()
    assert asyncio.run(orch._collect_web_api("c", Preference(destination="成都"), ["成都 攻略"])) is None


def _wire(monkeypatch, batches):
    monkeypatch.setattr(settings, "aliyun_search_api_key", "k")
    monkeypatch.setattr(settings, "aliyun_search_host", "https://h")
    monkeypatch.setattr(orch, "_progress", lambda *a, **k: None)
    calls = []

    async def fake_search(q, top_k=None):
        calls.append(q)
        return batches[len(calls) - 1]
    monkeypatch.setattr(web_search_api, "search", fake_search)
    import app.agent.source_pages as sp
    monkeypatch.setattr(sp, "save_page", lambda *a, **k: None)
    return calls


def _r(title, url, text="成都 攻略 " + "内容" * 60):
    return {"title": title, "url": url, "content": text, "published": ""}


def test_queries_run_together_merge_interleaved_and_dedupe(monkeypatch):
    calls = _wire(monkeypatch, [
        [_r("成都三日游", "https://a/1"), _r("成都美食", "https://a/2")],
        [_r("成都三日游", "https://b/9"), _r("成都景点", "https://a/3"), _r("太短", "https://a/4", "成都")],
    ])
    out = asyncio.run(orch._collect_web_api("c", Preference(destination="成都"), ["q1", "q2", "q3", "q4"][:2]))
    assert calls == ["q1", "q2"]
    # 轮流取：q1 第 1 条、q2 第 1 条（同标题去重）、q1 第 2 条、q2 第 2 条；太短的丢掉
    assert [s["url"] for s in out] == ["https://a/1", "https://a/2", "https://a/3"]
    assert all(s["summary"] for s in out)


def test_light_mode_uses_one_query(monkeypatch):
    calls = _wire(monkeypatch, [[_r("成都三日游", "https://a/1")]])
    asyncio.run(orch._collect_web_api("c", Preference(destination="成都"), ["q1", "q2"], light=True))
    assert calls == ["q1"]


def test_all_failed_returns_none_so_caller_falls_back(monkeypatch):
    _wire(monkeypatch, [[], []])
    assert asyncio.run(orch._collect_web_api("c", Preference(destination="成都"), ["q1", "q2"])) is None
