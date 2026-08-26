"""独立扫码连接会话（Phase 109 第二期）。

**为什么值得从对话轮次里搬出来** —— 原计划把这件事排到后面，理由是「等待会占住
浏览器池槽位，而 `BROWSER_POOL_MAX=2`」。**这个理由经查是错的**，它只算了新方案的
成本没算现状：

    现状：acquire → 导航携程 → 撞登录墙 → 等扫码(≤180s) → 重开页 → 抓取
          → 继续必应搜索 + 最多 8 个页面 → release
          占槽 = 采集全程 + 最多 180s

    独立：acquire → 导航 → 等扫码(≤90s) → release
          占槽 = 最多 90s，没有别的

所以挪出来是**减轻**池压力，不是增加；而且之后的轮次不再撞登录墙，更短。
超时也能砍一半——独立流程失败无所谓，用户点一下重试即可，而轮次里砍短了整轮就废。

另一层收益：Phase 71 的结论是「长任务流失的原因不是久，是不知道还要多久 + 静默空隙」，
而登录墙恰好在用户等攻略时插入一个 3 分钟的空隙。挪走它是直接消除一个已知最差体验点。

复用 `site_router._wait_for_login` 的轮询循环（`check_page` 旁观 + 每轮刷新截图 +
成功后 `mark_site_login`），不重写。
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 状态机：starting（拉浏览器/导航）→ waiting（等扫码，有截图）→ connected / failed / timeout
STATES = ("starting", "waiting", "connected", "failed", "timeout", "cancelled")

# 独立连接用的默认落地城市。只是为了触发登录墙判定，跟用户真实目的地无关。
_DEFAULT_CITY_ID = 2  # 上海（CTRIP_CITY_IDS）


def screenshot_path(token: str) -> str:
    d = os.path.join(tempfile.gettempdir(), "travel_connect")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{token}.jpg")


@dataclass
class ConnectSession:
    user_id: str
    key: str
    token: str
    state: str = "starting"
    message: str = ""
    started_at: float = field(default_factory=time.monotonic)

    @property
    def active(self) -> bool:
        return self.state in ("starting", "waiting")

    def view(self) -> dict:
        return {
            "token": self.token,
            "key": self.key,
            "state": self.state,
            "message": self.message,
            "elapsed_s": round(time.monotonic() - self.started_at, 1),
            # 截图只在 waiting 态有意义；其余态前端不该继续轮询图片。
            # ⚠️ 只给 token，**不拼完整路径**：前端挂在 /travel/api 下，后端拼出来的
            # /api/... 会 404（2026-08-26 线上踩到，图片显示成 alt 文字）。既有代码
            # 有在后端硬编码 "/travel/" 的写法（auth_api 的 avatar_url），那等于把
            # 部署路径散进后端各处，换个挂载点就要全仓找。让前端用自己的 API 常量拼。
            "screenshot_token": self.token if self.state == "waiting" else "",
        }


_sessions: dict[str, ConnectSession] = {}
_lock = threading.Lock()


def current(user_id: str) -> ConnectSession | None:
    with _lock:
        return _sessions.get(user_id)


def start(user_id: str, key: str) -> ConnectSession:
    """开一个连接会话。**同一用户已有进行中的会话就返回它**，不新建。

    没有这道互斥的话，用户连点几次「连接」就能把自己的浏览器槽位耗光
    （每个会话都要 acquire 一次），而池上限只有 2。
    """
    with _lock:
        old = _sessions.get(user_id)
        if old is not None and old.active:
            return old
        sess = ConnectSession(user_id=user_id, key=key, token=uuid.uuid4().hex)
        _sessions[user_id] = sess

    threading.Thread(
        target=_run, args=(sess,), name=f"connect-{user_id[:8]}", daemon=True,
    ).start()
    return sess


def cancel(user_id: str) -> bool:
    """用户主动取消。只置状态，后台循环下一轮自己收摊（不强杀，避免半截释放）。"""
    with _lock:
        sess = _sessions.get(user_id)
        if sess is None or not sess.active:
            return False
        sess.state = "cancelled"
        sess.message = "已取消"
        return True


def _finish(sess: ConnectSession, state: str, message: str) -> None:
    # 取消是用户的决定，后台不要用超时/失败把它覆盖回去
    if sess.state == "cancelled" and state != "connected":
        return
    sess.state = state
    sess.message = message


def _run(sess: ConnectSession) -> None:
    try:
        asyncio.run(_drive(sess))
    except Exception as e:  # noqa: BLE001 — 后台线程的异常必须就地消化
        logger.warning("connect session failed user=%s: %s", sess.user_id, e, exc_info=True)
        _finish(sess, "failed", "连接过程出错，请重试")
    finally:
        # 会话结束一律删截图（同 Phase 5：等待结束删截图，不留残影）
        try:
            os.remove(screenshot_path(sess.token))
        except OSError:
            pass


async def _drive(sess: ConnectSession) -> None:
    from app.agent.site_router import _wait_for_login, ctrip_target, mark_site_login
    from app.config import settings
    from app.db.session import get_session
    from app.tools.browser_tool import BrowserTool
    from app.tools.mcp_client import ChromeMCP

    if sess.key != "ctrip":
        _finish(sess, "failed", "该连接器不支持扫码连接")
        return

    target = ctrip_target(_DEFAULT_CITY_ID)
    path = screenshot_path(sess.token)

    async with ChromeMCP(user_id=sess.user_id) as chrome:
        browser = BrowserTool(chrome=chrome)
        page = await browser.open_page(target.url)

        if page.status == "ok":
            # 已经是登录态（profile 里还留着 cookie）——直接补记录，别让用户白扫一次
            with get_session() as db:
                mark_site_login(db, sess.user_id, "ctrip")
            _finish(sess, "connected", "已连接（此前的登录仍然有效）")
            return

        if page.status != "need_user_handoff":
            _finish(sess, "failed", "打不开携程页面，请稍后重试")
            return

        # ⚠️ 携程登录页默认是**账号密码登录**，二维码藏在右侧竖排的「扫码登录」标签后面。
        # 不点这一下，用户看到的就是一个表单页——CLAUDE.md Phase 5 记的
        # 「纯短信表单登录页会等到超时回退」就是这个现象，当时没往下追。
        # `_locate_uid` 先做精确文字匹配（匹配不到才用 LLM），所以这一步快且确定；
        # 找不到就 blocked，不抛异常——站点改版时退化成显示表单页，不至于整个流程炸。
        switched = await browser.find_and_click("扫码登录", url=target.url)
        if switched.status != "ok":
            logger.warning("switch to QR login failed: %s", switched.reason)

        sess.state = "waiting"
        sess.message = "请用携程 App 扫描二维码"
        await _capture_first(browser, path)

        def _progress(_text: str) -> None:
            pass  # 独立流程不写对话流；状态经 sess 暴露给前端轮询

        result = await _wait_for_login(
            target, browser, _progress,
            screenshot_path=path,
            wait_s=settings.connect_wait_s,
            user_id=sess.user_id,
        )

    if result is not None:
        # _wait_for_login 内部已 _record_login_success，这里只做状态
        _finish(sess, "connected", "已连接")
    else:
        _finish(sess, "timeout", "等待超时，没有检测到登录。可以重新发起连接")


async def _capture_first(browser, path: str) -> None:
    """先截一帧再进轮询循环：否则前端头一次拉图必然 404，白闪一下。"""
    try:
        await browser.screenshot_to_file(path)
    except Exception:  # noqa: BLE001
        logger.warning("first connect screenshot failed", exc_info=True)
