"""导入协同行程可靠性（2026-07-31）。

计划：docs/task_plans/导入协同行程可靠性重构-2026-07-31.md
线上：6 天攻略连续两次导入失败，各等约 2 分钟，留下两条 6 天 0 地点的空行程。
根因日志：`Day 2–2 分段抽取失败：结构化输出达到 3000 tokens 上限，已在 JSON 中途截断`。
全部离线（LLM 用 fake）。
"""

import asyncio

import pytest

from app.agent.trip_planner import TripDraft, TripImportDays, TripImportSummary
from app.api.trip_api import _extract_import_draft, _failed_days_of, _fmt_days
from app.config import settings

GUIDE = "\n\n".join(
    [f"## Day {d} 第{d}天\n\n上午去景点{d}A，下午去景点{d}B。" for d in range(1, 7)]
)


class _FakeLLM:
    """summary 永远成功；days 抽取按 fail_days 决定哪几天炸（模拟 token 截断）。"""

    def __init__(self, fail_days=()):
        self.fail_days = set(fail_days)
        self.day_calls = []
        self.max_tokens_seen = []

    def parse(self, prompt, schema, system="", model=None, max_tokens=None):
        if schema is TripImportSummary:
            return TripImportSummary(title="大理丽江6日", destination="大理、丽江", days=6,
                                     hotel_options=[], budget_items=[])
        self.max_tokens_seen.append(max_tokens)
        import re
        lo = int(re.search(r"Day (\d+)", prompt).group(1))
        self.day_calls.append(lo)
        if lo in self.fail_days:
            raise ValueError("结构化输出达到 3000 tokens 上限，已在 JSON 中途截断")
        return TripImportDays(
            stops=[{"day": lo, "name": f"景点{lo}A", "note": "", "transport": ""}],
            stays=[], day_plans=[],
        )


def _run(llm, **kw) -> TripDraft:
    return asyncio.run(_extract_import_draft(llm, GUIDE, **kw))


# ---------- 根因 A：单段输出上限 ----------

def test_chunk_uses_configured_max_tokens():
    """3000 太低——线上切到单天仍被截断。上限必须走配置且明显更大。"""
    llm = _FakeLLM()
    _run(llm)
    assert settings.trip_import_chunk_max_tokens >= 6000
    assert set(llm.max_tokens_seen) == {settings.trip_import_chunk_max_tokens}


# ---------- 根因 B：部分成功必须保留 ----------

def test_partial_success_keeps_good_days():
    """一天失败不再让其余 5 天陪葬（原来 asyncio.gather 快速失败，整包作废）。"""
    draft = _run(_FakeLLM(fail_days={2}))
    assert draft.failed_days == [2]
    assert sorted(s.day for s in draft.stops) == [1, 3, 4, 5, 6]


def test_all_days_fail_still_returns_draft_with_destination():
    """根因 E：destination 来自 summary，与逐天抽取独立，全失败也要落盘。"""
    draft = _run(_FakeLLM(fail_days={1, 2, 3, 4, 5, 6}))
    assert draft.failed_days == [1, 2, 3, 4, 5, 6]
    assert draft.stops == []
    assert draft.destination == "大理、丽江"  # 不再显示「未定目的地」


def test_no_failure_means_empty_failed_days():
    draft = _run(_FakeLLM())
    assert draft.failed_days == [] and len(draft.stops) == 6


# ---------- 只重跑失败的天 ----------

def test_only_days_limits_extraction():
    llm = _FakeLLM()
    draft = _run(llm, only_days={2, 5})
    assert sorted(llm.day_calls) == [2, 5]  # 已成功的天不重跑
    assert sorted(s.day for s in draft.stops) == [2, 5]


def test_retry_can_succeed_after_failure():
    first = _run(_FakeLLM(fail_days={2}))
    assert first.failed_days == [2]
    retry = _run(_FakeLLM(), only_days=set(first.failed_days))
    assert retry.failed_days == [] and [s.day for s in retry.stops] == [2]


# ---------- 进度回调 ----------

def test_progress_callback_reports_each_day():
    seen = []
    _run(_FakeLLM(), on_progress=lambda done, total: seen.append((done, total)))
    assert [d for d, _ in seen] == list(range(1, 7))
    assert {t for _, t in seen} == {6}  # 「已完成 3/6 天」的分母


