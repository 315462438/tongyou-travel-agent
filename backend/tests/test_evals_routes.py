"""路由分类评估集的单测（2026-08-14）。

不调 LLM——真跑分类是 `python -m evals.route_eval` 的事。这里测的是
**评分逻辑本身**和**数据集的自洽性**：一个把软错也算成通过的评分器，
会让报表永远好看。
"""

import pytest

from evals.route_eval import KINDS, RouteCase, grade, load_cases, summarize


# ---------- 评分 ----------

def test_exact_match_is_a_hit():
    c = RouteCase(id="x", text="帮我规划厦门三天", expect="guide")
    assert grade(c, "guide") == "hit"


def test_tolerated_downgrade_is_soft_not_hard():
    """ROUTE_SYSTEM 自己写着「拿不准一律 guide」，research→guide 是设计允许的降级。
    把它算硬错会逼着我们去「优化」一个本来就正确的行为。"""
    c = RouteCase(id="x", text="厦门和青岛哪个适合带娃", expect="research", tolerate=["guide"])
    assert grade(c, "guide") == "soft"


def test_untolerated_miss_is_hard():
    """guide 被判成 direct = 该联网查的没查，用户拿到一段编的回答。"""
    c = RouteCase(id="x", text="现在稻城亚丁封山了吗", expect="guide")
    assert grade(c, "direct") == "hard"


def test_soft_errors_do_not_count_as_hits():
    """软错是「可接受」，不是「答对了」——严格准确率必须把它排除在外，
    否则数据集会慢慢退化成一堆 tolerate 全开的送分题。"""
    results = [
        {"expect": "research", "got": "guide", "grade": "soft", "stable": True},
        {"expect": "guide", "got": "guide", "grade": "hit", "stable": True},
    ]
    s = summarize(results)
    assert s["hit"] == 1 and s["soft"] == 1
    assert s["accuracy"] == 0.5


def test_run_errors_never_masquerade_as_a_classification():
    """**立集当天真踩的坑**：生产的 `decide_route` 把 API 异常吞成 guide 兜底，
    评估若直接调它，一次断网会长得和「模型判成 guide」一模一样。

    当时 35 条全断网，报表打出「严格准确率 42.9%」——一个完全由连接失败构成、
    却非常像「模型偏向 guide」的假结论。所以跑挂必须是独立的 error 档。
    """
    c = RouteCase(id="x", text="随便", expect="direct")
    assert grade(c, "run_error") == "error"

    results = [
        {"id": "a", "expect": "direct", "got": "direct", "grade": "hit", "stable": True},
        {"id": "b", "expect": "guide", "got": "run_error", "grade": "error", "stable": True},
    ]
    s = summarize(results)
    assert s["errors"] == 1 and s["error_ids"] == ["b"]
    # 分母是「跑成了的条数」——把断网摊进分母会凭空造出一个「变差了」的结论
    assert s["scored"] == 1 and s["accuracy"] == 1.0
    assert "run_error" not in s["confusion"]["guide"]


def test_unstable_cases_are_listed_separately():
    """摇摆比稳定判错更危险：稳定错能一次修掉，摇摆的会随机复发。"""
    results = [{"id": "flaky", "expect": "direct", "got": "direct",
                "grade": "hit", "stable": False}]
    assert summarize(results)["unstable"] == ["flaky"]


def test_confusion_matrix_counts_by_expected_class():
    results = [
        {"expect": "direct", "got": "guide", "grade": "hard", "stable": True},
        {"expect": "direct", "got": "direct", "grade": "hit", "stable": True},
    ]
    assert summarize(results)["confusion"]["direct"] == {"guide": 1, "direct": 1}


# ---------- 数据集自洽 ----------

def test_routes_yaml_is_well_formed():
    cases = load_cases()
    assert len(cases) >= 30, "样本太少，混淆矩阵没有统计意义"
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)), "id 重复"
    for c in cases:
        assert c.expect in KINDS, f"{c.id} 的 expect 不合法：{c.expect}"
        assert c.expect not in c.tolerate, f"{c.id} 把期望值又写进了 tolerate"
        assert set(c.tolerate) <= set(KINDS), f"{c.id} 的 tolerate 有非法值"
        assert c.note, f"{c.id} 没写「守什么边界」"
        assert c.text.strip(), f"{c.id} 没有用户原话"


def test_every_route_class_is_covered():
    """三个通道都要有足够样本，否则混淆矩阵有一行是空的。"""
    from collections import Counter

    tally = Counter(c.expect for c in load_cases())
    for k in KINDS:
        assert tally[k] >= 5, f"{k} 只有 {tally[k]} 条样本，太少"


def test_no_case_tolerates_every_other_route():
    """防数据集退化：一条用例若把另外两个通道都列进 tolerate，它就**恒真**了——
    永远不可能报错，留在集里只会稀释信号。宁可删掉这条，也不留一道送分题。
    （立集时 `周末想出去玩有什么推荐` 就是这样一条，已删。）"""
    for c in load_cases():
        others = set(KINDS) - {c.expect}
        assert not others <= set(c.tolerate), f"{c.id} 的 tolerate 覆盖了全部通道，恒真"
