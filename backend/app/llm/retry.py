"""LLM 传输层重试（Phase 103）。移植自 opencode `packages/opencode/src/session/retry.ts`。

## 为什么需要

改造前全仓 `grep -rn "tenacity|max_retries|APIError|RateLimit"` 是 **0 结果**：
`LLMClient.parse()` 里的 `for _ in range(2)` 只重试「JSON 校验失败」和「输出截断」，
传输层错误一次都不重试。一轮 guide 要打 6-10 次 DeepSeek（parse → quick_take → 流式生成
→ critique → 记忆提炼 → 历史摘要），**任何一次撞上 429/503/连接重置，整轮 4-6 分钟直接
作废**——而 Phase 70/71 花大力气解决的正是「用户等太久会跑掉」。

它还悄悄打开一个保真度漏洞：轮末压缩失败被 except 吞掉只记日志，下一轮装配发现超限而
summary 为空 → 回退读兼容字段（新会话为空）→ 早期历史既没进摘要也没进窗口，静默消失。

## 设计要点（哪些抄、哪些是我们独有的）

抄 opencode：
- 用**错误文本**兜底判定（SDK 的 `isRetryable` 常漏标）
- 5xx 一律重试，显式绕过 SDK 判断
- 优先读 `Retry-After` / `retry-after-ms` 头，读不到才指数退避
- 指数 2s × 2^n + 25% 抖动，无头时封顶 30s，最多 5 次
- **context overflow 永不重试**——重试只会再超一次，纯浪费

我们独有（opencode 没有对应约束）：
- **退避等待必须可被停止按钮打断**：裸 sleep 会让停止在退避窗口里失灵，所以切成
  `_SLEEP_SLICE_S` 片轮询 `should_abort`
- **流式只在「尚未吐出任何内容」时重试**：见 `llm/client.py` 的 `produced` 标志。
  这条不在本模块，但判定表是共用的

本模块**无 I/O、无依赖注入**，纯函数 + 一个循环，全部可离线单测。
"""

import logging
import random
import re
import time
from typing import Callable

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
INITIAL_DELAY_S = 2.0
BACKOFF_FACTOR = 2.0
JITTER_FACTOR = 0.25
MAX_DELAY_NO_HEADERS_S = 30.0
MAX_DELAY_S = 600.0  # 服务端给的 Retry-After 也要有上限，否则一个离谱的头能挂死整轮
_SLEEP_SLICE_S = 0.5  # 退避切片，每片查一次取消

# 可重试的错误文本特征。provider SDK 的 isRetryable 经常漏标（尤其 openai-compatible
# 网关包装过的错误），所以用文本兜底。顺序无关，命中任一即可。
RETRYABLE_PATTERNS = [
    re.compile(r"\b(429|500|502|503|504|524)\b"),
    re.compile(r"rate.?limit|too many requests|请求过于频繁", re.I),
    re.compile(
        r"overloaded|service unavailable|internal (server )?error|server_error|"
        r"provider returned error|服务繁忙|系统繁忙",
        re.I,
    ),
    re.compile(
        r"terminated|fetch failed|failed to fetch|network error|upstream connect|"
        r"connection (error|refused|reset|lost|aborted)|socket hang up|remote end closed|"
        r"getaddrinfo|enotfound|eai_again|econnrefused|econnreset|etimedout|"
        r"incomplete chunked read|server disconnected",
        re.I,
    ),
    re.compile(r"^timeout$|(request|response|connection|network|stream|read) ?(timeout|timed out)", re.I),
    re.compile(r"try again later|try your request again|resource exhausted|temporarily", re.I),
]

# 绝不重试：重试只会再超一次限，纯浪费用户的等待时间。
# DeepSeek 超长上下文的报错文本形态不止一种，都收在这里。
NON_RETRYABLE_PATTERNS = [
    re.compile(
        r"context (length|window)|maximum context|context_length_exceeded|"
        r"too many tokens|reduce the length|上下文长度|超过最大长度",
        re.I,
    ),
]


def _status_of(error: BaseException) -> int | None:
    """从异常里挖 HTTP 状态码。openai SDK 挂在 .status_code，httpx 挂在 .response.status。"""
    code = getattr(error, "status_code", None)
    if isinstance(code, int):
        return code
    resp = getattr(error, "response", None)
    code = getattr(resp, "status_code", None)
    return code if isinstance(code, int) else None


