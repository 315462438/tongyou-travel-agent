"""Phase 68：小红书 MCP 只读工具白名单。

该 MCP 是第三方镜像，除了搜索/详情还暴露 publish_content、post_comment_to_feed、
like_feed、delete_cookies 等写操作；而登录态是**全平台共享的单个运维账号**。
白名单保证任何写操作在结构上不可能被调用。全部离线。
"""

import asyncio

import pytest

from app.tools import xhs_mcp


WRITE_TOOLS = [
    "publish_content",
    "publish_with_video",
    "post_comment_to_feed",
    "reply_comment_in_feed",
    "like_feed",
    "favorite_feed",
    "delete_cookies",
]


@pytest.mark.parametrize("tool", WRITE_TOOLS)
def test_write_tools_rejected(tool):
    """写操作一律拒绝，且在**发起连接之前**就拒绝（不碰网络）。"""
    with pytest.raises(xhs_mcp.XHSToolNotAllowed):
        asyncio.run(xhs_mcp._call_tool(tool, {}))


def test_unknown_tool_rejected():
    with pytest.raises(xhs_mcp.XHSToolNotAllowed):
        asyncio.run(xhs_mcp._call_tool("some_new_tool", {}))


def test_whitelist_is_exactly_readonly_pair():
    """白名单必须保持最小：只有搜索和详情两个只读工具。"""
    assert xhs_mcp._READONLY_TOOLS == frozenset({"search_feeds", "get_feed_detail"})


def test_rejection_happens_before_network(monkeypatch):
    """确认拒绝发生在建连之前——即使 MCP 地址配了也不会发出任何请求。"""
    called = {"n": 0}

    def _boom(*a, **kw):
        called["n"] += 1
        raise AssertionError("不应该建立连接")

    monkeypatch.setattr("mcp.client.streamable_http.streamablehttp_client", _boom)
    with pytest.raises(xhs_mcp.XHSToolNotAllowed):
        asyncio.run(xhs_mcp._call_tool("publish_content", {"title": "x"}))
    assert called["n"] == 0


def test_production_call_sites_use_whitelisted_tools_only():
    """源码级检查：_call_tool 的调用点只能出现白名单里的字面量工具名。"""
    import inspect
    import re

    src = inspect.getsource(xhs_mcp)
    # 抓 _call_tool("xxx" 形式的字面量首参（排除定义处）
    names = set(re.findall(r'_call_tool\(\s*"([a-z_]+)"', src))
    assert names, "没找到 _call_tool 调用点，检查正则是否失效"
    assert names <= xhs_mcp._READONLY_TOOLS, f"存在白名单外的调用：{names - xhs_mcp._READONLY_TOOLS}"
