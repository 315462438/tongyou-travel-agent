"""导航超时不再盲目重试（Phase 99）单测。全离线，无 Chrome、无 LLM。

背景：线上实测两轮 guide 各出现一个 ~62s 的 open_page span——正是「30s 超时 +
盲目重试再烧 30s」的痕迹。且重导航会把已部分加载的页面重置掉，双输。
现在按失败类型分流：超时 → 不重导航、snapshot 兜底；非超时（CDP 抖动）→ 维持重试。
"""

import asyncio

import pytest

from app.tools.browser_tool import BrowserTool, _looks_like_timeout


class FakeChrome:
    """按方法名脚本化返回/抛错，并记录 navigate 调用次数。"""

    def __init__(self, navigate_effects):
        # navigate_effects: 依次消费的效果列表；异常实例=抛出，其他=正常返回
        self.navigate_effects = list(navigate_effects)
        self.navigate_calls = 0

    async def call(self, method, params=None):
        if method == "navigate_page":
            self.navigate_calls += 1
            effect = self.navigate_effects.pop(0) if self.navigate_effects else None
            if isinstance(effect, BaseException):
                raise effect
            return effect
        if method == "wait_for":
            return None
        if method == "take_snapshot":
            return 'uid=1_0 RootWebArea "商丘古城攻略"\n  uid=1_1 StaticText "古城很好逛，门票免费。"'
        raise AssertionError(f"意料外的调用 {method}")


@pytest.fixture()
def tool(monkeypatch):
    def make(navigate_effects):
        chrome = FakeChrome(navigate_effects)
        t = BrowserTool(chrome=chrome)
        # 离线化：URL 校验放行（它会做真实 DNS 解析）、页面类型判定固定为 content（否则走 LLM）
        monkeypatch.setattr("app.tools.browser_tool.ensure_safe_url", lambda url: None)

        async def fake_detect(self, url, text_head):
            return "content"

        monkeypatch.setattr(BrowserTool, "_detect_page_type", fake_detect)
        return t, chrome
    return make


def test_timeout_skips_retry_and_salvages_via_snapshot(tool):
    """核心：超时只导航一次，仍走 snapshot 拿内容——最坏 62s 降到 ~32s，还可能救回正文。"""
    t, chrome = tool([TimeoutError()])
    result = asyncio.run(t.open_page("https://example.org/slow"))
    assert chrome.navigate_calls == 1, "超时不该重导航"
    assert result.status == "ok"
    assert "古城很好逛" in result.text  # 部分加载的页面被 snapshot 救回


def test_timeout_by_message_also_skips_retry(tool):
    """MCP 侧的超时常以普通异常 + 消息文本出现，不是 TimeoutError 实例。"""
    t, chrome = tool([RuntimeError("Navigation timed out after 30000ms")])
    result = asyncio.run(t.open_page("https://example.org/slow"))
    assert chrome.navigate_calls == 1
    assert result.status == "ok"


def test_transient_error_still_retries_once(tool):
    """非超时（CDP 抖动/连接断）保留重试——那才是当初加这行的合理场景，别一起砍。"""
    t, chrome = tool([RuntimeError("CDP connection lost"), None])
    result = asyncio.run(t.open_page("https://example.org/a"))
    assert chrome.navigate_calls == 2
    assert result.status == "ok"


def test_transient_error_twice_still_propagates(tool):
    """重试也失败：异常照旧冒泡（不吞），上层的自愈/降级逻辑依赖它。"""
    t, chrome = tool([RuntimeError("CDP lost"), RuntimeError("CDP lost again")])
    with pytest.raises(RuntimeError, match="again"):
        asyncio.run(t.open_page("https://example.org/a"))
    assert chrome.navigate_calls == 2


def test_success_navigates_exactly_once(tool):
    t, chrome = tool([None])
    result = asyncio.run(t.open_page("https://example.org/ok"))
    assert chrome.navigate_calls == 1
    assert result.status == "ok"


# ---------- 判别函数 ----------

@pytest.mark.parametrize("err,expect", [
    (TimeoutError(), True),                                # str 为空也要认出来
    (asyncio.TimeoutError(), True),
    (RuntimeError("Navigation timed out after 30000ms"), True),
    (RuntimeError("Timeout while waiting for page"), True),
    (RuntimeError("navigate TIMEOUT hit"), True),           # 大小写无关
    (RuntimeError("CDP connection lost"), False),
    (ValueError("target closed"), False),
    (Exception(""), False),                                 # 识别不出来 → 保留重试，不会更差
])
def test_looks_like_timeout(err, expect):
    assert _looks_like_timeout(err) is expect
