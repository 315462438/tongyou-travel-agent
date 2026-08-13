"""Langfuse 埋点（Phase 24）单测：无 key 全 no-op、有 key 各集成点可创建。全离线（不发网络）。"""

import pytest

from app import observability as obs
from app.config import settings


@pytest.fixture(autouse=True)
def _reset_env_flag():
    obs._env_ready = False
    yield
    obs._env_ready = False


def _set_keys(monkeypatch, on: bool):
    monkeypatch.setattr(settings, "langfuse_enabled", on)
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-lf-test" if on else "")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk-lf-test" if on else "")


# ---------- 默认关闭：全部 no-op ----------

def test_disabled_is_full_noop(monkeypatch):
    _set_keys(monkeypatch, False)
    assert obs.enabled() is False
    assert obs.langchain_handler() is None
    assert obs.wrap_openai_client_cls() is None
    with obs.turn_trace(cid="c1", user_id="u1", input_text="hi") as t:
        assert t is None
    with obs.span("web_search", input_data="q") as s:
        assert s is None
    obs.flush()  # 不抛


def test_enabled_requires_keys(monkeypatch):
    monkeypatch.setattr(settings, "langfuse_enabled", True)
    monkeypatch.setattr(settings, "langfuse_public_key", "")
    monkeypatch.setattr(settings, "langfuse_secret_key", "")
    assert obs.enabled() is False  # 只开开关没 key 仍 no-op


# ---------- 启用：各集成点可创建（不发网络） ----------

def test_enabled_creates_handler_and_wrapper(monkeypatch):
    _set_keys(monkeypatch, True)
    assert obs.enabled() is True
    h = obs.langchain_handler()
    assert h is not None and "CallbackHandler" in type(h).__name__
    cls = obs.wrap_openai_client_cls()
    assert cls is not None  # langfuse.openai 包装类


def test_llm_client_fallback_plain_openai(monkeypatch):
    """未启用时 LLMClient 必须用裸 OpenAI（零行为变化）。"""
    _set_keys(monkeypatch, False)
    from app.llm.client import LLMClient

    c = LLMClient(api_key="x", base_url="https://example.com")
    assert type(c._client).__module__.startswith("openai")


def test_enabled_turn_trace_and_span_yield_real_objects(monkeypatch):
    """启用态：turn_trace/span 必须真的建出 span 对象（v4 API 回归——曾用错 v3 方法名）。

    不 flush，OTel span 只进本地缓冲，不发网络。
    """
    _set_keys(monkeypatch, True)
    with obs.turn_trace(cid="c1", user_id="u1", input_text="hi", metadata={"route": "direct"}) as t:
        assert t is not None, "turn_trace 未能创建 span（API 兼容性回归）"
        t.update(metadata={"route": "direct"})  # v4 span 有 update
    with obs.span("web_search", input_data="厦门") as s:
        assert s is not None
        s.update(output={"results": 3})
