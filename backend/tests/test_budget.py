"""Phase 67 预算面板：汇总/归一/兜底的离线单测（不打 LLM、不连网、不落库）。"""

from app.agent.budget import build_budget_payload
from app.schemas.budget_schema import BudgetData, BudgetLine, ReservationItem


def _data(**kw) -> BudgetData:
    kw.setdefault("items", [])
    return BudgetData(**kw)


def _line(category="门票", name="某景点", amount=100.0, day=0, note="") -> BudgetLine:
    return BudgetLine(category=category, name=name, amount=amount, day=day, note=note)


def test_total_is_recomputed_server_side():
    """总额来自逐项求和，不采信模型（schema 里根本没有 total 字段）。"""
    p = build_budget_payload(
        _data(items=[_line(amount=30), _line(amount=54), _line(amount=120)])
    )
    assert p["total"] == 204.0
    assert sum(i["amount"] for i in p["items"]) == p["total"]


def test_category_normalized_and_summed():
    """同义词归一到规范类别后再汇总。"""
    p = build_budget_payload(
        _data(
            items=[
                _line(category="机票", name="往返机票", amount=800),
                _line(category="高铁", name="城际高铁", amount=200),
                _line(category="地铁", name="市内通勤", amount=50),
                _line(category="民宿", name="住2晚", amount=600),
            ]
        )
    )
    cats = {c["category"]: c["amount"] for c in p["by_category"]}
    assert cats["大交通"] == 1000.0  # 机票 + 高铁
    assert cats["交通"] == 50.0
    assert cats["住宿"] == 600.0
    assert p["total"] == 1650.0


def test_unknown_category_falls_back_to_other():
    p = build_budget_payload(_data(items=[_line(category="玄学开销", amount=88)]))
    assert p["by_category"][0]["category"] == "其他"


def test_category_order_is_stable():
    """展示顺序固定（大交通→住宿→餐饮→门票→交通→其他），与金额无关。"""
    p = build_budget_payload(
        _data(
            items=[
                _line(category="其他", amount=999),
                _line(category="门票", amount=10),
                _line(category="大交通", amount=1),
            ]
        )
    )
    assert [c["category"] for c in p["by_category"]] == ["大交通", "门票", "其他"]


def test_pct_sums_to_about_100():
    p = build_budget_payload(
        _data(items=[_line(category="住宿", amount=750), _line(category="餐饮", amount=250)])
    )
    assert abs(sum(c["pct"] for c in p["by_category"]) - 100.0) < 0.2


def test_total_lines_are_dropped():
    """模型无视约束输出「合计」行时必须剔除，否则总额翻倍。"""
    p = build_budget_payload(
        _data(
            items=[
                _line(name="门票", amount=100),
                _line(name="住宿", amount=200),
                _line(name="合计", amount=300),
                _line(name="总预算", amount=300),
            ]
        )
    )
    assert p["total"] == 300.0
    assert len(p["items"]) == 2


def test_nonpositive_amounts_dropped():
    p = build_budget_payload(
        _data(items=[_line(amount=0), _line(amount=-50), _line(amount=100)])
    )
    assert len(p["items"]) == 1
    assert p["total"] == 100.0


def test_by_day_and_shared_split():
    """day=0 归为整趟通用（shared），不混进逐天汇总。"""
    p = build_budget_payload(
        _data(
            items=[
                _line(day=1, amount=100),
                _line(day=1, amount=50),
                _line(day=2, amount=80),
                _line(day=0, amount=800, category="大交通"),
            ]
        )
    )
    assert p["by_day"] == [{"day": 1, "amount": 150.0}, {"day": 2, "amount": 80.0}]
    assert p["shared"] == 800.0
    assert p["total"] == 1030.0


def test_group_total_uses_headcount():
    p = build_budget_payload(_data(headcount=3, items=[_line(amount=500)]))
    assert p["total"] == 500.0  # 人均
    assert p["group_total"] == 1500.0


def test_headcount_never_below_one():
    p = build_budget_payload(_data(headcount=0, items=[_line(amount=10)]))
    assert p["headcount"] == 1
    assert p["group_total"] == 10.0


def test_empty_guide_yields_empty_payload():
    """攻略没写预算 → 空明细（调用方据此给友好提示，而不是编数字）。"""
    p = build_budget_payload(_data())
    assert p["items"] == []
    assert p["total"] == 0.0
    assert p["by_category"] == []


def test_reservations_kept_and_blank_names_dropped():
    p = build_budget_payload(
        _data(
            items=[_line(amount=10)],
            reservations=[
                ReservationItem(name="故宫博物院", channel="官方公众号", advance="提前7天"),
                ReservationItem(name="  "),  # 无名项丢弃
            ],
        )
    )
    assert len(p["reservations"]) == 1
    assert p["reservations"][0]["name"] == "故宫博物院"
    assert p["reservations"][0]["advance"] == "提前7天"


def test_notes_capped_at_three():
    p = build_budget_payload(
        _data(items=[_line(amount=10)], notes=["a", "b", "c", "d", " "])
    )
    assert p["notes"] == ["a", "b", "c"]


def test_blank_item_name_gets_placeholder():
    p = build_budget_payload(_data(items=[_line(name="   ", amount=20)]))
    assert p["items"][0]["name"] == "未命名开销"


def test_negative_day_clamped():
    p = build_budget_payload(_data(items=[_line(day=-3, amount=20)]))
    assert p["items"][0]["day"] == 0
    assert p["shared"] == 20.0
