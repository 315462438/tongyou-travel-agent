"""2026-07-30 体验走查修复批次的回归测试（docs/task_plans/体验走查修复批次-2026-07-30.md）。

覆盖：表格安全插图（P0-2）、单括号占位符（P2-d）、灵感图图注（P2-a）、
小红书尝试上限（P1-1）、360 相关性过滤（P1-4）、深度研究终稿择优（P0-1）、
预算口径对账（P2-b）。全部离线。
"""

import asyncio

from app.agent.orchestrator import _embed_images

IMG_MAP = {
    "锦城公园": "/travel/api/img?u=JC",
    "小红书灵感·成都懒人四日游·1": "/travel/api/img?u=XHS1",
}

TABLE = (
    "## Day 1\n"
    "| 时段 | 地点 | 花费 |\n"
    "| --- | --- | --- |\n"
    "| 下午 | **锦城公园**：湖边散步 | 免费 |\n"
    "| 晚上 | 双子塔夜景 | 免费 |\n"
    "\n收尾一段。"
)


def _table_intact(out: str) -> bool:
    """表格 4 行（表头+分隔+2 数据行）必须连续，中间不能插任何非表格行。"""
    lines = out.split("\n")
    idx = [i for i, l in enumerate(lines) if l.lstrip().startswith("|")]
    return len(idx) == 4 and idx[-1] - idx[0] == 3


# ---------- P0-2：插图不劈开表格 ----------

def test_fallback_image_not_inside_table():
    # 图片名在表格行内被加粗提及 → 兜底插图必须推迟到表格结束之后
    out = _embed_images(TABLE, {"锦城公园": IMG_MAP["锦城公园"]})
    assert "![锦城公园](/travel/api/img?u=JC)" in out
    assert _table_intact(out)
    # 图片出现在最后一个表格行之后
    assert out.index("![锦城公园]") > out.index("| 晚上 |")


def test_placeholder_inside_table_cell_moved_after_table():
    text = TABLE.replace("湖边散步", "湖边散步 [[img:锦城公园]]")
    out = _embed_images(text, {"锦城公园": IMG_MAP["锦城公园"]})
    assert "[[img:" not in out
    assert "![锦城公园](/travel/api/img?u=JC)" in out
    assert _table_intact(out)


def test_streaming_no_fallback_and_strips_partial():
    out = _embed_images(TABLE + "\n最后 [[img:锦城", {"锦城公园": IMG_MAP["锦城公园"]},
                        streaming=True)
    assert "[[img:" not in out
    assert _table_intact(out)


# ---------- P2-d：单括号 / 全角冒号占位符 ----------

def test_single_bracket_placeholder_replaced():
    out = _embed_images("看看 [img:锦城公园] 吧", {"锦城公园": IMG_MAP["锦城公园"]})
    assert "[img:" not in out
    assert "![锦城公园](/travel/api/img?u=JC)" in out


def test_fullwidth_colon_placeholder_replaced():
    out = _embed_images("[[img：锦城公园]]", {"锦城公园": IMG_MAP["锦城公园"]})
    assert "img：" not in out and "/travel/api/img?u=JC" in out


def test_unmatched_single_bracket_removed():
    out = _embed_images("[img:小红书灵感·📍不存在✔️·2]", IMG_MAP)
    assert "[img:" not in out


# ---------- P2-a：灵感图兜底带图注 ----------

def test_inspiration_fallback_has_caption():
    text = "# 标题\n\n## Day 1 好玩的\n\n正文一段。"
    out = _embed_images(text, {"小红书灵感·成都懒人四日游·1": "/travel/api/img?u=XHS1"})
    assert "![小红书灵感图｜成都懒人四日游](/travel/api/img?u=XHS1)" in out
    assert "*图源：小红书笔记「成都懒人四日游」*" in out


# ---------- P1-1：小红书尝试上限 ----------

