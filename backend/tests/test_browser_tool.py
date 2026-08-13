"""BrowserTool 纯逻辑单测 —— 对应 docs/test_cases 用例 6（截断）及辅助方法"""

from app.config import settings
from app.tools.browser_tool import BrowserTool


class TestSnapshotTruncation:
    """用例 6：超长页面截断逻辑生效"""

    def test_long_snapshot_truncated(self):
        long_text = "x" * (settings.max_snapshot_chars + 5000)
        result = BrowserTool._snapshot_to_text(long_text)
        assert len(result) <= settings.max_snapshot_chars + 20
        assert result.endswith("[截断]")

    def test_short_snapshot_untouched(self):
        short = "uid=1_0 RootWebArea \"test\""
        assert BrowserTool._snapshot_to_text(short) == short


class TestTitleUrlExtraction:
    def test_rootwebarea_title(self):
        snap = 'uid=2_0 RootWebArea "东京都_百度百科"\n  uid=2_1 heading "东京都"'
        title, url = BrowserTool._extract_title_url(snap, "https://fallback.example")
        assert title == "东京都_百度百科"
        assert url == "https://fallback.example"

    def test_page_title_header_format(self):
        snap = "Page Title: Tokyo Guide\nPage URL: https://example.com/tokyo"
        title, url = BrowserTool._extract_title_url(snap, "https://fallback.example")
        assert title == "Tokyo Guide"
        assert url == "https://example.com/tokyo"


class TestLocateUid:
    def test_exact_text_match(self):
        snap = 'uid=3_7 link "查看酒店详情" /hotel/123\nuid=3_8 link "下一页" /page/2'
        result = BrowserTool._locate_uid(snap, "下一页")
        assert result is not None
        assert result[0] == "3_8"
        assert result[1] == "下一页"

    def test_no_match_returns_none(self):
        snap = 'uid=3_7 link "查看酒店详情" /hotel/123'
        assert BrowserTool._locate_uid(snap, "不存在的按钮") is None


class Test360Fallback:
    """必应限流时的 360 搜索兜底：自家内容服务过滤（Phase 6.5）"""

    def test_link_redirect_kept(self):
        assert BrowserTool._is_360_self_service("https://www.so.com/link?m=abc") is False

    def test_self_services_skipped(self):
        for url in (
            "https://wenku.so.com/s?q=x",
            "https://wenda.so.com/q/137733",
            "https://ai.so.com/search/so918",
            "https://xinwen.so.com/detail?x=1",
            "https://www.so.com/s?q=开封",  # 搜索页自身
        ):
            assert BrowserTool._is_360_self_service(url) is True

    def test_external_sites_kept(self):
        assert BrowserTool._is_360_self_service("https://zhuanlan.zhihu.com/p/1") is False
        assert BrowserTool._is_360_self_service("https://baike.baidu.com/item/x") is False



class TestQueryMatches:
    """搜索结果与查询的对应性校验（Phase 28.1）：必应限流返回垃圾页/旧 DOM 时，
    搜索框值为空或是别的词——这批结果必须丢弃走重试/360 兜底（此前只写了注释没写代码，
    线上搜「商丘古城」混进 Doomworld 论坛）。"""

    def test_matching_query_accepted(self):
        assert BrowserTool._query_matches("商丘旅游攻略 必去景点", "商丘旅游攻略 必去景点 美食推荐") is True

    def test_rewritten_but_overlapping_accepted(self):
        assert BrowserTool._query_matches("商丘旅游攻略", "商丘旅游攻略") is True

    def test_empty_box_rejected(self):
        assert BrowserTool._query_matches("", "商丘旅游攻略") is False
        assert BrowserTool._query_matches(None, "商丘旅游攻略") is False

    def test_unrelated_box_rejected(self):
        assert BrowserTool._query_matches("doom wads download", "商丘古城 旅游攻略") is False

    def test_short_query_passes_through(self):
        assert BrowserTool._query_matches("whatever", "x") is True  # 无 ≥2 长度词元，放行


class TestCtripCityResolve:
    """携程城市 ID 动态解析（Phase 8）：建议接口 JS 构造"""

    def test_city_injected_safely(self):
        js = BrowserTool._city_suggest_js('开封')
        assert '"开封"' in js and 'getHotelKeywords' in js

    def test_city_with_quotes_escaped(self):
        js = BrowserTool._city_suggest_js('a"b')
        assert '\\"' in js  # json.dumps 转义，不会截断 JS 字符串


class TestCaptchaMarkers:
    """滑块验证码文案特征快判（不依赖 URL / LLM）"""

    def test_baidu_slider_text_detected(self):
        import asyncio
        b = BrowserTool(chrome=None)
        t = asyncio.run(b._detect_page_type(
            "https://baike.baidu.com/item/x", "百度安全验证 请完成下方验证后继续操作 拖动滑块使图片为正"))
        assert t == "captcha"

    def test_wappass_url_detected(self):
        import asyncio
        b = BrowserTool(chrome=None)
        t = asyncio.run(b._detect_page_type("https://wappass.baidu.com/static/captcha/x.html", ""))
        assert t == "captcha"
