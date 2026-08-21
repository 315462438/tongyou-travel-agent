"""攻略触到长度上限时自动续写（2026-08-04）。

线上现象：多城 7 天攻略被从「**人均（含」这种半句处硬切断，只补了一句
「已截断，可要我分段生成」——用户拿到的是残缺正文。现在改成自动续写，
续满仍未写完才提示。全部离线（LLM 用 fake）。
"""

import pytest

from app.agent import orchestrator as orch
from app.config import settings
from app.schemas.chat_schema import Preference


class _FakeLLM:
    """按预设脚本流式吐字：每个元素是 (正文, finish_reason)。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[list[dict]] = []

    def stream_generate_with_reasoning(self, *, messages, model=None, max_tokens=None, cid=None):
        self.calls.append(messages)
        text, finish = self.script.pop(0) if self.script else ("", "stop")
        if text:
            yield ("content", text)
        yield ("finish", finish)


@pytest.fixture()
def wired(monkeypatch):
    """把 generate_guide_streaming 的外部依赖全部换成假的，只留流式与续写逻辑。"""
    saved = {"content": None}
    monkeypatch.setattr(orch, "gather_context", lambda *a, **k: {"block": "", "used": []})
    monkeypatch.setattr(orch, "_build_image_context", lambda sources: ({}, ""))
    monkeypatch.setattr(orch, "build_guide_messages", lambda *a, **k: [{"role": "user", "content": "q"}])
    monkeypatch.setattr(orch, "_history_text", lambda cid: "")
    monkeypatch.setattr(orch, "_add_streaming_message", lambda cid: "m1")
    monkeypatch.setattr(orch, "_update_streaming_message", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_finalize_streaming_message", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_progress", lambda *a, **k: saved.__setitem__("progress", a))
    monkeypatch.setattr(orch, "_waypoint_directive", lambda pref: "")
    monkeypatch.setattr("app.agent.realtime_guard.credibility_directive", lambda *a, **k: "")
    return saved


# 正文必须 >50 字符，否则会撞上「输出过短 = 工具调用泄漏」的既有防线（与本测试无关）
PAD = "。".join(["苍山洱海慢行，古城闲逛，环海西路骑行"] * 3)


def _run(llm, monkeypatch):
    monkeypatch.setattr(orch, "get_llm", lambda: llm)
    guide, _reasoning, _mid, _mem = orch.generate_guide_streaming(
        "c1", "去马来西亚玩7天", Preference(destination="吉隆坡、仙本那"), "route", [], "u1",
    )
    return guide


def test_truncated_guide_is_continued(wired, monkeypatch):
    """第一次被截断 → 自动续写，正文拼接完整，且不留「已截断」提示。"""
    head, tail = f"# 攻略\n\n{PAD}**人均（含", "国际机票）约 ¥9,000"
    llm = _FakeLLM([(head, "length"), (tail, "stop")])
    guide = _run(llm, monkeypatch)
    assert guide == head + tail  # 从半句处无缝接上
    assert "截断" not in guide  # 续写成功就不该再吓用户
    assert len(llm.calls) == 2


def test_continuation_passes_partial_and_instruction(wired, monkeypatch):
    """续写请求必须带上已生成正文 + 明确的「接着最后一个字符写」纪律。"""
    llm = _FakeLLM([(PAD, "length"), ("后半段", "stop")])
    _run(llm, monkeypatch)
    cont = llm.calls[1]
    assert cont[-2]["role"] == "assistant" and cont[-2]["content"] == PAD
    assert cont[-1]["role"] == "user"
    assert cont[-1]["content"] == orch.CONTINUE_GUIDE_PROMPT
    assert "不要重复" in orch.CONTINUE_GUIDE_PROMPT
    assert "紧接着最后一个字符继续写" in orch.CONTINUE_GUIDE_PROMPT


def test_multiple_continuations_until_done(wired, monkeypatch):
    llm = _FakeLLM([(PAD, "length"), ("B", "length"), ("C", "stop")])
    assert _run(llm, monkeypatch) == PAD + "BC"
    assert len(llm.calls) == 3


def test_still_truncated_after_max_continuations_warns(wired, monkeypatch):
    """续满上限仍没写完才提示——而且措辞是「续写几轮后仍未写完」，不是「已截断」。"""
    llm = _FakeLLM([(PAD, "length")] * (settings.guide_max_continuations + 1))
    guide = _run(llm, monkeypatch)
    assert guide.startswith(PAD * (settings.guide_max_continuations + 1))
    assert "续写几轮后仍未写完" in guide
    assert len(llm.calls) == settings.guide_max_continuations + 1


def test_no_continuation_when_not_truncated(wired, monkeypatch):
    llm = _FakeLLM([(PAD, "stop")])
    guide = _run(llm, monkeypatch)
    assert guide == PAD and len(llm.calls) == 1


def test_guide_max_tokens_raised():
    """8000 对多城长行程不够（线上实证）。"""
    assert settings.guide_max_tokens >= 16000
    assert settings.guide_max_continuations >= 1