def test_collect_xhs_attempt_cap(monkeypatch):
    from app.tools import xhs_mcp

    calls = {"detail": 0}
    feeds = [{"feed_id": f"f{i}", "xsec_token": "t", "title": f"笔记{i}"} for i in range(20)]

    async def fake_search(_kw):
        return feeds

    async def fake_detail(_fid, _tok):
        calls["detail"] += 1
        return {"title": "太短", "desc": "短", "images": []}  # 永远不合格

    monkeypatch.setattr(xhs_mcp, "enabled", lambda: True)
    monkeypatch.setattr(xhs_mcp, "search_notes", fake_search)
    monkeypatch.setattr(xhs_mcp, "note_detail", fake_detail)

    seen = []
    out = asyncio.run(xhs_mcp.collect_xhs_sources(
        "成都", limit=5, on_note=lambda i, total, title: seen.append((i, title)),
    ))
    assert out == []
    assert calls["detail"] == 7  # n+2，不再无限抓
    assert len(seen) == 7 and seen[0][0] == 1  # 逐篇进度回调


def test_collect_xhs_progress_callback_error_ignored(monkeypatch):
    from app.tools import xhs_mcp

    async def fake_search(_kw):
        return [{"feed_id": "f", "xsec_token": "t", "title": "好笔记"}]

    async def fake_detail(_fid, _tok):
        return {"title": "好笔记", "desc": "长" * 200, "images": []}

    monkeypatch.setattr(xhs_mcp, "enabled", lambda: True)
    monkeypatch.setattr(xhs_mcp, "search_notes", fake_search)
    monkeypatch.setattr(xhs_mcp, "note_detail", fake_detail)

    def boom(*_a):
        raise RuntimeError("progress boom")

    out = asyncio.run(xhs_mcp.collect_xhs_sources("成都", limit=1, on_note=boom))
    assert len(out) == 1  # 回调炸了不影响采集


# ---------- P1-4：360 结果相关性过滤 ----------

def test_360_relevance_filter():
    from app.tools.browser_tool import BrowserTool

    rel = BrowserTool._relevant_to_query
    q = "重庆 西安 国庆 酒店价格"
    assert rel("重庆国庆酒店均价盘点", q)
    assert rel("西安旅游攻略", q)
    assert not rel("唧唧Down下载-唧唧Down中文版", q)
    assert not rel("哔哩哔哩下载中心", q)
    assert not rel("", q)
    assert rel("任何标题", "短 q")  # 无 ≥2 长度词元 → 放行


def test_bing_results_also_relevance_filtered():
    """搜索框校验通过但结果是垃圾页（全 Facebook 链接）→ 必应路径也要滤掉。"""
    from app.tools.browser_tool import BrowserTool

    rel = BrowserTool._relevant_to_query
    q = "武汉到长沙高铁二等座票价 时刻表"
    garbage = ["Facebook", "Log Into Facebook", "Facebook - log in or sign up"]
    assert all(not rel(t, q) for t in garbage)
    assert rel("武汉到长沙高铁时刻表查询", q)


# ---------- P0-1：深度研究终稿择优 ----------

class _Msg:
    def __init__(self, type_, content):
        self.type = type_
        self.content = content


def test_extract_answer_prefers_report_over_closing_remark():
    from app.agent.deep_research import _extract_answer

    report = "# 对比报告\n\n" + "详细内容。" * 400  # 长报告
    closing = "报告已生成。核心结论：西安更划算。"
    result = {"messages": [_Msg("ai", report), _Msg("ai", closing)]}
    assert _extract_answer(result) == report


def test_extract_answer_keeps_last_when_no_big_earlier():
    from app.agent.deep_research import _extract_answer

    result = {"messages": [_Msg("ai", "我先查一下资料。"), _Msg("ai", "这是最终的简短回答。")]}
    assert _extract_answer(result) == "这是最终的简短回答。"


def test_extract_answer_ignores_history_before_last_human():
    """上线当天真实翻车：state 带注入历史，历史里的旧攻略比本轮报告长 → 被错当终稿。"""
    from app.agent.deep_research import _extract_answer

    old_guide = "# 武汉2日美食攻略\n\n" + "老内容。" * 800   # 历史里的超长旧回复
    report = "# 长沙 vs 南昌对比\n\n" + "本轮内容。" * 300
    closing = "报告已生成。"
    result = {"messages": [
        _Msg("human", "武汉美食攻略"), _Msg("ai", old_guide),
        _Msg("human", "长沙和南昌选哪个"), _Msg("ai", report), _Msg("ai", closing),
    ]}
    assert _extract_answer(result) == report


