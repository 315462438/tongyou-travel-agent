"""DS Search/Fetch + 原搜索入口的离线合同与回归测试，不读真实密钥、不访问网络。"""

import asyncio
import json

import httpx
import pytest

from app.config import Settings, settings
from app.tools import deepseek_web as ds, web_search_api as web

_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(settings, "deepseek_search_enabled", True)
    monkeypatch.setattr(settings, "deepseek_fetch_enabled", True)
    monkeypatch.setattr(settings, "deepseek_web_base_url", "https://api.deepseek.com")
    monkeypatch.setattr(settings, "deepseek_web_timeout_s", 2)
    monkeypatch.setattr(settings, "web_search_min_results", 3)
    monkeypatch.setattr(settings, "aliyun_search_api_key", "")
    async def ready(kind):
        pass
    monkeypatch.setattr(ds, "_wait_for_slot", ready)


def wire(monkeypatch, handler):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _CLIENT(transport=httpx.MockTransport(handler), **kw))


def result(url="https://example.com/a", content="公告正文" * 40):
    return {"title": "景区公告", "url": url, "content": content, "published": "2026-10-17"}


def test_search_wire_contract_and_metadata(monkeypatch):
    def handle(request):
        assert str(request.url) == "https://api.deepseek.com/v1/tools/search"
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {"query": "景区 site:example.com", "count": 5, "need_content": True}
        return httpx.Response(200, json={"results": [{
            "title": "开园公告", "url": "https://example.com/a", "content": "",
            "summary": "完整摘要", "snippet": "短摘要", "date": "2026-10-17T00:00:00Z",
            "authority": 3, "rerank_score": 2.4,
        }]})
    wire(monkeypatch, handle)
    item = asyncio.run(ds.search("景区 site:example.com", 5))[0]
    assert item["content"] == "完整摘要" and item["published"] == "2026-10-17"
    assert item["provider"] == "deepseek" and item["authority"] == 3
    assert item["rerank_score"] == 2.4 and item["retrieved_at"] > 0


@pytest.mark.parametrize("query", ["", "  ", "字" * 129])
def test_invalid_queries_do_not_call_api(monkeypatch, query):
    wire(monkeypatch, lambda request: pytest.fail("invalid query sent"))
    assert asyncio.run(ds.search(query)) == []


def test_parse_rejects_unsafe_urls_and_bad_types():
    items = [None, {"url": 3}, {"url": "javascript:alert(1)"},
             {"url": "https://user:pass@example.com/a"}, {"url": "http://127.0.0.1"},
             {"url": "http://169.254.169.254"},
             {"url": "https://example.com/a", "title": [], "content": {}, "summary": "有效"}]
    out = ds.parse_results({"results": items})
    assert len(out) == 1 and out[0]["content"] == "有效" and out[0]["title"] == ""
    assert ds.parse_results([]) == [] and ds.parse_results({"results": "bad"}) == []


@pytest.mark.parametrize("status,calls", [(400, 1), (401, 1), (402, 1), (403, 1), (404, 1),
                                         (408, 2), (429, 2), (500, 2), (504, 2)])
def test_errors_are_bounded_and_do_not_break_caller(monkeypatch, status, calls):
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(status, json={"error": {"message": "unavailable"}})
    wire(monkeypatch, handle)
    assert asyncio.run(ds.search("景区")) == []
    assert len(seen) == calls


def test_transient_error_retries_once_then_recovers(monkeypatch):
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(429 if len(seen) == 1 else 200,
                              json={"results": [{"url": "https://example.com", "content": "正文"}]})
    wire(monkeypatch, handle)
    assert asyncio.run(ds.search("景区"))[0]["content"] == "正文"
    assert len(seen) == 2


@pytest.mark.parametrize("body", [b"not-json", b"[]", b'{"results":null}'])
def test_malformed_response_is_empty(monkeypatch, body):
    wire(monkeypatch, lambda request: httpx.Response(200, content=body))
    assert asyncio.run(ds.search("景区")) == []


