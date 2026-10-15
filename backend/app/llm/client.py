"""LLMClient 统一封装（评审 🔴5）—— DeepSeek 版

- DeepSeek OpenAI 兼容接口（base_url=https://api.deepseek.com）
- parse():   结构化输出：json_object 模式 + Pydantic 校验 + 失败带错误重试一次
- generate(): 自由文本生成
- 模型：全部 deepseek-flash（V4.1，规划/抽取/分类/视觉；按调用定思考档位，见 _thinking_kwargs）
"""

import json
import logging
from typing import TypeVar

import httpx
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.config import settings

_logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMOutputTruncatedError(ValueError):
    """结构化输出达到模型长度上限，JSON 必然不完整。"""


# DeepSeek 思考模式对**结构化抽取**任务会过度推理：线上实测「从 Markdown 挑地点填 schema」
# 烧掉 13124 思考 token / 118s，而正文只有 971。这是 ITINERARY（Phase 11）、quick_take
# （Phase 101）之后第三次撞同一类问题，治法也还是同一味药——在 system 里写思考纪律。
# 共享一份常量，不在各模块手抄（手抄必漂移）。max_tokens 不因此调小：纪律省时间，
# 预算兜安全（截断重试一次 ~140s，比多想几步贵得多），各管各的。
EXTRACT_THINKING_DISCIPLINE = (
    "\n**思考纪律**：这是结构化抽取任务，答案都在给定文本里，不需要长推理。"
    "思考最多两三行要点即可，把输出预算留给 JSON 正文。"
)


# 语义档位 → DeepSeek 请求字段（Phase 108）。映射抄自上游 deepseek-harness
# `packages/llm/llm-deepseek/src/serialize.ts::resolveThinking`：
#
#     off            → thinking=disabled，**不带** reasoning_effort
#     low/high/max   → thinking=enabled + reasoning_effort=<档位>
#
# ⚠️ **`off` 不是一个 wire 档位**，发 `reasoning_effort="off"` 是错的——这是这张表里
# 最容易写错的一格，有单测钉死。
# ⚠️ `thinking` 不是 openai SDK 的已知参数，必须走 extra_body；SDK 会把 extra_body 的键
# 合并到请求体**顶层**，正好满足协议要求（不是嵌套在 extra_body 里发出去）。
_WIRE_EFFORTS = ("low", "high", "max")


def _thinking_kwargs(effort: str | None) -> dict:
    """把语义档位翻成 `chat.completions.create` 的关键字参数。

    `None` / `"none"` / 空串一律返回 `{}`——**请求体与改造前逐字节相同**，这是回退路径，
    必须保证「配置成 none」等于「这个功能不存在」。未知档位同样降级为 `{}` 并记一条
    warning：配置写错时宁可退回旧行为，不能让整条链路 400。
    """
    if not effort or effort == "none":
        return {}
    if effort == "off":
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    if effort in _WIRE_EFFORTS:
        return {
            "reasoning_effort": effort,
            "extra_body": {"thinking": {"type": "enabled"}},
        }
    _logger.warning("未知的 reasoning effort %r，本次不发思考控制字段", effort)
    return {}


def _timeout(total: float | None = None, *, stream: bool = False) -> httpx.Timeout:
    """分层超时（2026-10-15）：建连单独短超时；流式的 read 是**两块数据之间**的最长间隔
    （httpx 语义），正好就是 harness 的 idle watchdog——首块迟迟不来、或中途断流都会触发。"""
    read = settings.llm_stream_idle_timeout_s if stream else (total or settings.llm_call_timeout_s)
    return httpx.Timeout(read, connect=settings.llm_connect_timeout_s)


# 2026-10-15 停止即断流（借鉴 harness：调用方 signal 与内部 consumer 合并，finally 里 abort 拆 socket）。
# 协作式取消只在「收到下一块」时才生效：模型卡着不出字时点停止要等到超时，被放弃的请求还在后台
# 继续烧 token。这里登记每个会话正在读的流，停止接口直接把它关掉。
import threading

_streams_lock = threading.Lock()
_open_streams: dict[str, set] = {}


def _track(cid: str | None, stream) -> None:
    if cid:
        with _streams_lock:
            _open_streams.setdefault(cid, set()).add(stream)


def _untrack(cid: str | None, stream) -> None:
    if cid:
        with _streams_lock:
            group = _open_streams.get(cid)
            if group is not None:
                group.discard(stream)
                if not group:
                    _open_streams.pop(cid, None)


def close_streams(cid: str) -> int:
    """关闭该会话所有正在读的模型流（停止按钮调用）。返回关闭条数。读流的线程随即收到异常，
    stream_generate_with_reasoning 把它认成取消（TurnCancelled），不算失败、不重试。"""
    with _streams_lock:
        group = list(_open_streams.pop(cid, set()))
    for stream in group:
        try:
            stream.close()
        except Exception:  # noqa: BLE001 — 关不掉也只是退回协作式取消
            _logger.debug("close stream failed", exc_info=True)
    return len(group)


