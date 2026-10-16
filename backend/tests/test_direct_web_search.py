"""「联网搜索」开关（2026-10-16）：直答先联网搜，且永不把工具调用标记展示给用户。

线上「合肥洗浴中心」：用户说「帮我查一下」，非规划分支的模型编了 `<tool_call>web_search…`
文本原样展示。
"""
import pytest

import app.agent.orchestrator as O


class _FakeLLM:
    def __init__(self, answer: str, queries=("合肥 洗浴中心 新开",)):
        self.answer = answer
        self.queries = list(queries)
        self.messages = None

    def classify(self, prompt, schema, **kw):
        return schema(queries=self.queries)

    def stream_generate_with_reasoning(self, messages, **kw):
        self.messages = messages
        yield "content", self.answer
        yield "finish", "stop"


@pytest.fixture
def direct(monkeypatch):
    finals: list[tuple[str, dict]] = []
    progress: list[str] = []
    monkeypatch.setattr(O, "gather_context", lambda *a, **k: {"block": "", "used": []})
    monkeypatch.setattr(O, "_assemble_history", lambda *a, **k: ([], ""))
    monkeypatch.setattr(O, "_recent_plan_prefix", lambda *a, **k: "")
    monkeypatch.setattr(O, "_add_streaming_message", lambda cid: "m1")
    monkeypatch.setattr(O, "_update_streaming_message", lambda *a, **k: None)
    monkeypatch.setattr(O, "_finalize_streaming_message",
                        lambda mid, content, reasoning, meta: finals.append((content, meta)))
    monkeypatch.setattr(O, "extract_and_save", lambda *a, **k: [])
    monkeypatch.setattr(O, "update_history_summary", lambda *a, **k: None)
    monkeypatch.setattr(O, "_progress", lambda cid, text, meta=None: progress.append(text))

    from app.tools import web_search_api

    async def _search(q, top_k=None):
        return [{"title": "某某汤泉 新店开业", "url": "https://example.com/a",
                 "content": "位于政务区，2025 年开业，人均 168 元。", "published": "2025-09-01"}]

    monkeypatch.setattr(web_search_api, "enabled", lambda: True)
    monkeypatch.setattr(web_search_api, "search", _search)

    def run(llm, search_on: bool):
        monkeypatch.setattr(O, "get_llm", lambda: llm)
        if search_on:
            O._WEB_SEARCH_CIDS.add("c1")
        try:
            O.run_direct_answer("c1", "推荐一个，帮我查一下", "u1")
        finally:
            O._WEB_SEARCH_CIDS.discard("c1")
        return finals[-1], progress

    return run


def test_search_on_injects_results_and_sources(direct):
    llm = _FakeLLM("推荐某某汤泉 [1]")
    (content, meta), progress = direct(llm, search_on=True)
    prompt = llm.messages[-1]["content"]
    assert "<web_results>" in prompt and "人均 168 元" in prompt
    assert meta["sources"] == [{"title": "某某汤泉 新店开业", "url": "https://example.com/a"}]
    assert meta["direct"] is True  # 前端据此不出攻略按钮
    assert any("正在联网搜索" in p for p in progress)


def test_search_off_does_not_search(direct):
    llm = _FakeLLM("常识回答")
    (content, meta), _ = direct(llm, search_on=False)
    assert "<web_results>" not in llm.messages[-1]["content"]
    assert "sources" not in meta


def test_no_queries_means_no_search(direct):
    llm = _FakeLLM("不客气", queries=())
    (content, meta), progress = direct(llm, search_on=True)
    assert "<web_results>" not in llm.messages[-1]["content"]
    assert not any("正在联网搜索" in p for p in progress)


def test_toolcall_markup_never_reaches_user(direct):
    leaked = ('<tool_call>web_search</tool_call>\n{"query": "合肥 汤泉"}\n'
              "Wait, I need to output properly formatted tool calls.")
    (content, _), _ = direct(_FakeLLM(leaked), search_on=False)
    assert "tool_call" not in content
    assert "联网搜索" in content  # 告诉用户打开开关


def test_singular_tool_call_tag_is_stripped():
    assert O._strip_toolcall_leak("答案在此\n<tool_call>web_search</tool_call>") == "答案在此"
    assert O._strip_toolcall_leak("<function_call>x") == ""
