"""协作式取消（Phase 16）：用户点停止 → 标记 cid，运行中的 agent 在检查点抛出中止。

进程内线程安全集合（BackgroundTask 跑在线程池里）。取消是「协作式」的：
长时间 MCP 调用不会立刻中断，但会在下一个 check 点（每块流式/每次搜索抓取）生效。
"""

import logging
import threading

logger = logging.getLogger(__name__)

_cancelled: set[str] = set()
_lock = threading.Lock()


class TurnCancelled(Exception):
    """本轮被用户停止。"""


def request_cancel(cid: str) -> None:
    logger.info("cancel requested cid=%s", cid)
    with _lock:
        _cancelled.add(cid)


def is_cancelled(cid: str) -> bool:
    with _lock:
        return cid in _cancelled


def clear_cancel(cid: str) -> None:
    with _lock:
        _cancelled.discard(cid)


def check(cid: str) -> None:
    """检查点：被取消则抛 TurnCancelled。"""
    if is_cancelled(cid):
        raise TurnCancelled()


async def wait_cancellable(cid: str, awaitable, poll_s: float = 1.0):
    """等待 awaitable，期间每 poll_s 秒响应一次停止请求（2026-07-31）。

    线上教训：budget/poster 的抽取是一次阻塞 LLM 调用，检查点只能放在调用前后——
    调用异常变慢时（结构化重试），用户点停止后要干等它返回（实测拖了 3 分钟）。
    这里把「等结果」和「看取消」并行：取消时放弃结果立即抛 TurnCancelled；
    底层线程无法真正杀掉，会在后台自然跑完，结果被丢弃（无副作用的抽取调用可接受）。

    ⚠️ 调用方注意：TurnCancelled 的**终稿处理必须在传给 asyncio.run 的协程内部完成**，
    不能放在 asyncio.run 之后——asyncio.run 退出时会 join 默认线程池，被放弃的孤儿
    LLM 线程会把外层代码拖到它自然结束（分钟级）之后才执行（2026-07-31 线上排障实证）。
    """
    import asyncio

    task = asyncio.ensure_future(awaitable)
    while True:
        done, _ = await asyncio.wait({task}, timeout=poll_s)
        if done:
            return task.result()
        if is_cancelled(cid):
            task.cancel()
            logger.info("wait_cancellable aborted cid=%s", cid)
            raise TurnCancelled()
