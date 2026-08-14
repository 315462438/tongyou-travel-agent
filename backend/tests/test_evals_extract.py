"""本体抽取评估器的单测（2026-08-14）。

评估器本身也会写错——一个永远返回「通过」的检查器比没有检查器更糟，
因为它会让人以为守住了。这里每条都构造一个**故意坏掉的 TripObject**，
断言对应的检查项确实报警。

全离线：不调 LLM、不连库。
"""

import pytest

from app.ontology.objects import (
    DayObject,
    ExpenseObject,
    StopObject,
    TripObject,
)
from evals.extract_checks import Sample, run_extract_checks


def _trip(**kw) -> TripObject:
    """构造一个「本该全对」的行程：3 天，每天 2 个点，带开销。"""
    days = [DayObject(day=d) for d in (1, 2, 3)]
    stops = [StopObject(day=d, order=i, name=n)
             for d, names in {1: ["黄鹤楼", "江汉关"], 2: ["东湖", "省博"], 3: ["昙华林", "户部巷"]}.items()
             for i, n in enumerate(names, 1)]
    base = dict(
        days=days, stops=stops,
        expenses=[ExpenseObject(name="门票", category="门票", day=1, amount=70.0),
                  ExpenseObject(name="住宿", category="住宿", day=0, amount=300.0)],
        headcount=2, lanes=["itinerary", "cost"],
    )
    base.update(kw)
    return TripObject(**base).normalized()


_SAMPLE = Sample(id="t", days=[1, 2, 3], must_stops=["黄鹤楼", "东湖"],
                 expect_headcount=2, expects_cost=True)


def _codes(trip, sample=_SAMPLE) -> set[str]:
    return {f.code for f in run_extract_checks(trip, sample)}


def test_healthy_trip_passes_everything():
    """基线必须干净——否则下面每条断言都说明不了问题。"""
    assert _codes(_trip()) == set()


# ---------- 逐日覆盖 ----------

def test_missing_day_is_reported():
    """分块路径（天数 > ontology_single_call_max_days）丢天 → 海报少一张图。"""
    trip = _trip(days=[DayObject(day=1), DayObject(day=2)])
    assert "ext_missing_days" in _codes(trip)


def test_failed_days_is_reported_even_when_days_look_complete():
    """部分失败时 days 可能凑齐了，但 failed_days 非空说明那几天是空壳。"""
    trip = _trip(failed_days=[2])
    assert "ext_failed_days" in _codes(trip)


def test_day_without_any_stop_is_reported():
    """守：海报那天会是一张白图。"""
    trip = _trip(stops=[StopObject(day=1, order=1, name="黄鹤楼"),
                        StopObject(day=2, order=1, name="东湖")])
    assert "ext_empty_day" in _codes(trip)


def test_missing_landmark_is_reported():
    trip = _trip(stops=[StopObject(day=d, order=1, name=f"某地{d}") for d in (1, 2, 3)])
    got = _codes(trip)
    assert "ext_missing_landmark" in got


# ---------- Phase 67 不变式 ----------

@pytest.mark.parametrize("name", ["合计", "总计约3450元", "小计", "共计"])
def test_total_row_must_not_become_an_expense_item(name):
    """**最隐蔽的一种错**：汇总行进了逐项，服务端再求和 → 总额翻倍，
    而表面上每一行看着都对。`extract._is_total_line` 挡的就是它。"""
    trip = _trip(expenses=[ExpenseObject(name=name, amount=3450.0)])
    assert "ext_total_as_item" in _codes(trip)


def test_headcount_mismatch_is_reported():
    """预算表写「两人合计」却认成 1 人 → 人均金额整体翻倍。"""
    assert "ext_headcount" in _codes(_trip(headcount=1))


def test_missing_cost_lane_is_reported():
    """cost 路整条静默失败时，build_trip_object 只是把它留空——闸门必须发现。"""
    got = _codes(_trip(expenses=[], lanes=["itinerary"]))
    assert "ext_no_expenses" in got


def test_all_zero_amounts_is_reported():
    trip = _trip(expenses=[ExpenseObject(name="门票", amount=0.0)])
    assert "ext_zero_amounts" in _codes(trip)


# ---------- 名字卫生 ----------

@pytest.mark.parametrize("bad", ["**黄鹤楼**", "[[img:黄鹤楼]]", "`东湖`"])
def test_markdown_residue_in_names_is_reported(bad):
    """带残渣的名字会原样显示在海报和预算表里。"""
    trip = _trip(stops=[StopObject(day=d, order=1, name=bad) for d in (1, 2, 3)])
    assert "ext_markdown_residue" in _codes(trip)


# ---------- lane 登记 ----------

def test_empty_lane_registered_is_reported():
    """空结果却登记了 lane = 缓存把「什么都没有」当成功结果永久固化，
    下次调用不会重试——这类错一旦发生是**静默且长期**的。"""
    trip = _trip(expenses=[], lanes=["itinerary", "cost"])
    assert "ext_empty_lane_registered" in _codes(trip)


def test_unregistered_lane_is_reported():
    trip = _trip(lanes=[])
    assert "ext_lane_unregistered" in _codes(trip)


# ---------- 数据集本身的完整性 ----------

def test_extract_yaml_is_loadable_and_well_formed():
    """样本文件不进 git，但 yaml 进——它至少要能解析、字段齐、哈希登记了。"""
    from evals.extract_eval import load_samples

    samples = load_samples()
    assert samples, "extract.yaml 不该是空的"
    for s in samples:
        assert s.message_id and len(s.sha256) == 16, f"{s.id} 缺 message_id/sha256"
        assert s.days == sorted(s.days) and s.days[0] == 1, f"{s.id} 的 days 应从 1 连续"
        assert s.note, f"{s.id} 没写「守什么」——照 checks.py 的门槛，说不清就不该进集"
