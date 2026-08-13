"""Phase 51 批5：实时数据可信度守卫单测（纯函数，固定 today，全离线）。"""

from datetime import date

from app.agent.realtime_guard import (
    credibility_directive,
    extract_travel_date,
    realtime_kind,
    resolve_date,
)

TODAY = date(2026, 7, 20)  # 周一


def test_realtime_kind():
    assert realtime_kind("帮我查成都的酒店价格") == "hotel"
    assert realtime_kind("订个民宿") == "hotel"
    assert realtime_kind("去成都的高铁票") == "transport"
    assert realtime_kind("查一下机票") == "transport"
    # 交通优先于酒店（都需日期，纪律一致）
    assert realtime_kind("订去成都的火车顺便看看酒店") == "transport"
    # 非实时类
    assert realtime_kind("成都有什么好玩的") == ""
    assert realtime_kind("帮我规划三天行程") == ""


def test_extract_date_explicit():
    assert extract_travel_date("我8月2号去", TODAY) == "2026-08-02"
    assert extract_travel_date("8月2日出发", TODAY) == "2026-08-02"
    assert extract_travel_date("2026-08-02 到", TODAY) == "2026-08-02"
    assert extract_travel_date("8-2 那天", TODAY) == "2026-08-02"
    # 过去的月份算明年
    assert extract_travel_date("1月5号", TODAY) == "2027-01-05"


def test_extract_date_relative():
    assert extract_travel_date("明天去", TODAY) == "2026-07-21"
    assert extract_travel_date("后天", TODAY) == "2026-07-22"
    assert extract_travel_date("大后天走", TODAY) == "2026-07-23"
    assert extract_travel_date("周末去玩", TODAY) == "2026-07-25"  # 周一→本周六
    assert extract_travel_date("周三出发", TODAY) == "2026-07-22"  # 周一→周三
    assert extract_travel_date("下周三", TODAY) == "2026-07-29"


def test_extract_date_none():
    assert extract_travel_date("帮我查酒店", TODAY) == ""
    assert extract_travel_date("", TODAY) == ""


def test_resolve_date_prefers_first():
    # 本轮无日期，回退上下文里的日期
    assert resolve_date("看看酒店", "上一轮说了8月2号去成都", today=TODAY) == "2026-08-02"
    assert resolve_date("明天", "8月2号", today=TODAY) == "2026-07-21"  # 本轮优先


def test_directive_no_date_hotel():
    d = credibility_directive("帮我查成都的酒店", today=TODAY)
    assert "参考价（非实时）" in d and "请用户补充具体日期" in d
    assert "携程" in d


def test_directive_with_date_transport():
    d = credibility_directive("查8月2号去成都的高铁", today=TODAY)
    assert "查询日期 2026-08-02" in d and "12306" in d


def test_directive_empty_for_non_realtime():
    assert credibility_directive("成都三天怎么安排", today=TODAY) == ""


def test_directive_uses_context_date():
    # 本轮只说「看酒店」，日期在上一轮上下文里
    d = credibility_directive("帮我看看酒店", context="用户8月2号去成都", today=TODAY)
    assert "查询日期 2026-08-02" in d
