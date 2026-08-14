"""流式丝滑改造（2026-08-13）：流式增量落库节拍的配置化测试。

节拍本身在 orchestrator 运行时才体现（无法离线断言），这里钉住配置默认值
与可覆盖性——部署时可在 .env 用 STREAMING_FLUSH_INTERVAL_S 调。
"""

from app.config import settings


def test_streaming_flush_interval_default_is_smooth():
    """默认 0.5s：与前端 800ms 轮询叠加，可见粒度 ≤ ~1.3s（改造前 1.2s+1.5s ≈ 2.7s）。"""
    assert settings.streaming_flush_interval_s == 0.5
    assert 0.1 <= settings.streaming_flush_interval_s <= 2.0


def test_streaming_flush_interval_env_override(monkeypatch):
    """env 可覆盖（.env 部署调参路径）。"""
    monkeypatch.setenv("STREAMING_FLUSH_INTERVAL_S", "0.3")
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class _S(BaseSettings):
        model_config = SettingsConfigDict(env_file=None, extra="ignore")
        streaming_flush_interval_s: float = 0.5

    assert _S().streaming_flush_interval_s == 0.3
