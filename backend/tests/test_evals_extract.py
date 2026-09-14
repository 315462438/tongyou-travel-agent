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


def test_city_landmark_counts_when_it_lands_in_overnight_city():
    """多城行程的**城市名**落在 `overnight_city` 而不是 stop 名里，是完全正常的。

    只看 stop 名会随机漏报：实测同一份马来西亚攻略连跑四次，「仙本那」只有一次
    进了 stop 名，其余都在日标题/过夜城市里。要问的是「在对象图里有没有被表示」。
    """
    trip = _trip(
        days=[DayObject(day=1, overnight_city="仙本那"),
              DayObject(day=2), DayObject(day=3)],
        stops=[StopObject(day=d, order=1, name=f"某地{d}") for d in (1, 2, 3)],
    )
    sample = Sample(id="t", days=[1, 2, 3], must_stops=["仙本那"], expects_cost=True)
    assert "ext_missing_landmark" not in _codes(trip, sample)


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


# ---------- 预算覆盖率（2026-09-14） ----------
# 条目数只反映粒度：flash 抽分类预算表 5 项、总额贴正文；v4-pro 抽每顿饭 13 项、漏住宿油费。

def test_coverage_is_per_person_sum_over_stated_per_person():
    from evals.extract_checks import cost_coverage

    trip = _trip(stated_total=1000.0, headcount=2)  # 正文人均 500；逐项 70 + 300 = 370
    assert cost_coverage(trip) == pytest.approx(0.74)


def test_few_category_items_that_match_the_stated_total_do_not_warn():
    """线上重庆样本的形状：5 条分类大项，合计贴着正文——条目少不是问题。"""
    items = [ExpenseObject(name=n, category=c, day=0, amount=a) for n, c, a in (
        ("酒店4晚", "住宿", 600.0), ("5天餐饮", "餐饮", 367.0), ("油费过路费", "交通", 233.0),
        ("门票项目", "门票", 292.0), ("宝宝用品", "其他", 100.0))]
    trip = _trip(expenses=items, stated_total=4500.0, headcount=3)
    assert "ext_cost_coverage_low" not in _codes(trip)


def test_many_small_items_missing_lodging_warn():
    """线上 v4-pro 的形状：一堆单顿饭价格，漏了住宿和油费，总额只有正文的四成多。"""
    items = [ExpenseObject(name=f"第{d}天午餐", category="餐饮", day=d, amount=50.0)
             for d in range(1, 14)]
    trip = _trip(expenses=items, stated_total=4500.0, headcount=3)  # 650 / 1500
    findings = [f for f in run_extract_checks(trip, _SAMPLE) if f.code == "ext_cost_coverage_low"]
    assert findings and findings[0].level == "warn", "分母也是模型抄的，只能 warn 不能硬失败"


def test_group_amounts_filled_as_per_person_warn_high():
    """线上重庆样本 flash 一轮的形状：团组金额当人均填，总额是正文的 3 倍多。"""
    items = [ExpenseObject(name=n, category=c, day=0, amount=a) for n, c, a in (
        ("酒店4晚", "住宿", 1800.0), ("5天餐饮", "餐饮", 1100.0), ("油费过路费", "交通", 700.0),
        ("门票项目", "门票", 875.0))]
    trip = _trip(expenses=items, stated_total=4500.0, headcount=3)  # 4475 / 1500
    findings = [f for f in run_extract_checks(trip, _SAMPLE) if f.code == "ext_cost_coverage_high"]
    assert findings and findings[0].level == "warn"


def test_no_stated_total_skips_the_coverage_check():
    """正文没写合计就没有 ground truth——不能拿 0 当分母乱报。"""
    from evals.extract_checks import cost_coverage

    trip = _trip(stated_total=0.0)
    assert cost_coverage(trip) is None
    assert "ext_cost_coverage_low" not in _codes(trip)


def test_total_rows_do_not_inflate_coverage():
    """「合计」行混进逐项时覆盖率不能被它撑满——那条由 ext_total_as_item 另报。"""
    from evals.extract_checks import cost_coverage

    trip = _trip(expenses=[ExpenseObject(name="门票", amount=70.0),
                           ExpenseObject(name="合计", amount=2000.0)],
                 stated_total=1000.0, headcount=2)
    assert cost_coverage(trip) == pytest.approx(0.14)


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