def test_progress_callback_fires_even_for_failed_day():
    seen = []
    _run(_FakeLLM(fail_days={3}), on_progress=lambda done, total: seen.append(done))
    assert len(seen) == 6  # 失败的天也要推进进度，否则进度会卡住


def test_progress_callback_error_ignored():
    def boom(*_a):
        raise RuntimeError("progress boom")

    draft = _run(_FakeLLM(), on_progress=boom)
    assert len(draft.stops) == 6  # 回调炸了不影响抽取


# ---------- 失败天回读（重试端点用） ----------

class _Trip:
    def __init__(self, status, review):
        self.ai_status = status
        self.ai_review = review


def test_failed_days_roundtrip():
    review = f"部分导入成功：第 {_fmt_days([2, 5])} 天解析失败（其余 4 天已导入）。"
    assert _failed_days_of(_Trip("partial", review)) == {2, 5}


def test_failed_days_empty_for_other_states():
    assert _failed_days_of(_Trip("failed", "导入失败：模型输出被截断。")) == set()
    assert _failed_days_of(_Trip(None, "")) == set()


# ---------- 逐日 POI 检索城市（2026-08-01 线上事故） ----------

def test_single_city_trip_ignores_overnight_city_for_pois():
    """六安一日游当晚坐高铁到武汉过夜 → day_plan.overnight_city=武汉，
    结果当天**六安的景点**全按武汉查：「中央公园」匹配到汉阳中央公园（行政区校验还通过），
    另外三个查不到，地图整体飘到武汉、路线画不出来。"""
    from app.agent.trip_planner import DraftDayPlan, DraftStop
    from app.api.trip_api import _geocode_stops_by_city

    asked: list[tuple[str, tuple[str, ...]]] = []

    async def fake_geocode(names, city):
        asked.append((city, tuple(names)))
        return {n: f"{city}-坐标" for n in names} if city == "六安" else {}

    stops = [DraftStop(day=1, name=n) for n in
             ("神云吊锅老店", "中央公园", "皖西博物馆", "月亮岛", "六安站")]
    plans = [DraftDayPlan(day=1, overnight_city="武汉")]
    result = asyncio.run(_geocode_stops_by_city(stops, plans, "六安", fake_geocode))

    assert len(result) == 5  # 五个点全部定位（此前只有 2 个，且都在武汉）
    assert all(v == "六安-坐标" for v in result.values())
    assert asked[0][0] == "六安"  # 首选就是行程目的地，不是过夜城市


def test_destination_is_always_a_retry_candidate():
    """当天 hint 城市查不到时，行程自己的目的地必须被试到（此前从不在候选里）。"""
    from app.agent.trip_planner import DraftDayPlan, DraftStop
    from app.api.trip_api import _geocode_stops_by_city

    tried: list[str] = []

    async def fake_geocode(names, city):
        tried.append(city)
        return {n: f"{city}-坐标" for n in names} if city == "开封" else {}

    stops = [DraftStop(day=2, name="清明上河园")]
    plans = [DraftDayPlan(day=1, overnight_city="郑州"), DraftDayPlan(day=2, overnight_city="郑州")]
    result = asyncio.run(_geocode_stops_by_city(stops, plans, "郑州、开封", fake_geocode))
    assert result[(2, "清明上河园")] == "开封-坐标"
    assert "开封" in tried


def test_route_style_destination_not_treated_as_city():
    """「西安至兰州」「合肥→武汉」是路线描述不是城市名，不能拿去当全程检索城市。"""
    from app.api.trip_api import _is_single_city

    assert _is_single_city("六安", ["六安"])
    assert not _is_single_city("西安至兰州", ["西安至兰州"])
    assert not _is_single_city("合肥→武汉", ["合肥→武汉"])
    assert not _is_single_city("武汉、开封", ["武汉", "开封"])


def test_repair_path_uses_same_city_rule():
    """「重新定位」按钮与手动加地点走的是 _trip_city_for_day，必须和导入同规则——
    否则修好导入、用户一点重新定位又被 overnight_city 打回武汉。"""
    import json as _json

    from app.api.trip_api import _trip_city_for_day

    class _T:
        destination = "六安"
        days = 1
        day_plan_json = _json.dumps([{"day": 1, "overnight_city": "武汉"}])

    assert _trip_city_for_day(_T(), 1) == "六安"

    class _Multi(_T):
        destination = "郑州、开封"

    assert _trip_city_for_day(_Multi(), 1) == "武汉"  # 多城仍按逐日过夜城市