class _Watchdog:
    """按「内容块」计时的看门狗：首块超过 first_s、或两块之间超过 idle_s 就关流。

    心跳（SSE keep-alive 注释）被 SDK 吞掉，不会喂狗——正是要它不算数。
    关流后读侧收到异常（或迭代提前结束），调用方看 `fired` 判定为超时并按可重试错误处理。
    """

    def __init__(self, stream, first_s: float, idle_s: float):
        self._stream = stream
        self._idle_s = idle_s
        self.fired = False
        self._timer: threading.Timer | None = None
        self._arm(first_s)

    def _arm(self, seconds: float) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(seconds, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def _fire(self) -> None:
        self.fired = True
        try:
            self._stream.close()
        except Exception:  # noqa: BLE001
            pass

    def kick(self) -> None:
        if not self.fired:
            self._arm(self._idle_s)

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.cancel()


class LLMStreamStalled(TimeoutError):
    """流式长时间收不到内容（只有心跳或完全无数据）。文本含 timeout，retry 判定为可重试。"""


def _abort_of(cid: str | None):
    """把 cid 变成一个「是否该中止」的回调。不传 cid 则退避期间不响应停止（行为同改造前）。"""
    if not cid:
        return None
    from app.agent.cancel import is_cancelled

    return lambda: is_cancelled(cid)


class LLMClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        # Langfuse 埋点（Phase 24）：启用时换 drop-in 包装类，自动记录每次调用的
        # 完整 prompt/补全/用量（含流式）；未启用/失败回退裸 OpenAI，行为不变。
        from app.observability import wrap_openai_client_cls

        client_cls = wrap_openai_client_cls() or OpenAI
        self._client = client_cls(
            api_key=api_key or settings.deepseek_api_key,
            base_url=base_url or settings.deepseek_base_url,
            # Phase 103：显式超时。默认 600s 意味着一个卡住的连接能吃掉整轮预算——
            # 而这条链路上游还有 deep_research_timeout_s(600) 这类兜底，等于白等。
            # 超时会被 retry.is_retryable 认成可重试，所以掐短是安全的。
            timeout=_timeout(),
            # 重试由我们自己的 retry 模块做（可见、可停止、快速失败），SDK 内置重试会叠加成多倍等待
            max_retries=0,
        )

    def parse(
        self,
        prompt: str | list[dict],
        schema: type[T],
        *,
        model: str | None = None,
        system: str | None = None,
        max_tokens: int = 8000,
        cid: str | None = None,
        effort: str | None = None,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> T:
        """结构化输出：返回通过 Pydantic 校验的对象。校验失败带错误信息重试一次。

        `effort`（Phase 108）：思考档位，**默认 None = 不发思考控制字段**（行为同改造前）。

        ⚠️ 刻意**不**在这里读全局配置。parse() 确实是结构化抽取的边界，但「结构化」不等于
        「机械」：需求解析、自检 critique、记忆增删这些同样走 parse()，它们的质量**依赖**推理。
        真正机械的抽取（从给定文本挑字段填 schema）由调用点显式传档位——范围与 Phase 102
        给五个抽取 system 挂 EXTRACT_THINKING_DISCIPLINE 时圈定的完全一致。
        全局默认会让将来任何新增的 parse() 调用**静默**继承一个它未必该有的档位。

        Phase 103：**两层重试各管各的**——这里的 for 循环治「模型输出不合法」（校验失败/
        截断），`call_with_retry` 治「请求没打通」（429/5xx/连接断）。前者要改 prompt 再问，
        后者要原样重发，混在一起会把「合法的重发」错当成「模型又答错了」而消耗校验重试次数。
        """
        from app.llm.retry import call_with_retry

        model = model or settings.model_extractor
        thinking = _thinking_kwargs(effort)
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        sys_prompt = (
            (system + "\n\n" if system else "")
            + "你必须只输出一个 JSON 对象（不要 markdown 代码块），严格符合以下 JSON Schema：\n"
            + schema_json
        )
        # prompt 可以是字符串，也可以是多模态 content parts（Phase 105 视觉走这条）
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt},
        ]
        last_err: Exception | None = None
        for _ in range(2):  # 首次 + 带错误重试一次
            resp = call_with_retry(
                lambda: self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                    timeout=_timeout(timeout),
                    **thinking,
                ),
                what=f"llm.parse[{model}]",
                should_abort=_abort_of(cid),
                max_retries=retries,
                cid=cid,
            )
            choice = resp.choices[0]
            raw = choice.message.content or ""
            if getattr(choice, "finish_reason", None) == "length":
                last_err = LLMOutputTruncatedError(
                    f"结构化输出达到 {max_tokens} tokens 上限，已在 JSON 中途截断"
                )
                # 截断内容往往很大，不能再塞回下一次请求，否则重试 prompt 更长、更容易再次超限。
                messages.append({
                    "role": "user",
                    "content": "你上一份 JSON 因输出过长被截断。请显著精简字段内容后重新输出完整 JSON。",
                })
                continue
            try:
                return schema.model_validate_json(raw)
            except ValidationError as e:
                last_err = e
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": f"你输出的 JSON 未通过校验，错误如下，请修正后重新只输出 JSON：\n{e}",
                })
        raise ValueError(f"LLM 结构化输出解析失败（重试后仍不合法）: {last_err}")

    def parse_image(
        self,
        prompt: str,
        schema: type[T],
        *,
        images: list[str],
        model: str | None = None,
        system: str | None = None,
        max_tokens: int = 3000,
        cid: str | None = None,
    ) -> T:
        """视觉结构化抽取（Phase 105）。`images` 是 http(s) URL 或 data: URI。

        ⚠️ **强制 `response_format=json_object`，这不是格式讲究是性能开关。**
        实测（6 张真实小红书图，max_tokens 都是 3000）：

            裸 prompt     空正文 2/6   延迟中位 23.7s   out 中位 2622
            json_object   空正文 0/6   延迟中位  7.4s   out 中位  743

        prompt 里**已经写了** Phase 101/102 那套思考纪律，它照样把预算烧满；json_object
        一开思考链自己收住。这是第四次撞 DeepSeek 思考模式过度推理（Phase 11 ITINERARY /
        101 quick_take / 102 五处抽取 / 本次），也是「结构化输出必须走 parse() 而非裸
        prompt」这条不变式在视觉输入下的新证据。

        走的仍是 `parse()`：schema 校验、截断重试、传输层重试（Phase 103）全都复用，
        不另写一套。
        """
        parts: list[dict] = [{"type": "text", "text": prompt}]
        for url in images:
            parts.append({"type": "image_url", "image_url": {"url": url}})
        return self.parse(
            parts, schema, model=model or settings.model_vision,
            system=system, max_tokens=max_tokens, cid=cid,
            # 视觉走自己的旋钮：exp 模型对思考控制字段的支持与文本模型未必一致，
            # 且它已有一条实测验证过的刹车（上面那张 json_object 对照表）。
            effort=settings.vision_reasoning_effort,
        )

    def classify(
        self, prompt: str, schema: type[T], *, system: str | None = None,
        cid: str | None = None, effort: str | None = None,
        timeout: float | None = None, retries: int | None = None,
    ) -> T:
        """轻量分类：用便宜的模型（v4-flash），如页面类型判定。"""
        return self.parse(
            prompt, schema, model=settings.model_classifier, system=system,
            max_tokens=1024, cid=cid, effort=effort, timeout=timeout, retries=retries,
        )

    def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system: str | None = None,
        max_tokens: int = 8000,
        cid: str | None = None,
    ) -> str:
        """自由文本生成（行程/总结类）。"""
        return self.generate_with_reasoning(
            prompt, model=model, system=system, max_tokens=max_tokens, cid=cid
        )[0]

    @staticmethod
    def _build_messages(prompt: str | None, system: str | None, messages: list[dict] | None) -> list[dict]:
        """messages 与 prompt/system 二选一（Phase 31）：传 messages 时按原样透传，
        调用方自行构造标准 agent 轨迹（system / user / assistant+tool_calls / tool）。
        注意：DeepSeek 思考模式要求带 tool_calls 的 assistant 消息附 reasoning_content。
        """
        if messages is not None:
            return messages
        out = []
        if system:
            out.append({"role": "system", "content": system})
        out.append({"role": "user", "content": prompt or ""})
        return out

    def generate_with_reasoning(
        self,
        prompt: str | None = None,
        *,
        model: str | None = None,
        system: str | None = None,
        messages: list[dict] | None = None,
        max_tokens: int = 8000,
        cid: str | None = None,
        effort: str | None = None,
    ) -> tuple[str, str]:
        """自由文本生成，同时返回 (正文, 思考过程)。

        DeepSeek v4 系列在 message.reasoning_content 里返回推理链，
        用于对话界面「点击展开模型思考过程」（类 GPT/Claude）。
        正常结束却**什么都没返回**（正文和思考都空）时原样再问一次（harness 的 EMPTY_RESPONSE）。
        """
        from app.llm.retry import call_with_retry

        for _ in range(2):
            resp = call_with_retry(
                lambda: self._client.chat.completions.create(
                    model=model or settings.model_planner,
                    messages=self._build_messages(prompt, system, messages),
                    max_tokens=max_tokens,
                    **_thinking_kwargs(effort),
                ),
                what="llm.generate",
                should_abort=_abort_of(cid),
                cid=cid,
            )
            msg = resp.choices[0].message
            content, reasoning = msg.content or "", getattr(msg, "reasoning_content", None) or ""
            if content or reasoning:
                break
            _logger.warning("llm.generate returned an empty response, asking once more")
        return (content, reasoning)

    def stream_generate_with_reasoning(
        self,
        prompt: str | None = None,
        *,
        model: str | None = None,
        system: str | None = None,
        messages: list[dict] | None = None,
        max_tokens: int = 8000,
        cid: str | None = None,
        effort: str | None = None,
    ):
        """流式生成（Phase 11）：逐块 yield ("reasoning"|"content", 增量文本)。

        DeepSeek 先流式输出 reasoning_content 再输出 content；
        调用方累积增量并周期性落库，实现前端边生成边显示。

        Phase 103 重试：**只在还没吐出任何内容时**才重试。一旦 yield 过 delta，调用方
        （`orchestrator._stream_into`）已经把它累进 content_parts 并周期落库了，重开一条流
        会让用户看到重复的正文——比一次失败更糟。`produced` 守住这条线：首块之前的连接错
        走重试（这正是最常见的失败点：建连/首字节），之后的一律上抛。
        """
        from app.agent.cancel import TurnCancelled
        from app.llm.retry import (
            LLMUnavailableError, delay_for, is_down, is_retryable, mark_down, notify_retry,
            retry_limit, sleep_interruptible,
        )

        if is_down(cid):
            raise LLMUnavailableError("llm.stream: model marked unavailable for this turn")
        abort = _abort_of(cid)
        limit = retry_limit()
        attempt = 0
        empty_retried = False
        while True:
            produced = False
            stream = None
            watchdog: _Watchdog | None = None
            try:
                # ⚠️ 这里**不能**再套 `call_with_retry`：本函数自己就是重试循环，套上去就是
                # 双层嵌套（内层 5 次 × 外层 5 次 = 36 次请求），503 风暴下会把 provider
                # 打爆。单测 test_stream_gives_up_after_max_retries 钉住总次数。
                stream = self._client.chat.completions.create(
                    model=model or settings.model_planner,
                    messages=self._build_messages(prompt, system, messages),
                    max_tokens=max_tokens,
                    stream=True,
                    timeout=_timeout(stream=True),
                    **_thinking_kwargs(effort),
                )
                _track(cid, stream)
                watchdog = _Watchdog(stream, settings.llm_first_token_timeout_s,
                                     settings.llm_stream_idle_timeout_s)
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    watchdog.kick()
                    choice = chunk.choices[0]
                    delta = choice.delta
                    rc = getattr(delta, "reasoning_content", None)
                    if rc:
                        produced = True
                        yield ("reasoning", rc)
                    if delta.content:
                        produced = True
                        yield ("content", delta.content)
                    # 末块带 finish_reason：length=触到 max_tokens 被截断（P0，调用方据此提示/续写）
                    if getattr(choice, "finish_reason", None):
                        if not produced and not empty_retried and choice.finish_reason != "length":
                            break  # 正常结束却一个字都没有：下面原样再问一次
                        yield ("finish", choice.finish_reason)
                if watchdog.fired:
                    raise LLMStreamStalled("stream read timeout: no content from model")
                # 一个字都没吐（正常结束或空流）：原样再问一次，只此一次（harness 的 EMPTY_RESPONSE）
                if not produced and not empty_retried:
                    empty_retried = True
                    _logger.warning("llm.stream returned an empty response, asking once more")
                    continue
                return
            except (TurnCancelled, GeneratorExit, LLMUnavailableError):
                raise
            except BaseException as e:  # noqa: BLE001 — 判定完再决定放行还是重试
                if abort is not None and abort():
                    raise TurnCancelled() from e  # 停止接口关掉了流：这是取消，不是失败
                if watchdog is not None and watchdog.fired and not isinstance(e, LLMStreamStalled):
                    e = LLMStreamStalled(f"stream read timeout: no content from model ({e})")
                attempt += 1
                if produced or not is_retryable(e):
                    raise
                if attempt > limit:
                    mark_down(cid)
                    raise LLMUnavailableError(f"llm.stream failed after {limit} retries: {e}") from e
                wait = delay_for(attempt, e)
                _logger.warning(
                    "llm.stream failed before first token (%s/%s), retrying in %.1fs: %s",
                    attempt, limit, wait, e,
                )
                notify_retry(cid, attempt, limit)
                sleep_interruptible(wait, abort)
            finally:
                if watchdog is not None:
                    watchdog.stop()
                if stream is not None:
                    _untrack(cid, stream)


_default_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