def test_timeout_is_empty_and_cancellation_propagates(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("timeout")
    wire(monkeypatch, timeout)
    assert asyncio.run(ds.search("景区")) == []
    def cancelled(request):
        raise asyncio.CancelledError()
    wire(monkeypatch, cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ds.search("景区"))


def test_total_deadline_includes_the_http_wait(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_web_timeout_s", 0.01)
    async def slow(request):
        await asyncio.sleep(0.1)
        pytest.fail("total deadline did not cancel the request")
    wire(monkeypatch, slow)
    assert asyncio.run(ds.search("景区")) == []


def test_disabled_flags_and_missing_key(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_search_enabled", False)
    assert not ds.enabled() and ds.enabled("fetch")
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    assert not ds.enabled("fetch")
    assert asyncio.run(ds.fetch("https://example.com")) is None
    assert not web.enabled()


def test_fetch_wire_and_markdown(monkeypatch):
    monkeypatch.setattr(ds, "ensure_safe_url", lambda url: None)
    def handle(request):
        assert str(request.url).endswith("/v1/tools/fetch")
        assert json.loads(request.content) == {"url": "https://example.com/a"}
        return httpx.Response(200, json={"title": "公告", "content": "# 原文\n周一闭园"})
    wire(monkeypatch, handle)
    out = asyncio.run(ds.fetch("https://example.com/a"))
    assert out["content"] == "# 原文\n周一闭园" and out["provider"] == "deepseek"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://127.0.0.1/a", "http://169.254.169.254",
                                 "https://user:pass@example.com", "https://example.com/" + "a" * 8192])
def test_fetch_rejects_unsafe_urls_before_request(monkeypatch, url):
    wire(monkeypatch, lambda request: pytest.fail("unsafe fetch sent"))
    assert asyncio.run(ds.fetch(url)) is None


async def empty(*args):
    return []


def test_aliyun_sufficient_does_not_call_ds(monkeypatch):
    async def ali(*args):
        return [result(f"https://example.com/{i}") for i in range(3)]
    async def forbidden(*args):
        pytest.fail("unnecessary DS call")
    monkeypatch.setattr(web, "_aliyun_search", ali)
    monkeypatch.setattr(ds, "search", forbidden)
    out = asyncio.run(web.search("景区"))
    assert len(out) == 3 and all(r["provider"] == "aliyun" for r in out)


def test_insufficient_aliyun_merges_ds_and_dedupes_tracking_urls(monkeypatch):
    async def ali(*args):
        return [result("https://example.com/a?utm_source=x#top", "短文")]
    async def search(*args):
        return [result("https://example.com/a", "更长的正文" * 40), result("https://example.com/b")]
    monkeypatch.setattr(web, "_aliyun_search", ali)
    monkeypatch.setattr(ds, "search", search)
    out = asyncio.run(web.search("景区"))
    assert len(out) == 2 and out[0]["content_provider"] == "deepseek"
    assert out[0]["provider"] == "aliyun" and len(out[0]["content"]) > 80


def test_bad_aliyun_items_do_not_crowd_out_ds(monkeypatch):
    async def ali(*args):
        return [result(f"https://example.com/bad{i}", "短") for i in range(8)]
    async def search(*args):
        return [result("https://example.com/good")]
    monkeypatch.setattr(web, "_aliyun_search", ali)
    monkeypatch.setattr(ds, "search", search)
    assert asyncio.run(web.search("景区", 1))[0]["url"].endswith("/good")


def test_aliyun_failure_uses_ds_and_both_empty_allows_browser_fallback(monkeypatch):
    monkeypatch.setattr(web, "_aliyun_search", empty)
    async def search(*args):
        return [result()]
    monkeypatch.setattr(ds, "search", search)
    assert asyncio.run(web.search("景区"))[0]["provider"] == "deepseek"
    monkeypatch.setattr(ds, "search", empty)
    assert asyncio.run(web.search("景区")) == []


def test_model_1017_uses_official_alias():
    conf = Settings(_env_file=None, database_url="sqlite://")
    assert {conf.model_planner, conf.model_extractor, conf.model_classifier, conf.model_vision} == {"deepseek-flash"}


def test_research_fetch_uses_ds_with_source_isolation_and_shared_quota(monkeypatch):
    from app.agent import research_tools
    monkeypatch.setattr("app.agent.orchestrator._progress", lambda *args, **kw: None)
    monkeypatch.setattr(research_tools, "ensure_safe_url", lambda url: None)
    monkeypatch.setattr(settings, "deep_research_max_fetches", 1)
    seen = []
    async def fetch(url):
        seen.append(url)
        return {"title": "官方开园公告", "content": "周一闭园，以本公告为准。" * 200, "retrieved_at": 123.0}
    monkeypatch.setattr(ds, "fetch", fetch)
    wire(monkeypatch, lambda request: pytest.fail("DS 成功后不应直接抓网页"))
    sources = []
    main, sub = research_tools.build_tools("c1", "u1", None, sources)
    tools = {t.__name__: t for t in main + sub}
    async def run():
        out = await tools["fetch_url"]("https://example.com/a")
        over = await tools["fetch_url"]("https://example.com/b")
        return out, over
    out, over = asyncio.run(run())
    assert "<external_content" in out and "read_source" in out
    assert "配额已用完" in over and seen == ["https://example.com/a"]
    assert sources == [{"title": "官方开园公告", "url": "https://example.com/a",
                        "provider": "deepseek", "retrieved_at": 123.0}]


def test_research_fetch_ds_failure_uses_existing_http_path(monkeypatch):
    from app.agent import research_tools
    monkeypatch.setattr("app.agent.orchestrator._progress", lambda *args, **kw: None)
    monkeypatch.setattr(research_tools, "ensure_safe_url", lambda url: None)
    async def fetch(url):
        return None
    monkeypatch.setattr(ds, "fetch", fetch)
    wire(monkeypatch, lambda request: httpx.Response(200, text="<p>" + "原有 HTTP 正文。" * 30 + "</p>"))
    sources = []
    main, sub = research_tools.build_tools("c1", "u1", None, sources)
    tool = {t.__name__: t for t in main + sub}["fetch_url"]
    out = asyncio.run(tool("https://example.com/a"))
    assert "原有 HTTP 正文" in out and "<external_content" in out
    assert sources[0]["url"] == "https://example.com/a"


def test_guide_keeps_provider_and_date_for_ds_sources(monkeypatch):
    from app.agent import orchestrator as orch, source_pages
    from app.schemas.chat_schema import Preference
    monkeypatch.setattr(orch, "_progress", lambda *args, **kw: None)
    monkeypatch.setattr(source_pages, "save_page", lambda *args, **kw: "p1")
    async def search(*args):
        return [{**result(content="成都 公告 " * 50), "provider": "deepseek", "retrieved_at": 123.0}]
    monkeypatch.setattr(web, "search", search)
    out = asyncio.run(orch._collect_web_api("c1", Preference(destination="成都"), ["成都 景区公告"]))
    assert out[0]["provider"] == "deepseek" and out[0]["published"] == "2026-10-17"
    assert out[0]["retrieved_at"] == 123.0 and out[0]["page_id"] == "p1"


def test_rate_gate_spaces_each_endpoint_independently(monkeypatch):
    # 恢复本测试要测的真实函数（autouse 只替换请求测试的等待）。
    import importlib.util
    spec = importlib.util.spec_from_file_location("rate_gate_test", ds.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, "monotonic", lambda: 100.0)
    delays = []
    async def sleep(delay):
        delays.append(delay)
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    async def run():
        await module._wait_for_slot("search")
        await module._wait_for_slot("search")
        await module._wait_for_slot("fetch")
    asyncio.run(run())
    assert delays == pytest.approx([0.22])
