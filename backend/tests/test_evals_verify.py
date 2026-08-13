"""三层验证器 + 闸门一致性的回归测试（2026-08-04）。

补的是 `evals/verify.py` 此前**一行测试都没有**的窟窿——28 个既有测试全在 checks.py，
于是「三层验证」这层本身是未被验证的。这里守三件事：

1. 三层各自判阳/判阴，且给出稳定机器码（compare.py 靠它对照）
2. 轨迹模式过期时**必须报**，不能静默放行（proc_unrecognized_trail）
3. 控制台判定 / 退出码 / 报告表格用的是**同一个** `passed()`，不会各算一套
"""

from __future__ import annotations

from evals.checks import Query
from evals.compare import _codes
from evals.runner import passed, verdict_line
from evals.verify import (
    tool_sequence,
    verify_all,
    verify_process,
    verify_quality,
    verify_result,
)

GOOD = """# 成都 3 日
## Day 1 宽窄巷子
| 时间 | 地点 |
| --- | --- |
| 上午 | 宽窄巷子 |
## Day 2 大熊猫基地
## Day 3 都江堰
参考来源
""" + "内容" * 400

Q = Query(id="t", text="成都3天", cities=["成都"], min_days=3)

TRAIL = [
    "正在理解你的旅行需求…",
    "已获取高德实时数据（天气 + 景点）",
    "正在小红书搜索：成都 攻略",
    "正在综合多个来源，生成攻略…",
]


# ---------- 第一层：结果 ----------

def test_result_passes_when_days_cities_and_sources_present():
    r = verify_result(GOOD, {"sources": [{"site": "xhs"}]}, Q)
    assert r.passed
    assert r.codes == []
    assert r.evidence["days_covered"] == [1, 2, 3]


def test_result_flags_missing_day_city_and_zero_sources():
    r = verify_result("# 重庆\n## Day 1\n## Day 2\n", {"sources": []}, Q)
    assert not r.passed
    assert "res_missing_days" in r.codes
    assert "res_missing_cities" in r.codes
    assert "res_no_sources" in r.codes


def test_result_flags_truncation():
    r = verify_result(GOOD + "\n（内容触及长度上限）", {"sources": [{"site": "web"}]}, Q)
    assert not r.passed
    assert "res_truncated" in r.codes


# ---------- 第二层：过程 ----------

def test_tool_sequence_collapses_repeats_and_keeps_order():
    seq = tool_sequence(TRAIL + ["正在小红书搜索：成都 美食"])
    assert seq == ["parse_request", "amap_city_brief", "xhs_search", "generate_guide",
                   "xhs_search"]


def test_process_passes_on_healthy_trail():
    r = verify_process(TRAIL, {"sources": [{"site": "xhs"}]}, Q)
    assert r.passed, r.reason
    assert r.codes == []


def test_process_flags_reuse_then_skipping_web_search():
    trail = ["复用了上轮的小红书资料", "跳过网页搜索", "正在生成你的旅行方案"]
    r = verify_process(trail, {"sources": [{"site": "xhs"}]}, Q)
    assert not r.passed
    assert "proc_reuse_skipped_web" in r.codes


def test_process_flags_unfounded_risk_control_attribution():
    r = verify_process([*TRAIL, "携程触发风控，跳过"], {"sources": [{"site": "xhs"}]}, Q)
    assert "proc_unfounded_riskcontrol" in r.codes


def test_process_flags_clarifying_when_destination_is_explicit():
    r = verify_process([*TRAIL, "你想去哪里呢？"], {"sources": [{"site": "xhs"}]}, Q)
    assert "proc_clarify_with_destination" in r.codes


def test_process_flags_waypoint_round_reusing_sources():
    q = Query(id="w", text="路上", category="waypoint", cities=["西安"])
    r = verify_process(["复用了上轮的小红书资料", "正在生成你的旅行方案"],
                       {"sources": [{"site": "xhs"}]}, q)
    assert "proc_waypoint_reused" in r.codes


def test_process_flags_no_content_source():
    r = verify_process(TRAIL, {"sources": [{"site": "amap"}]}, Q)
    assert "proc_no_content_source" in r.codes


# ---- 修复 4：模式过期必须报，不能静默通过 ----