def test_extract_answer_empty():
    from app.agent.deep_research import _extract_answer

    assert _extract_answer({"messages": []}) == ""
    assert _extract_answer(None) == ""


# ---------- P2-b：预算口径对账 ----------

def test_budget_stated_total_mismatch_note():
    from app.agent.budget import build_budget_payload
    from app.schemas.budget_schema import BudgetData, BudgetLine

    data = BudgetData(
        headcount=2,
        items=[BudgetLine(category="住宿", name="酒店3晚", day=0, amount=600)],
        guide_stated_total=3210,  # 正文合计远大于逐项累加（1200）
    )
    payload = build_budget_payload(data)
    assert payload["group_total"] == 1200
    assert any("¥3210" in n and "逐项累加" in n for n in payload["notes"])


def test_budget_stated_total_close_no_note():
    from app.agent.budget import build_budget_payload
    from app.schemas.budget_schema import BudgetData, BudgetLine

    data = BudgetData(
        headcount=2,
        items=[BudgetLine(category="住宿", name="酒店3晚", day=0, amount=600)],
        guide_stated_total=1250,  # 差 <20% → 不加注记
    )
    payload = build_budget_payload(data)
    assert not any("有差异" in n for n in payload["notes"])


# ---------- 2026-07-31：停止链路补全（budget/poster/反思） ----------

def test_budget_stop_finalizes_and_clears_flag(monkeypatch):
    """点停止后：占位消息终稿为「已停止」，且取消标记被清（残留会误杀下一轮）。"""
    from app.agent import budget
    from app.agent.cancel import is_cancelled, request_cancel

    finals = []
    monkeypatch.setattr(budget, "_add_streaming", lambda cid: "m1")
    monkeypatch.setattr(budget, "_finalize", lambda mid, text, payload: finals.append(text))

    async def fake_run(cid, message_id, msg_id):
        from app.agent import cancel
        cancel.check(cid)

    monkeypatch.setattr(budget, "_run", fake_run)
    request_cancel("c-stop")
    budget.generate_budget("c-stop", "msg")
    assert finals == ["已停止本次预算统计。"]
    assert not is_cancelled("c-stop")  # 标记必须被清


def test_poster_stop_clears_flag(monkeypatch):
    from app.agent import poster
    from app.agent.cancel import is_cancelled, request_cancel

    finals = []
    monkeypatch.setattr(poster, "_add_streaming", lambda cid: "m1")
    monkeypatch.setattr(poster, "_finalize", lambda mid, text, payload: finals.append(text))

    async def fake_run(cid, message_id, msg_id):
        from app.agent import cancel
        cancel.check(cid)

    monkeypatch.setattr(poster, "_run", fake_run)
    request_cancel("c-stop2")
    poster.generate_poster("c-stop2", "msg")
    assert finals == ["已停止本次海报生成。"]
    assert not is_cancelled("c-stop2")


def test_critique_node_respects_cancel():
    import pytest

    from app.agent import nodes
    from app.agent.cancel import TurnCancelled, clear_cancel, request_cancel

    request_cancel("c-crit")
    try:
        with pytest.raises(TurnCancelled):
            nodes.critique_node({"cid": "c-crit", "user_text": "x", "guide": "y", "rounds": 0})
    finally:
        clear_cancel("c-crit")


def test_wait_cancellable_returns_result_and_aborts_on_cancel():
    from app.agent import cancel

    async def slow_ok():
        await asyncio.sleep(0.05)
        return 42

    assert asyncio.run(cancel.wait_cancellable("c-wc", slow_ok(), poll_s=0.02)) == 42

    async def scenario():
        async def hang():
            await asyncio.sleep(30)

        cancel.request_cancel("c-wc2")
        try:
            await cancel.wait_cancellable("c-wc2", hang(), poll_s=0.02)
        finally:
            cancel.clear_cancel("c-wc2")

    import pytest
    with pytest.raises(cancel.TurnCancelled):
        asyncio.run(scenario())
