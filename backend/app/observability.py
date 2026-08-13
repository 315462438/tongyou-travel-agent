"""Langfuse 可观测埋点（Phase 24）

三层：
- turn 级：`turn_trace()` 包住一轮对话（session_id=cid → Langfuse 按会话分组）；
- LLM 级：`wrap_openai_client()` 给 LLMClient 换 langfuse.openai 的 drop-in 包装
  （自动记每次调用的完整 prompt/补全/用量，含流式）；
- 工具级：研究模式 `langchain_handler()` 挂进 agent config（LangGraph 全图自动成 trace 树，
  含每轮模型请求 messages 与每个工具调用）；guide 流水线用 `span()` 手动包关键步骤。

铁律：**没配 key = 全部 no-op；埋点任何异常只 warn，绝不影响业务。**
"""

import logging
import os
from contextlib import contextmanager

from app.config import settings

logger = logging.getLogger(__name__)

_env_ready = False


def enabled() -> bool:
    return bool(
        settings.langfuse_enabled and settings.langfuse_public_key and settings.langfuse_secret_key
    )


def _ensure_env() -> None:
    """langfuse SDK 从环境变量读配置；首次使用前写入。"""
    global _env_ready
    if _env_ready:
        return
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
    os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)
    _env_ready = True


def _client():
    if not enabled():
        return None
    _ensure_env()
    try:
        from langfuse import get_client

        return get_client()
    except Exception:  # noqa: BLE001
        logger.warning("langfuse client init failed", exc_info=True)
        return None


@contextmanager
def turn_trace(*, cid: str, user_id: str, input_text: str, metadata: dict | None = None):
    """一轮对话 = 一条 trace。session_id=cid，Langfuse 界面按会话聚合各轮。

    langfuse SDK v4 API：trace 级属性（session/user/metadata）用 `propagate_attributes`
    上下文传播，根 span 用 `start_as_current_observation(as_type="span")`。
    yield 的 span 可为 None（未启用/失败），调用方用 `if span:` 防御；span 只有
    `.update()/.end()`（v4 没有 update_trace）。
    """
    lf = _client()
    if lf is None:
        yield None
        return
    opened: list = []
    span_obj = None
    try:
        from langfuse import propagate_attributes

        cm_attr = propagate_attributes(
            session_id=cid, user_id=user_id or None,
            trace_name="conversation_turn", metadata=metadata or None,
        )
        cm_attr.__enter__()
        opened.append(cm_attr)
        cm_span = lf.start_as_current_observation(
            name="conversation_turn", as_type="span", input=input_text,
        )
        span_obj = cm_span.__enter__()
        opened.append(cm_span)
    except Exception:  # noqa: BLE001
        logger.warning("langfuse turn_trace failed", exc_info=True)
        span_obj = None
    try:
        yield span_obj
    finally:
        for cm in reversed(opened):
            try:
                cm.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                logger.warning("langfuse turn_trace close failed", exc_info=True)


@contextmanager
def span(name: str, input_data=None):
    """手动步骤 span（guide 流水线的搜索/读页等）。未启用时零开销。"""
    lf = _client()
    if lf is None:
        yield None
        return
    cm = None
    s = None
    try:
        cm = lf.start_as_current_observation(name=name, as_type="span", input=input_data)
        s = cm.__enter__()
    except Exception:  # noqa: BLE001
        s = None
    try:
        yield s
    finally:
        if cm is not None:
            try:
                cm.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass


def langchain_handler():
    """LangChain/LangGraph 回调（研究模式 agent 全图追踪）。未启用返回 None。"""
    if not enabled():
        return None
    _ensure_env()
    try:
        from langfuse.langchain import CallbackHandler

        return CallbackHandler()
    except Exception:  # noqa: BLE001
        logger.warning("langfuse langchain handler init failed", exc_info=True)
        return None


def wrap_openai_client_cls():
    """返回带埋点的 OpenAI 客户端类；未启用/失败返回 None（调用方回退裸 openai）。"""
    if not enabled():
        return None
    _ensure_env()
    try:
        from langfuse.openai import OpenAI as LangfuseOpenAI

        return LangfuseOpenAI
    except Exception:  # noqa: BLE001
        logger.warning("langfuse openai wrapper unavailable", exc_info=True)
        return None


def flush() -> None:
    """turn 结束时冲刷缓冲（在后台线程里调用，不挡请求路径）。"""
    lf = _client()
    if lf is None:
        return
    try:
        lf.flush()
    except Exception:  # noqa: BLE001
        logger.warning("langfuse flush failed", exc_info=True)
