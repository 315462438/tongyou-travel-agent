"""chrome-devtools-mcp 连接管理（评审 🔴1/🔴2）

- 通过 stdio 启动 chrome-devtools-mcp，--browser-url 连接用户已启动的调试 Chrome
- 带重连逻辑：连接失败抛 MCPConnectionError，由上层把任务标记 failed（不挂死）
"""

import asyncio
import threading
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config import settings


class MCPConnectionError(Exception):
    pass


# 进程级串行锁：多个 chrome-devtools-mcp 客户端同时连同一个常驻 Chrome 会互相
# 搞死对方的 CDP 会话（navigate 永久无响应，见 docs/pitfalls/
# MCP调用无超时导致任务永久挂起.md）。任一时刻只允许一个 MCP 会话存在。
# 用 threading.Lock 而非 asyncio.Lock：每个后台任务跑在自己线程的独立事件循环里。
_MCP_GLOBAL_LOCK = threading.Lock()


class ChromeMCP:
    """chrome-devtools-mcp 会话封装。用法：

    async with ChromeMCP() as chrome:
        await chrome.call("navigate_page", {"url": "https://example.com"})
        snapshot = await chrome.call("take_snapshot", {})
    """

    def __init__(self, browser_url: str | None = None, *, user_id: str = "", on_queue=None):
        self.user_id = user_id
        self.on_queue = on_queue  # 排队等待浏览器时的回调 on_queue(position)
        self._pool = None
        self._holds_pool = False
        # pool 模式下 browser_url 由 acquire 决定（延后到 __aenter__）
        self.browser_url = browser_url or settings.chrome_debug_url
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._holds_lock = False

    @property
    def _use_pool(self) -> bool:
        return settings.browser_pool_enabled and bool(self.user_id)

    async def __aenter__(self) -> "ChromeMCP":
        if self._use_pool:
            # 每用户浏览器池：acquire 拿到该用户独立 Chrome 的 url（池的 busy 即每用户串行）
            from app.tools.browser_pool import get_pool

            self._pool = get_pool()
            self.browser_url = await asyncio.to_thread(self._pool.acquire, self.user_id, self.on_queue)
            self._holds_pool = True
        else:
            # 全局串行：等上一个 MCP 会话彻底结束（在线程池里阻塞等待，不卡事件循环）
            await asyncio.to_thread(_MCP_GLOBAL_LOCK.acquire)
            self._holds_lock = True
        try:
            await self.connect()
        except BaseException:
            self._release_slot()
            raise
        return self

    async def __aexit__(self, *exc):
        try:
            await self.close()
        finally:
            self._release_slot()

    def _release_slot(self) -> None:
        if self._holds_pool:
            self._holds_pool = False
            if self._pool is not None:
                self._pool.release(self.user_id)
        if self._holds_lock:
            self._holds_lock = False
            _MCP_GLOBAL_LOCK.release()

    async def connect(self, retries: int = 2) -> None:
        # 两种模式：
        #  - chrome_executable 指定时：让 mcp 自己拉起 headless 浏览器（服务器部署）
        #  - 否则：连现成调试 Chrome（本地开发，共享登录态）
        args = ["-y", "chrome-devtools-mcp@0.6.0"]
        if settings.chrome_executable:
            # 不用 --isolated：持久 profile 保留登录态（Phase 5 扫码登录一次，
            # 后续任务直接带 cookie，不再反复弹登录卡）
            args += [
                "--headless=true",
                "--executablePath",
                settings.chrome_executable,
            ]
        else:
            args += ["--browser-url", self.browser_url]
        params = StdioServerParameters(command="npx", args=args)
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                if not settings.chrome_executable:
                    # 必须在 MCP 启动前确保浏览器有标签页：连接后再建 MCP 感知不到
                    await asyncio.to_thread(self._ensure_tab_via_http)
                self._stack = AsyncExitStack()
                read, write = await self._stack.enter_async_context(stdio_client(params))
                self._session = await self._stack.enter_async_context(ClientSession(read, write))
                await asyncio.wait_for(self._session.initialize(), timeout=30)
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
                await self.close()
                if attempt < retries:
                    await asyncio.sleep(2 * (attempt + 1))
        raise MCPConnectionError(
            f"无法连接 chrome-devtools-mcp（browser_url={self.browser_url}）。"
            f"请确认已用 scripts/start_chrome.sh 启动调试 Chrome。原始错误: {last_err}"
        )

    async def _restart_remote_browser(self) -> None:
        """杀掉僵死的常驻 Chrome，交给 systemd（Restart=always）拉起全新实例。"""
        import logging
        import subprocess
        from urllib.parse import urlparse

        port = urlparse(self.browser_url).port or 9222
        logging.getLogger(__name__).warning("remote browser wedged, killing chrome on :%s", port)
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["pkill", "-f", f"remote-debugging-port={port}"],
                timeout=10,
            )
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(6)  # 等 systemd 拉起新实例

    def _ensure_tab_via_http(self) -> None:
        """确保调试 Chrome 至少有一个标签页（必须在 MCP 启动前调用）。

        浏览器一个标签页都没有时，chrome-devtools-mcp 0.6.0 的**所有**工具
        （包括 new_page）都报 "No page selected"，且连接后再建标签页也感知不到，
        只能在启动 MCP 前用 Chrome 调试 HTTP 接口补一个（踩坑：docs/pitfalls/
        调试Chrome无标签页导致NoPageSelected.md）。
        """
        import json as _json
        import urllib.request

        # 本机 CDP 接口必须直连：环境里的 HTTP_PROXY 会把 127.0.0.1 也送进代理（502）
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(f"{self.browser_url}/json/list", timeout=5) as resp:
                targets = _json.loads(resp.read().decode())
            if any(t.get("type") == "page" for t in targets):
                return
            req = urllib.request.Request(
                f"{self.browser_url}/json/new?about:blank", method="PUT"
            )
            opener.open(req, timeout=5).read()
        except Exception:  # noqa: BLE001 — Chrome 不可达时留给 MCP 连接报错
            pass

    async def close(self) -> None:
        if self._stack is not None:
            try:
                await self._stack.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._stack = None
            self._session = None

    # 单次工具调用的兜底超时 + 三层自愈（见 docs/pitfalls/MCP调用无超时导致任务永久挂起.md）：
    #   1) 45s 超时（navigate 自带 30s 页面超时，足够）
    #   2) 超时 → 重建 mcp 会话重试（mcp 子进程僵死的情况）
    #   3) 仍超时且是远程常驻浏览器 → 杀掉 Chrome（systemd Restart=always 秒级拉起
    #      全新实例，登录态在磁盘 profile 不丢）→ 重连重试。反复 attach/detach 会把
    #      Chrome 本体搞僵，重启浏览器是唯一解。本地模式绝不杀用户自己的 Chrome。
    CALL_TIMEOUT_S = 45

    async def call(self, tool: str, arguments: dict[str, Any] | None = None) -> str:
        """调用一个 MCP 工具，返回文本结果。工具报错时抛异常而不是把错误文本当结果。"""
        result = None
        for attempt in range(3):
            if self._session is None:
                raise MCPConnectionError("MCP 会话未连接")
            try:
                result = await asyncio.wait_for(
                    self._session.call_tool(tool, arguments or {}), timeout=self.CALL_TIMEOUT_S
                )
                break
            except TimeoutError as e:
                if attempt == 0:
                    await self.close()
                    await self.connect()
                elif attempt == 1 and self._use_pool:
                    # 池模式：杀掉该用户僵死的 Chrome 并重拉（profile 保登录）
                    await asyncio.to_thread(self._pool.restart, self.user_id)
                    self.browser_url = await asyncio.to_thread(self._pool.acquire, self.user_id, None)
                    await self.close()
                    await self.connect()
                elif attempt == 1 and settings.remote_browser:
                    await self._restart_remote_browser()
                    await self.close()
                    await self.connect()
                else:
                    raise MCPConnectionError(
                        f"MCP 工具 {tool} 超过 {self.CALL_TIMEOUT_S}s 未响应（会话僵死，自愈失败）"
                    ) from e
        parts = []
        for item in result.content:
            if getattr(item, "type", "") == "text":
                parts.append(item.text)
        text = "\n".join(parts)
        if getattr(result, "isError", False):
            raise MCPConnectionError(f"MCP 工具 {tool} 执行失败: {text[:300]}")
        return text

    async def list_tools(self) -> list[str]:
        if self._session is None:
            raise MCPConnectionError("MCP 会话未连接")
        result = await self._session.list_tools()
        return [t.name for t in result.tools]
