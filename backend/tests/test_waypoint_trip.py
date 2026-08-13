"""沿途中转意图建模（2026-07-31，docs/task_plans/沿途中转意图建模-2026-07-31.md）。

线上踩坑：「合肥出发终点武汉，途经有什么可逛」被答成武汉城市攻略（含反方向的咸宁），
补充重问又因 destination 解析为空被反问。全部离线。
"""

from app.agent.orchestrator import _waypoint_directive, _xhs_query_plan
from app.schemas.chat_schema import Preference


def test_preference_new_fields_default():
    p = Preference()
    assert p.origin == ""
    assert p.waypoint_trip is False


def test_xhs_query_plan_waypoint_corridor():
    from app.config import settings

    p = Preference(destination="武汉", origin="合肥", waypoint_trip=True, interests=["古镇"])
    plan = _xhs_query_plan(p)
    assert plan == [("合肥到武汉 自驾 沿途 古镇", settings.xhs_notes_per_turn)]


def test_xhs_query_plan_waypoint_default_interest():
    p = Preference(destination="武汉", origin="合肥", waypoint_trip=True)
    ((q, _n),) = _xhs_query_plan(p)
    assert q == "合肥到武汉 自驾 沿途 古镇 景点"


def test_xhs_query_plan_waypoint_without_origin_falls_back():
    # origin 没解析出来 → 退回普通目的地查询，不生成畸形的「到武汉」查询
    p = Preference(destination="武汉", waypoint_trip=True)
    ((q, _n),) = _xhs_query_plan(p)
    assert q.startswith("武汉 旅游攻略")


def test_xhs_query_plan_normal_unchanged():
    p = Preference(destination="成都", interests=["美食"])
    ((q, _n),) = _xhs_query_plan(p)
    assert q == "成都 旅游攻略 美食"


def test_waypoint_directive_content():
    p = Preference(destination="武汉", origin="合肥", waypoint_trip=True)
    d = _waypoint_directive(p)
    assert "合肥 → 武汉" in d
    assert "顺路" in d and "车程" in d
    assert "不要展开写 武汉" in d


def test_waypoint_directive_empty_for_normal_turn():
    assert _waypoint_directive(Preference(destination="成都")) == ""
