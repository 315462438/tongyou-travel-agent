"""Phase 76：漏斗报告脚本的纯函数。"""

from scripts.funnel_report import _pct, _quantile, classify_first_reply


def test_classify_candidates_first():
    """Phase 76 之后区域型提问应落在「候选卡」，这是判断改造是否生效的关键指标。"""
    assert classify_first_reply("帮你圈了几个方向：", {"candidates": [{"name": "池州"}]}) == "候选卡"


def test_classify_clarify_vs_guide():
    assert classify_first_reply("请问您想去合肥周边的哪个城市？", {}) == "反问"
    assert classify_first_reply("# 芜湖两日游\n" + "正文" * 300, {}) == "攻略"


def test_classify_failures():
    assert classify_first_reply("", {}) == "空回复"
    assert classify_first_reply("已停止本轮。", {}) == "被停止"
    assert classify_first_reply("短短的一段回答", {}) == "很短"


def test_classify_long_question_is_not_clarify():
    """>60 字的问句是正常回答里带了问号，不能算追问（追问判据是「短且以问号结尾」）。"""
    assert classify_first_reply("这段回答很长" * 20 + "你觉得呢？", {}) == "很短"
    assert classify_first_reply("这段回答很长" * 80 + "你觉得呢？", {}) == "攻略"


def test_quantile_and_pct():
    assert _quantile([1, 2, 3, 4, 5], 0.5) == 3
    assert _quantile([], 0.5) == 0.0
    assert _pct(1, 4) == "25%"
    assert _pct(0, 0) == "—"
