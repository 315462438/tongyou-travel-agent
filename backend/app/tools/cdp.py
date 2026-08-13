"""CDP 直连工具（绕过 chrome-devtools-mcp 的能力缺口）

目前只有一个用途：清空常驻浏览器的全部 cookie（Storage.clearCookies），
用于站点登录态过期（Phase 9）。mcp 0.6.0 不暴露任何 cookie 工具。

按域清理（Storage.clearDataForOrigin）受 cookie domain 归属影响不可靠；
这个浏览器是 Agent 专用的单用途实例，全清最干净。
"""

import json
import logging

import httpx
import websockets

logger = logging.getLogger(__name__)


async def clear_browser_cookies(debug_url: str) -> bool:
    """清空浏览器全部 cookie。成功返回 True，任何失败返回 False（不抛异常）。"""
    try:
        # 本机 CDP 接口必须直连（环境代理会把 127.0.0.1 送进远端代理，踩过坑）
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            resp = await client.get(f"{debug_url}/json/version")
            ws_url = resp.json()["webSocketDebuggerUrl"]
        async with websockets.connect(ws_url, open_timeout=5, close_timeout=3) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Storage.clearCookies", "params": {}}))
            reply = json.loads(await ws.recv())
            ok = reply.get("id") == 1 and "error" not in reply
            if not ok:
                logger.warning("Storage.clearCookies failed: %s", reply)
            return ok
    except Exception:  # noqa: BLE001
        logger.warning("clear_browser_cookies failed", exc_info=True)
        return False