def test_process_flags_unrecognized_trail_instead_of_silently_passing():
    """进度文案被改掉后，_STEP_PATTERNS 全落空——这一层已失效，必须红。"""
    stale = ["正在琢磨你的需求…", "正在翻小红书…", "正在写方案…", "快好了…"]
    r = verify_process(stale, {"sources": [{"site": "xhs"}]}, Q)
    assert not r.passed, "轨迹一条都没匹配上却判通过 = 过程验证静默失效"
    assert "proc_unrecognized_trail" in r.codes


def test_short_trail_does_not_trigger_stale_pattern_alarm():
    """轮次太短时轨迹本来就可能识别不出东西，不该误报。"""
    r = verify_process(["正在琢磨…"], {"sources": [{"site": "xhs"}]}, Q)
    assert "proc_unrecognized_trail" not in r.codes


def test_partially_stale_patterns_warn_without_failing():
    trail = ["正在理解你的旅行需求…", "已获取高德实时数据（天气 + 景点）", "正在写方案…"]
    r = verify_process(trail, {"sources": [{"site": "xhs"}]}, Q)
    assert r.passed
    assert r.warnings and "generate_guide" in r.warnings[0]


# ---------- 第三层：质量 ----------

def test_quality_is_dimension_wise_not_a_single_score():
    r = verify_quality(GOOD, Q)
    assert r.passed
    assert r.evidence["排版完整性"] == "PASS"


def test_quality_maps_findings_to_dimensions_with_codes():
    bad = GOOD.replace("## Day 1 宽窄巷子", "## Day 1 宽窄巷子，**火锅")
    r = verify_quality(bad, Q)
    assert not r.passed
    assert "qual_排版完整性" in r.codes
    assert r.evidence["排版完整性"].startswith("FAIL")


# ---------- 闸门一致性（修复 2） ----------

def _row(**kw) -> dict:
    row = {"id": "t", "findings": [], "metrics": {}}
    row.update(kw)
    return row


def test_process_only_failure_fails_the_gate():
    """核心回归：质量层干净、过程层挂了，闸门必须红。

    修复前 `errs` 只看 findings，这种情况会打印「✓ 三层验证通过」且退出码 0。
    """
    r = _row(findings=[], verification={"passed": False, "failed_layers": ["process"],
                                        "codes": ["proc_reuse_skipped_web"], "warnings": []})
    assert not passed(r)
    line = verdict_line(r)
    assert "✗" in line and "过程" in line and "proc_reuse_skipped_web" in line


def test_clean_run_passes_the_gate():
    r = _row(verification={"passed": True, "failed_layers": [], "codes": [], "warnings": []})
    assert passed(r)
    assert verdict_line(r) == "✓ 三层验证通过"


def test_quality_finding_still_fails_the_gate():
    r = _row(findings=[{"code": "broken_table", "level": "error", "detail": ""}],
             verification={"passed": False, "failed_layers": ["quality"],
                           "codes": ["qual_排版完整性"], "warnings": []})
    assert not passed(r)


def test_warn_level_finding_does_not_fail_the_gate():
    r = _row(findings=[{"code": "no_sources", "level": "warn", "detail": ""}],
             verification={"passed": True, "failed_layers": [], "codes": [], "warnings": []})
    assert passed(r)


def test_legacy_snapshot_without_verification_falls_back():
    """接入三层之前的老快照没有 verification 字段，不能因此崩掉或误判。"""
    assert passed(_row(verified=True))
    assert not passed(_row(verified=False))


def test_verify_all_aggregates_layers():
    v = verify_all(GOOD, {"sources": [{"site": "xhs"}]}, TRAIL, Q)
    assert v["passed"]
    assert set(v["layers"]) == {"result", "process", "quality"}


# ---------- 对照闸门涵盖过程层（修复 3） ----------

def test_compare_codes_include_process_layer():
    """修复前 compare 只读 findings，过程层回归进不了前后对照。"""
    r = _row(verification={"passed": False, "failed_layers": ["process"],
                           "codes": ["proc_reuse_skipped_web"], "warnings": []})
    assert "proc_reuse_skipped_web" in _codes(r)


def test_compare_codes_exclude_quality_dims_to_avoid_double_counting():
    """qual_* 是 findings 的重新归类，纳入会把同一个问题数两遍。"""
    r = _row(findings=[{"code": "broken_table", "level": "error", "detail": ""}],
             verification={"passed": False, "failed_layers": ["quality"],
                           "codes": ["qual_排版完整性"], "warnings": []})
    assert _codes(r) == {"broken_table"}
