"""LLMClient 统一封装（评审 🔴5）—— DeepSeek 版

- DeepSeek OpenAI 兼容接口（base_url=https://api.deepseek.com）
- parse():   结构化输出：json_object 模式 + Pydantic 校验 + 失败带错误重试一次
- generate(): 自由文本生成
- 模型分层：deepseek-v4-pro（规划/抽取）、deepseek-v4-flash（轻量分类）
"""

import json
import logging
from typing import TypeVar

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
            timeout=settings.llm_timeout_s,
        )

    def parse(
        self,
        prompt: str,
        schema: type[T],
        *,
        model: str | None = None,
        system: str | None = None,
        max_tokens: int = 8000,
        cid: str | None = None,
    ) -> T:
        """结构化输出：返回通过 Pydantic 校验的对象。校验失败带错误信息重试一次。

        Phase 103：**两层重试各管各的**——这里的 for 循环治「模型输出不合法」（校验失败/
        截断），`call_with_retry` 治「请求没打通」（429/5xx/连接断）。前者要改 prompt 再问，
        后者要原样重发，混在一起会把「合法的重发」错当成「模型又答错了」而消耗校验重试次数。
        """
        from app.llm.retry import call_with_retry

        model = model or settings.model_extractor
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        sys_prompt = (
            (system + "\n\n" if system else "")
            + "你必须只输出一个 JSON 对象（不要 markdown 代码块），严格符合以下 JSON Schema：\n"
            + schema_json
        )
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
                ),
                what=f"llm.parse[{model}]",
                should_abort=_abort_of(cid),
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

    def classify(
        self, prompt: str, schema: type[T], *, system: str | None = None, cid: str | None = None
    ) -> T:
        """轻量分类：用便宜的模型（v4-flash），如页面类型判定。"""
        return self.parse(
            prompt, schema, model=settings.model_classifier, system=system,
            max_tokens=1024, cid=cid,
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
    ) -> tuple[str, str]:
        """自由文本生成，同时返回 (正文, 思考过程)。

        DeepSeek v4 系列在 message.reasoning_content 里返回推理链，
        用于对话界面「点击展开模型思考过程」（类 GPT/Claude）。
        """
        from app.llm.retry import call_with_retry

        resp = call_with_retry(
            lambda: self._client.chat.completions.create(
                model=model or settings.model_planner,
                messages=self._build_messages(prompt, system, messages),
                max_tokens=max_tokens,
            ),
            what="llm.generate",
            should_abort=_abort_of(cid),
        )
        msg = resp.choices[0].message
        return (msg.content or "", getattr(msg, "reasoning_content", None) or "")

    def stream_generate_with_reasoning(
        self,
        prompt: str | None = None,
        *,
        model: str | None = None,
        system: str | None = None,
        messages: list[dict] | None = None,
        max_tokens: int = 8000,
        cid: str | None = None,
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
        from app.llm.retry import MAX_RETRIES, delay_for, is_retryable, sleep_interruptible

        abort = _abort_of(cid)
        attempt = 0
        while True:
            produced = False
            try:
                # ⚠️ 这里**不能**再套 `call_with_retry`：本函数自己就是重试循环，套上去就是
                # 双层嵌套（内层 5 次 × 外层 5 次 = 36 次请求），503 风暴下会把 provider
                # 打爆。单测 test_stream_gives_up_after_max_retries 钉住总次数。
                stream = self._client.chat.completions.create(
                    model=model or settings.model_planner,
                    messages=self._build_messages(prompt, system, messages),
                    max_tokens=max_tokens,
                    stream=True,
                )
                for chunk in stream:
                    if not chunk.choices:
                        continue
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
                        yield ("finish", choice.finish_reason)
                return
            except (TurnCancelled, GeneratorExit):
                raise
            except BaseException as e:  # noqa: BLE001 — 判定完再决定放行还是重试
                attempt += 1
                if produced or attempt > MAX_RETRIES or not is_retryable(e):
                    raise
                wait = delay_for(attempt, e)
                _logger.warning(
                    "llm.stream failed before first token (%s/%s), retrying in %.1fs: %s",
                    attempt, MAX_RETRIES, wait, e,
                )
                sleep_interruptible(wait, abort)


_default_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
