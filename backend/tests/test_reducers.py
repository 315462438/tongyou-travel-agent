"""工具输出按结构裁剪（Phase 96）单测。

真实样本在 `tests/fixtures/pages/`（gzip，见那里的 README）。全离线、无网络、无 LLM。

这些用例的共同关切不是「压缩率好看」，而是**别把正文吃掉**——那类 bug 是静默的
（产出看起来正常，只是内容少了）。开发期真机数据上踩到过三次，每次都在下面留了用例。
"""

import gzip
import pathlib

import pytest

from app.agent.reducers import (
    Reduction,
    looks_like_a11y,
    looks_like_html,
    naive_text,
    note,
    reduce_a11y,
    reduce_auto,
    reduce_html,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "pages"


def _fixture(name: str) -> str:
    path = FIXTURES / f"{name}.gz"
    if not path.exists():  # 样本缺失时跳过而不是失败——缺样本是环境问题，不是代码回归
        pytest.skip(f"缺少样本 {path}")
    return gzip.open(path, "rt", encoding="utf-8", errors="ignore").read()


# ==================== HTML 裁剪 ====================

def test_wikipedia_chrome_is_gone_from_the_window():
    """核心用例：改造前 4000 字窗口里 3566 字是主菜单和目录，正文只剩 434 字。

    这是整个改动的理由——位置截断的问题不是「丢了后面」，是**前面全是导航**。
    """
    html = _fixture("wikipedia_xihu.html")
    before, after = naive_text(html)[:4000], reduce_html(html).text[:4000]

    for chrome in ("互助客栈", "开关沿革子章节", "维基社群", "随机条目"):
        assert chrome in before, f"样本已漂移：改造前的窗口里本应有 {chrome}"
        assert chrome not in after, f"{chrome} 没被剔除"

    # 正文必须还在（且现在能挤进窗口）
    assert "西湖位于中华人民共和国浙江省杭州旧城西侧" in after
    assert "苏堤" in after and "白堤" in after


def test_ctrip_navigation_dropped_content_kept():
    html = _fixture("ctrip_travels.html")
    out = reduce_html(html).text
    for chrome in ("特价机票", "航班动态", "企业商旅", "联系客服"):
        assert chrome not in out
    assert "杭州蓝之莲酒店美好下午茶时光" in out  # 游记标题保留


def test_qunar_is_not_wikipedia_overfit():
    """第二个站点：规则是通用的标签/命名，不含站点特判。"""
    html = _fixture("qunar_hangzhou.html")
    r = reduce_html(html)
    assert r.kind == "html"
    assert r.dropped > 0
    assert len(r.text) < len(naive_text(html))


def test_html_entities_are_decoded():
    """`&#91; 註 1 &#93;` 是同一段文字的转义形态，解码是无损还原（「只删不改」的唯一例外）。"""
    out = reduce_html("<html><body><p>西湖 &#91;1&#93; &amp; 雷峰塔</p></body></html>").text
    assert "&#91;" not in out and "&amp;" not in out
    assert "雷峰塔" in out


def test_reference_marks_dropped():
    out = reduce_html("<html><body><p>西湖[12]很美[註 3]。</p></body></html>").text
    assert "[12]" not in out and "[註 3]" not in out
    assert "西湖" in out and "很美" in out


# ---------- 「别把正文吃掉」的三道防线（每条都对应真机踩到的 bug） ----------

def test_root_element_attributes_never_drop_the_document():
    """真机 bug #1：维基的 <html class="...-toc-pinned-..."> 命中 chrome 规则 → 整页归零。

    根元素的 class 是页面级特性开关，跟「这块是不是导航」毫无关系。
    """
    html = ('<html class="vector-feature-toc-pinned-clientpref-1">'
            "<body><p>西湖是中国大陆首批国家重点风景名胜区。</p></body></html>")
    r = reduce_html(html)
    assert "西湖是中国大陆首批国家重点风景名胜区" in r.text
    assert r.kind == "html"


def test_undershoot_falls_back_instead_of_returning_a_husk():
    """真机 bug #2 的防线：某条规则误伤整块正文时，退回朴素提取而不是交出空壳。

    这类 bug 是**静默**的，必须有自动检测。真实数据上它在小红书网页版（JS 空壳）
    和携程景点页上真的触发过。
    """
    # 正文全被包在会被丢弃的容器里 —— 模拟规则误伤
    html = "<html><body><div class='sidebar'>" + "正文内容。" * 400 + "</div></body></html>"
    r = reduce_html(html)
    assert r.kind == "html_undershoot_fallback"
    assert "正文内容" in r.text


def test_js_shell_page_is_not_mangled():
    """JS 空壳页（正文全在脚本里）不该被裁成空。"""
    html = "<html><head><script>var data={a:1}</script></head><body><div id='app'></div></body></html>"
    r = reduce_html(html)
    assert r.text is not None
    assert "var data" not in r.text  # script 内容仍要丢掉


# ==================== a11y 快照裁剪 ====================

@pytest.mark.parametrize("name,floor", [
    ("snapshot_qunar.txt", 0.60),
    ("snapshot_bing.txt", 0.40),
    ("snapshot_baike.txt", 0.50),
])
def test_real_snapshots_shrink_without_structural_leakage(name, floor):
    raw = _fixture(name)
    r = reduce_a11y(raw)
    assert r.kind == "a11y"
    assert r.ratio >= floor, f"{name} 只压了 {r.ratio:.0%}，低于预期 {floor:.0%}"
    for leak in ("uid=", 'level="', 'description="', "focusable", "RootWebArea",
                 "StaticText", "generic"):
        assert leak not in r.text, f"{name} 残留结构噪声 {leak}"


def test_snapshot_keeps_readable_content():
    raw = _fixture("snapshot_qunar.txt")
    out = reduce_a11y(raw).text
    assert "北京旅游攻略" in out


def test_attribute_values_are_not_mistaken_for_content():
    """真机 bug #3：`listitem "" level="1"` 把属性值 1 当成内容，满屏孤零零的「1」。

    节点 label 是**不以 `=` 开头**的那个引号段。
    """
    snap = 'uid=1_0 RootWebArea "页面"\n  uid=1_1 listitem "" level="1"\n  uid=1_2 link "登录"'
    out = reduce_a11y(snap).text
    assert "1" not in out.replace("页面", "").replace("登录", "")
    assert "登录" in out and "页面" in out


def test_parent_and_child_duplicate_text_collapses():
    """a11y 树里父 label 与子 StaticText 必然重复，这是最大的一块冗余。"""
    snap = ('uid=1_0 RootWebArea "站点"\n'
            '  uid=1_1 link "登录"\n'
            '    uid=1_2 StaticText "登录"\n')
    assert reduce_a11y(snap).text.count("登录") == 1


def test_structural_nodes_without_labels_are_dropped():
    snap = 'uid=1_0 RootWebArea "站点"\n  uid=1_1 generic ""\n    uid=1_2 list ""\n'
    out = reduce_a11y(snap).text
    assert "站点" in out
    assert "generic" not in out and "list" not in out


# ==================== 不变式 ====================

@pytest.mark.parametrize("name", [
    "wikipedia_xihu.html", "ctrip_travels.html", "qunar_hangzhou.html",
])
def test_html_reduction_is_idempotent(name):
    """链路里会多次截断，不幂等就会变成头尾拼盘（Phase 90 立的约束，换了下刀方式也得守）。"""
    once = reduce_html(_fixture(name)).text
    assert reduce_auto(once).text == once


@pytest.mark.parametrize("name", [
    "snapshot_qunar.txt", "snapshot_bing.txt", "snapshot_baike.txt",
])
def test_a11y_reduction_is_idempotent(name):
    """真机上踩过：裁剪产物已不含 uid/RootWebArea，第二遍会把没引号的行全丢光，只剩两行标题。"""
    once = reduce_a11y(_fixture(name)).text
    assert reduce_a11y(once).text == once


@pytest.mark.parametrize("name", ["qunar_hangzhou.html", "ctrip_travels.html"])
def test_reduced_text_invents_no_characters(name):
    """只删不改：裁剪后的每一段都必须能在朴素提取里找到。

    比较**忽略空白**——块级边界本来就会把空格换成换行，那是结构标注不是内容改动。
    这条用例真的抓到过一个 bug：相邻内联标签的文本被无分隔拼接（`清除<i>历史</i>记录`
    → `清除历史记录`），中文无害但英文会把 `Hotel`+`Booking` 粘成 `HotelBooking`。
    """
    html = _fixture(name)
    base = "".join(naive_text(html).split())
    for line in reduce_html(html).text.splitlines():
        chunk = "".join(line.split())
        if len(chunk) < 6:
            continue
        assert chunk in base, f"裁剪产出了原文里没有的内容：{chunk[:60]!r}"


# ==================== 识别与退化 ====================

def test_plain_text_and_json_pass_through_untouched():
    """认不得就别动——误把纯文本当 HTML 裁一遍，风险远大于不裁的收益。"""
    for src in ("就是一段普通的中文说明文字，没有任何标记。",
                '{"pois": [{"name": "西湖", "rating": 4.7}]}'):
        r = reduce_auto(src)
        assert r.text == src and r.dropped == 0 and r.kind == "plain"


def test_detectors():
    assert looks_like_html("<html><body><p>x</p></body></html>")
    assert not looks_like_html("普通文本 < 3 且 > 1")
    assert looks_like_a11y('uid=1_0 RootWebArea "x"')
    assert not looks_like_a11y("普通文本")


@pytest.mark.parametrize("junk", [
    "", "<", "<html", "<<<>>>", "\x00\x01\x02", "<p>" * 5000, "&#;&#x;&amp",
])
def test_malformed_input_never_raises(junk):
    """裁剪是增强，绝不能让抓取链路失败。"""
    for fn in (reduce_html, reduce_a11y, reduce_auto):
        assert isinstance(fn(junk), Reduction)


def test_empty_input():
    for fn in (reduce_html, reduce_a11y, reduce_auto):
        r = fn("")
        assert r.text == "" and r.kind == "empty"


# ==================== 留痕 ====================

def test_note_only_when_reduction_is_significant():
    assert note(Reduction("x", 0, "plain")) == ""
    assert note(Reduction("x" * 100, 5, "html")) == ""          # 只省 5%，不打扰模型
    assert "已按结构裁剪" in note(Reduction("x" * 100, 400, "html"))


def test_reduction_ratio():
    assert Reduction("x" * 25, 75, "html").ratio == 0.75
    assert Reduction("", 0, "empty").ratio == 0.0


# ==================== 接线（契约不变） ====================

def test_html_to_text_still_honors_limit():
    from app.agent.research_tools import _html_to_text

    assert len(_html_to_text("<p>" + "字" * 9000 + "</p>", limit=100)) == 100


def test_snapshot_to_text_still_truncates():
    from app.config import settings
    from app.tools.browser_tool import BrowserTool

    long_snap = 'uid=1_0 RootWebArea "x"\n' + "\n".join(
        f'  uid=1_{i} StaticText "内容{i}"' for i in range(settings.max_snapshot_chars)
    )
    out = BrowserTool._snapshot_to_text(long_snap)
    assert len(out) <= settings.max_snapshot_chars + 20
    assert out.endswith("[截断]")
