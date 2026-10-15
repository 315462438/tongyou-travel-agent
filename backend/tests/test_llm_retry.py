"""LLM 传输层重试（Phase 103）单测。全离线：不发网络请求、不调 LLM。

改造前全仓 grep `tenacity|max_retries|APIError|RateLimit` 是 0 结果——一轮 guide 要打
6-10 次 DeepSeek，任何一次撞上 429/503/连接重置整轮 4-6 分钟直接作废。
移植自 opencode `packages/opencode/src/session/retry.ts`。
"""

import time

import pytest

from app.agent.cancel import TurnCancelled, clear_cancel, request_cancel
from app.llm import retry as R


class FakeAPIError(Exception):
    """模拟 openai SDK 的错误形态：status_code + headers 挂在异常上。"""

    def __init__(self, message, status_code=None, headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.headers = headers or {}


# --------------------------------------------------------------------------- 可重试判定

@pytest.mark.parametrize("err, expected", [
    (FakeAPIError("rate limit exceeded", 429), True),
    (FakeAPIError("boom", 500), True),
    (FakeAPIError("bad gateway", 502), True),
    (FakeAPIError("gateway timeout", 504), True),
    # 5xx 一律重试，哪怕文本毫无特征——SDK 的 isRetryable 常漏标
    (FakeAPIError("???", 503), True),
    # 没有状态码时靠错误文本兜底
    (FakeAPIError("Service Unavailable"), True),
    (FakeAPIError("Connection reset by peer"), True),
    (FakeAPIError("Request timed out"), True),
    (FakeAPIError("服务繁忙，请稍后再试"), True),
    (FakeAPIError("upstream connect error"), True),
    # 我们自己的问题，重试没用
    (FakeAPIError("invalid api key", 401), False),
    (FakeAPIError("model not found", 404), False),
    (FakeAPIError("invalid request", 400), False),
    (ValueError("LLM 结构化输出解析失败"), False),
])
def test_is_retryable(err, expected):
    assert R.is_retryable(err) is expected


def test_context_overflow_never_retried():
    """重试只会再超一次限，纯浪费用户的等待时间。"""
    for msg in [
        "This model's maximum context length is 128000 tokens",
        "context_length_exceeded",
        "请求的上下文长度超过最大长度",
        "Please reduce the length of the messages",
    ]:
        assert R.is_retryable(FakeAPIError(msg)) is False


def test_overflow_wins_over_retryable_signal():
    """判定顺序：**先看不可重试**。

    一条 overflow 报文里同时含 5xx 数字并非不可能（网关包装）；先判可重试就会把它
    放进重试循环，白白多烧几次超长请求。
    """
    err = FakeAPIError("500 error: context_length_exceeded", 500)
    assert R.is_retryable(err) is False


# --------------------------------------------------------------------------- 退避时长

def test_retry_after_seconds_header():
    assert R.retry_after_s(FakeAPIError("x", 429, {"retry-after": "3"})) == 3.0


def test_retry_after_ms_header_wins():
    """retry-after-ms 更精确，优先于秒级头。"""
    err = FakeAPIError("x", 429, {"retry-after-ms": "1500", "retry-after": "60"})
    assert R.retry_after_s(err) == 1.5


def test_retry_after_http_date():
    from email.utils import formatdate

    err = FakeAPIError("x", 429, {"retry-after": formatdate(time.time() + 5, usegmt=True)})
    got = R.retry_after_s(err)
    assert got is not None and 3.0 <= got <= 6.0


def test_retry_after_garbage_falls_back():
    assert R.retry_after_s(FakeAPIError("x", 429, {"retry-after": "soon"})) is None
    assert R.retry_after_s(FakeAPIError("x", 429)) is None


def test_explicit_retry_after_overrides_backoff():
    """服务端说了等多久就等多久，可以超过 30s 的无头封顶。"""
    err = FakeAPIError("x", 429, {"retry-after": "45"})
    assert R.delay_for(1, err) == 45.0


def test_exponential_backoff_with_jitter():
    err = FakeAPIError("boom", 500)
    # 2026-10-15 交互链路：attempt=1 → base 1s，抖动 25% → 落在 [1, 1.25]
    assert R.delay_for(1, err, rand=0.0) == 1.0
    assert R.delay_for(1, err, rand=1.0) == 1.25
    # 指数增长
    assert R.delay_for(3, err, rand=0.0) == 4.0
    # 无头时封顶 8s
    assert R.delay_for(9, err, rand=1.0) == R.MAX_DELAY_NO_HEADERS_S == 8.0


def test_jitter_stays_within_band():
    """抖动是为了防惊群（并发用户同时撞 429 不要在同一毫秒重试），但不能失控。"""
    err = FakeAPIError("boom", 500)
    for _ in range(50):
        d = R.delay_for(2, err)
        assert 2.0 <= d <= 2.5


# --------------------------------------------------------------------------- 重试循环

def test_retries_then_succeeds():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise FakeAPIError("overloaded", 503)
        return "ok"

    assert R.call_with_retry(fn, max_retries=5) == "ok"
    assert calls["n"] == 3


def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(R, "delay_for", lambda *a, **k: 0.0)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise FakeAPIError("overloaded", 503)

    # 2026-10-15：重试用尽仍是可重试类错误 = 模型服务不可用，统一转成 LLMUnavailableError
    with pytest.raises(R.LLMUnavailableError) as info:
        R.call_with_retry(fn, max_retries=2)
    assert calls["n"] == 3  # 首次 + 2 次重试
    assert isinstance(info.value.__cause__, FakeAPIError)


def test_non_retryable_raises_immediately():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise FakeAPIError("invalid api key", 401)

    with pytest.raises(FakeAPIError):
        R.call_with_retry(fn)
    assert calls["n"] == 1  # 一次都没重试


def test_cancel_is_not_a_failure():
    """用户点停止不是「失败」，绝不能被重试成 5 次。"""
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise TurnCancelled()

    with pytest.raises(TurnCancelled):
        R.call_with_retry(fn)
    assert calls["n"] == 1


def test_backoff_is_interruptible():
    """裸 time.sleep(30) 会让停止按钮在整个退避窗口里失灵（取消是协作式的，
    睡着的线程没有检查点）。退避必须切片轮询。"""
    cid = "cid-interrupt"
    clear_cancel(cid)
    request_cancel(cid)
    try:
        t0 = time.monotonic()
        with pytest.raises(TurnCancelled):
            R.sleep_interruptible(30.0, lambda: __import__(
                "app.agent.cancel", fromlist=["is_cancelled"]).is_cancelled(cid))
        assert time.monotonic() - t0 < 1.0  # 立刻返回，不是等 30 秒
    finally:
        clear_cancel(cid)


def test_cancel_during_backoff_stops_further_calls():
    """退避期间被取消 → 抛 TurnCancelled，且**不再发起下一次请求**。"""
    cid = "cid-during"
    clear_cancel(cid)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        request_cancel(cid)  # 第一次失败后用户点了停止
        raise FakeAPIError("overloaded", 503)

    from app.agent.cancel import is_cancelled

    try:
        with pytest.raises(TurnCancelled):
            R.call_with_retry(fn, should_abort=lambda: is_cancelled(cid))
        assert calls["n"] == 1
    finally:
        clear_cancel(cid)


def test_sleep_without_abort_callback_still_sleeps():
    """不传 cid 时退化为普通分片 sleep，行为与改造前一致（不抛异常）。"""
    t0 = time.monotonic()
    R.sleep_interruptible(0.2, None)
    assert time.monotonic() - t0 >= 0.15


# --------------------------------------------------------------------------- 流式重试

class _Delta:
    def __init__(self, content=None, reasoning_content=None):
        self.content = content
        self.reasoning_content = reasoning_content


class _Choice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _Chunk:
    def __init__(self, delta, finish_reason=None):
        self.choices = [_Choice(delta, finish_reason)]


def _chunks(*texts):
    out = [_Chunk(_Delta(content=t)) for t in texts]
    out.append(_Chunk(_Delta(), finish_reason="stop"))
    return out


class _FakeCompletions:
    """按脚本决定每次 create 的效果：异常实例=抛出，列表=当作流返回。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        effect = self.script.pop(0)
        if isinstance(effect, BaseException):
            raise effect
        # 有 close() 的假流原样返回（同真实 openai Stream）：看门狗/停止接口关的必须是它本身，
        # 包一层生成器就变成关生成器了，测试会「碰巧通过」
        return effect if hasattr(effect, "close") else iter(effect)


def _client_with(script, monkeypatch):
    from app.llm.client import LLMClient

    c = LLMClient.__new__(LLMClient)  # 绕开 __init__（不建真 OpenAI 客户端）
    fake = _FakeCompletions(script)
    c._client = type("C", (), {"chat": type("Ch", (), {"completions": fake})()})()
    monkeypatch.setattr(R, "delay_for", lambda *a, **k: 0.0)
    return c, fake


def test_stream_retries_before_first_token(monkeypatch):
    """首块之前的连接错是最常见的失败点（建连/首字节），必须重试。"""
    c, fake = _client_with([FakeAPIError("connection reset"), _chunks("杭州", "三日游")], monkeypatch)
    out = [d for k, d in c.stream_generate_with_reasoning(prompt="x") if k == "content"]
    assert out == ["杭州", "三日游"]
    assert fake.calls == 2


def test_stream_does_not_retry_after_producing_output(monkeypatch):
    """一旦 yield 过 delta，调用方（_stream_into）已经把它累进 content_parts 并周期落库，
    重开一条流会让用户看到**重复的正文**——比一次失败更糟。这条静默失效的话，
    线上表现是「攻略写到一半又从头写了一遍」，所以必须钉住。"""
    class _Boom:
        def __iter__(self):
            yield _Chunk(_Delta(content="杭州第一天"))
            raise FakeAPIError("connection reset")  # 可重试的错，但已经吐过内容了

    c, fake = _client_with([_Boom()], monkeypatch)
    seen = []
    with pytest.raises(FakeAPIError):
        for kind, delta in c.stream_generate_with_reasoning(prompt="x"):
            seen.append(delta)
    assert seen == ["杭州第一天"]  # 没有第二遍
    assert fake.calls == 1        # 没有重开流


def test_stream_gives_up_after_max_retries(monkeypatch):
    c, fake = _client_with([FakeAPIError("overloaded", 503)] * 10, monkeypatch)
    with pytest.raises(R.LLMUnavailableError):
        list(c.stream_generate_with_reasoning(prompt="x"))
    assert fake.calls == R.retry_limit() + 1


# --------------------------------------------------------------------------- 2026-10-15 快速失败/可见重试/空响应

def test_turn_fails_fast_once_model_is_down(monkeypatch):
    """DeepSeek 故障时一轮里 6-10 次调用不能各自再等一遍超时。"""
    monkeypatch.setattr(R, "delay_for", lambda *a, **k: 0.0)
    monkeypatch.setattr(R, "notify_retry", lambda *a, **k: None)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise FakeAPIError("Request timed out")

    try:
        with pytest.raises(R.LLMUnavailableError):
            R.call_with_retry(fn, max_retries=1, cid="down-1")
        assert calls["n"] == 2
        with pytest.raises(R.LLMUnavailableError):
            R.call_with_retry(fn, cid="down-1")
        assert calls["n"] == 2  # 第二次调用直接失败，没有再发请求
        R.clear_down("down-1")
        with pytest.raises(R.LLMUnavailableError):
            R.call_with_retry(fn, max_retries=0, cid="down-1")
        assert calls["n"] == 3
    finally:
        R.clear_down("down-1")


def test_retry_is_announced_in_the_conversation(monkeypatch):
    monkeypatch.setattr(R, "delay_for", lambda *a, **k: 0.0)
    seen = []
    monkeypatch.setattr(R, "notify_retry", lambda cid, attempt, total: seen.append((cid, attempt, total)))
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise FakeAPIError("overloaded", 503)
        return "ok"

    assert R.call_with_retry(fn, max_retries=2, cid="c1") == "ok"
    assert seen == [("c1", 1, 2)]


def test_stream_retries_once_on_empty_response(monkeypatch):
    c, fake = _client_with([[_Chunk(_Delta(), finish_reason="stop")], _chunks("拉萨")], monkeypatch)
    out = [d for k, d in c.stream_generate_with_reasoning(prompt="x") if k == "content"]
    assert out == ["拉萨"] and fake.calls == 2


def test_stream_empty_twice_gives_up_quietly(monkeypatch):
    c, fake = _client_with([[], []], monkeypatch)
    assert list(c.stream_generate_with_reasoning(prompt="x")) == []
    assert fake.calls == 2


def test_stream_passes_thinking_effort_and_idle_timeout(monkeypatch):
    c, fake = _client_with([_chunks("好")], monkeypatch)
    seen = {}
    real = fake.create

    def spy(**kw):
        seen.update(kw)
        return real(**kw)
    fake.create = spy
    list(c.stream_generate_with_reasoning(prompt="x", effort="off"))
    assert seen["extra_body"] == {"thinking": {"type": "disabled"}}
    from app.config import settings
    assert seen["timeout"].read == settings.llm_stream_idle_timeout_s
    assert seen["timeout"].connect == settings.llm_connect_timeout_s


def test_stream_non_retryable_raises_immediately(monkeypatch):
    c, fake = _client_with([FakeAPIError("context_length_exceeded")], monkeypatch)
    with pytest.raises(FakeAPIError):
        list(c.stream_generate_with_reasoning(prompt="x"))
    assert fake.calls == 1


def test_stream_yields_finish_reason(monkeypatch):
    """finish_reason 是续写判据（Phase 11），重试改造不能把它吃掉。"""
    c, _ = _client_with([_chunks("正文")], monkeypatch)
    kinds = [(k, d) for k, d in c.stream_generate_with_reasoning(prompt="x")]
    assert ("finish", "stop") in kinds


def test_stop_closes_the_open_stream_and_counts_as_cancel(monkeypatch):
    """停止接口关掉流后，读流线程拿到的异常要认成取消，不能被当成故障去重试。"""
    from app.llm import client as C

    class _Closable:
        def __init__(self):
            self.closed = False

        def __iter__(self):
            yield _Chunk(_Delta(content="第一天"))
            C.close_streams("stop-1")       # 模拟另一个线程里的停止接口
            assert self.closed
            raise FakeAPIError("Connection reset by peer")  # 关流后读侧收到的错

        def close(self):
            self.closed = True

    c, fake = _client_with([_Closable()], monkeypatch)
    request_cancel("stop-1")
    try:
        with pytest.raises(TurnCancelled):
            list(c.stream_generate_with_reasoning(prompt="x", cid="stop-1"))
        assert fake.calls == 1
        assert "stop-1" not in C._open_streams
    finally:
        clear_cancel("stop-1")


class _SilentStream:
    """模拟 DeepSeek 排队时的流：只有 keep-alive（SDK 吞掉，不产出 chunk），直到被关掉。"""

    def __init__(self):
        import threading
        self._closed = threading.Event()

    def __iter__(self):
        if not self._closed.wait(5):
            raise AssertionError("watchdog never closed the stream")
        raise FakeAPIError("peer closed connection")  # 关流后读侧收到的错
        yield  # pragma: no cover

    def close(self):
        self._closed.set()


def test_heartbeat_only_stream_times_out_and_retries(monkeypatch):
    """2026-10-15 故障实测：流式只来心跳时 httpx 读超时永不触发，挂 330s+。看门狗按内容计时。"""
    from app.config import settings
    monkeypatch.setattr(settings, "llm_first_token_timeout_s", 0.2)
    monkeypatch.setattr(R, "notify_retry", lambda *a, **k: None)
    c, fake = _client_with([_SilentStream(), _chunks("拉萨")], monkeypatch)
    t = time.monotonic()
    out = [d for k, d in c.stream_generate_with_reasoning(prompt="x") if k == "content"]
    assert out == ["拉萨"] and fake.calls == 2
    assert time.monotonic() - t < 3


def test_heartbeat_only_every_time_means_unavailable(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "llm_first_token_timeout_s", 0.1)
    monkeypatch.setattr(R, "notify_retry", lambda *a, **k: None)
    c, fake = _client_with([_SilentStream() for _ in range(5)], monkeypatch)
    try:
        with pytest.raises(R.LLMUnavailableError):
            list(c.stream_generate_with_reasoning(prompt="x", cid="silent-1"))
        assert fake.calls == R.retry_limit() + 1
        assert R.is_down("silent-1")
    finally:
        R.clear_down("silent-1")
