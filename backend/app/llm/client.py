"""LLMClient 统一封装（评审 🔴5）—— DeepSeek 版

- DeepSeek OpenAI 兼容接口（base_url=https://api.deepseek.com）
- parse():   结构化输出：json_object 模式 + Pydantic 校验 + 失败带错误重试一次
- generate(): 自由文本生成
- 模型分层：deepseek-v4-pro（规划/抽取）、deepseek-v4-flash（轻量分类）
"""

import json
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.config import settings

T = TypeVar("T", bound=BaseModel)


class LLMOutputTruncatedError(ValueError):
    """结构化输出达到模型长度上限，JSON 必然不完整。"""


class LLMClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        # Langfuse 埋点（Phase 24）：启用时换 drop-in 包装类，自动记录每次调用的
        # 完整 prompt/补全/用量（含流式）；未启用/失败回退裸 OpenAI，行为不变。
        from app.observability import wrap_openai_client_cls

        client_cls = wrap_openai_client_cls() or OpenAI
        self._client = client_cls(
            api_key=api_key or settings.deepseek_api_key,
            base_url=base_url or settings.deepseek_base_url,
        )

    def parse(
        self,
        prompt: str,
        schema: type[T],
        *,
        model: str | None = None,
        system: str | None = None,
        max_tokens: int = 8000,
    ) -> T:
        """结构化输出：返回通过 Pydantic 校验的对象。校验失败带错误信息重试一次。"""
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
            resp = self._client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
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

    def classify(self, prompt: str, schema: type[T], *, system: str | None = None) -> T:
        """轻量分类：用便宜的模型（v4-flash），如页面类型判定。"""
        return self.parse(
            prompt, schema, model=settings.model_classifier, system=system, max_tokens=1024
        )

    def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system: str | None = None,
        max_tokens: int = 8000,
    ) -> str:
        """自由文本生成（行程/总结类）。"""
        return self.generate_with_reasoning(
            prompt, model=model, system=system, max_tokens=max_tokens
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
    ) -> tuple[str, str]:
        """自由文本生成，同时返回 (正文, 思考过程)。

        DeepSeek v4 系列在 message.reasoning_content 里返回推理链，
        用于对话界面「点击展开模型思考过程」（类 GPT/Claude）。
        """
        resp = self._client.chat.completions.create(
            model=model or settings.model_planner,
            messages=self._build_messages(prompt, system, messages),
            max_tokens=max_tokens,
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
    ):
        """流式生成（Phase 11）：逐块 yield ("reasoning"|"content", 增量文本)。

        DeepSeek 先流式输出 reasoning_content 再输出 content；
        调用方累积增量并周期性落库，实现前端边生成边显示。
        """
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
                yield ("reasoning", rc)
            if delta.content:
                yield ("content", delta.content)
            # 末块带 finish_reason：length=触到 max_tokens 被截断（P0，调用方据此提示/续写）
            if getattr(choice, "finish_reason", None):
                yield ("finish", choice.finish_reason)


_default_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