def _headers_of(error: BaseException) -> dict:
    """取响应头（小写键）。拿不到就空 dict——调用方据此退化为指数退避。"""
    resp = getattr(error, "response", None)
    headers = getattr(resp, "headers", None) or getattr(error, "headers", None)
    if not headers:
        return {}
    try:
        return {str(k).lower(): str(v) for k, v in dict(headers).items()}
    except Exception:  # noqa: BLE001 — 头拿不到不该影响重试判定
        return {}


def is_retryable(error: BaseException) -> bool:
    """这个错误值不值得重试。

    判定顺序有讲究：**先看不可重试**。一条「context length exceeded」的报文里同时含有
    「500」这类数字并非不可能，先判可重试会把它错误地放进重试循环。
    """
    text = f"{type(error).__name__}: {error}"
    if any(p.search(text) for p in NON_RETRYABLE_PATTERNS):
        return False
    status = _status_of(error)
    if status is not None:
        if status >= 500:
            return True  # 5xx 一律重试，哪怕 SDK 没标 retryable
        if status == 429:
            return True
        if 400 <= status < 500:
            return False  # 其余 4xx 是我们自己的问题，重试没用
    return any(p.search(text) for p in RETRYABLE_PATTERNS)


def retry_after_s(error: BaseException) -> float | None:
    """服务端明确说了等多久就等多久。返回 None 表示没说，调用方走指数退避。"""
    headers = _headers_of(error)
    ms = headers.get("retry-after-ms")
    if ms:
        try:
            return min(float(ms) / 1000.0, MAX_DELAY_S)
        except ValueError:
            pass
    after = headers.get("retry-after")
    if after:
        try:
            return min(float(after), MAX_DELAY_S)
        except ValueError:
            # HTTP-date 形态
            from email.utils import parsedate_to_datetime

            try:
                delta = parsedate_to_datetime(after).timestamp() - time.time()
                if delta > 0:
                    return min(delta, MAX_DELAY_S)
            except Exception:  # noqa: BLE001
                pass
    return None


def delay_for(attempt: int, error: BaseException, rand: float | None = None) -> float:
    """第 attempt 次失败后该等多久（attempt 从 1 起）。

    有 Retry-After 头就听它的（可以超过 30s——是服务端要求的）；没有则指数退避 + 抖动，
    并封顶 30s。抖动是为了防惊群：并发的几个用户同时撞 429 时不要在同一毫秒重试。
    """
    explicit = retry_after_s(error)
    if explicit is not None:
        return max(0.0, explicit)
    r = random.random() if rand is None else rand
    base = INITIAL_DELAY_S * (BACKOFF_FACTOR ** (attempt - 1))
    return min(base + base * JITTER_FACTOR * r, MAX_DELAY_NO_HEADERS_S)


def sleep_interruptible(seconds: float, should_abort: Callable[[], bool] | None = None) -> None:
    """分片睡眠，期间可被停止请求打断。

    这是我们相对 opencode 额外要的一条：裸 `time.sleep(30)` 会让停止按钮在整个退避窗口里
    失灵（Phase 16 的取消是协作式的，靠检查点生效，睡着的线程没有检查点）。
    """
    from app.agent.cancel import TurnCancelled

    deadline = time.monotonic() + seconds
    while True:
        if should_abort is not None and should_abort():
            raise TurnCancelled()
        left = deadline - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(_SLEEP_SLICE_S, left))


def call_with_retry(
    fn: Callable,
    *,
    what: str = "llm",
    should_abort: Callable[[], bool] | None = None,
    max_retries: int = MAX_RETRIES,
):
    """执行 fn()，传输层错误按策略重试。不可重试的错误原样抛出。

    fn 必须是**可重复执行且无副作用**的（一次 HTTP 请求）。流式生成不能整体套这个函数——
    见 `client.py` 里 `produced` 那段。
    """
    from app.agent.cancel import TurnCancelled

    attempt = 0
    while True:
        try:
            return fn()
        except TurnCancelled:
            raise  # 取消不是失败，别重试
        except BaseException as e:  # noqa: BLE001 — 判定完再决定放行还是重试
            attempt += 1
            if attempt > max_retries or not is_retryable(e):
                raise
            wait = delay_for(attempt, e)
            logger.warning(
                "%s failed (%s/%s), retrying in %.1fs: %s",
                what, attempt, max_retries, wait, e,
            )
            sleep_interruptible(wait, should_abort)
