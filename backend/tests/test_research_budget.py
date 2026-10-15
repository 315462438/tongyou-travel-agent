"""2026-10-14 补搜限时：到点不再发起新的搜索或抓取，已抓到的照常交回。"""

import asyncio
import time

from app.agent import orchestrator as orch
from app.config import settings
from app.schemas.chat_schema import Preference


class _Browser:
    def __init__(self):
        self.searches = 0

    async def search_web(self, q, top_n=6):
        self.searches += 1
        return [{"url": f"https://example.org/{q}", "title": q}]


def test_expired_deadline_starts_nothing(monkeypatch):
    monkeypatch.setattr(orch, "_progress", lambda *a, **k: None)
    browser = _Browser()
    out = asyncio.run(orch._search_and_collect_queries(
        "cid", Preference(destination="巢湖"), ["巢湖 螃蟹"], browser, deadline=time.monotonic() - 1,
    ))
    assert out == [] and browser.searches == 0


def test_guide_loops_at_most_once_by_default():
    assert settings.graph_max_guide_rounds == 1


def test_xhs_search_timeout_stays_long_enough_for_retry():
    """MCP 卡住要到它内部 60s 才放手；我们的单次超时太短，重试会撞上还没放手的那次一起失败。"""
    assert settings.xhs_search_timeout_s >= 40


def test_single_fact_questions_route_to_direct_answer():
    from app.agent.deep_research import ROUTE_SYSTEM
    assert "西藏天气怎么样" in ROUTE_SYSTEM.split("- guide")[0]
    assert "拿不准时选 direct" in ROUTE_SYSTEM


def test_weather_lookup_only_for_weather_questions(monkeypatch):
    def boom():
        raise AssertionError("non-weather questions must not call the model for a city")
    monkeypatch.setattr(orch, "get_llm", boom)
    assert orch._live_weather_block("c", "布达拉宫几点开门", "") == ""
    assert orch._WEATHER_RE.search("拉萨现在冷不冷")


def test_model_unavailable_is_found_through_wrappers():
    """LangGraph 等会把异常包一层；包过之后也要认出「模型不可用」，给用户明确提示。"""
    from app.llm.retry import LLMUnavailableError

    try:
        try:
            raise LLMUnavailableError("down")
        except LLMUnavailableError as inner:
            raise RuntimeError("node failed") from inner
    except RuntimeError as outer:
        assert orch._caused_by(outer, LLMUnavailableError)
    assert not orch._caused_by(ValueError("x"), LLMUnavailableError)
