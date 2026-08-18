"""从 dsh 搬过来的三样（Phase 89）单测：

1. 重复调用守卫（repeat-tool-reminder）
2. 上下文清单（Model-visible ⟺ logged 的可落地版）
3. 幂等中段截断（compaction-tool-result-pruner 的核心约束）

全离线，无 LLM、无网络。
"""

import asyncio

import pytest

from app.agent.context_manifest import attach, build_manifest
from app.agent.repeat_guard import (
    RepeatGuard,
    canonical_key,
    guard_tool,
    guard_tools,
    owner_from_config,
)
from app.agent.truncate import BRIEF, TOOL_RESULT, TruncateBudget


# ==================== 1. 重复调用守卫 ====================

def test_reminder_fires_at_thresholds_only():
    g = RepeatGuard(thresholds=(3, 6))
    got = [g.check("web_search", {"q": "亚庇"}) for _ in range(7)]
    fired = [i + 1 for i, r in enumerate(got) if r]
    assert fired == [3, 6]


def test_different_args_reset_the_chain():
    """换了参数就是新查询，不该被计成重复。"""
    g = RepeatGuard(thresholds=(3,))
    g.check("web_search", {"q": "亚庇"})
    g.check("web_search", {"q": "亚庇"})
    g.check("web_search", {"q": "沙巴"})       # 重置
    assert g.check("web_search", {"q": "亚庇"}) is None


def test_argument_order_does_not_matter():
    """参数只是顺序不同，必须判为同一次调用（规范化的意义）。"""
    a = canonical_key("amap_poi", {"city": "亚庇", "kw": "海滩"})
    b = canonical_key("amap_poi", {"kw": "海滩", "city": "亚庇"})
    assert a == b


def test_excluded_tools_are_transparent_to_the_chain():
    """被排除的工具既不累加也不重置——否则记账类工具一插进来就把循环「洗白」了。

    这是 dsh 特意点名的设计：search X → read_source → search X 仍算连续两次 search X。
    """
    g = RepeatGuard(thresholds=(3,), exclude=("read_source",))
    g.check("web_search", {"q": "亚庇"})
    g.check("read_source", {"source_id": "s1"})   # 透明
    g.check("web_search", {"q": "亚庇"})
    g.check("read_source", {"source_id": "s2"})   # 透明
    assert g.check("web_search", {"q": "亚庇"}) is not None  # 第 3 次触发


def test_same_threshold_fires_once_per_run():
    """同一档只提醒一次，不要在同一个 run 里反复刷。"""
    g = RepeatGuard(thresholds=(3,))
    for _ in range(3):
        last = g.check("web_search", {"q": "x"})
    assert last is not None
    assert g.check("web_search", {"q": "x"}) is None  # 第 4 次不再提醒


def test_first_threshold_is_short_later_ones_name_the_args():
    g = RepeatGuard(thresholds=(3, 6))
    first = None
    for _ in range(3):
        first = g.check("web_search", {"q": "亚庇"})
    later = None
    for _ in range(3):
        later = g.check("web_search", {"q": "亚庇"})
    assert "亚庇" not in first        # 轻提示不引用参数
    assert "亚庇" in later            # 详细版点名参数
    assert "web_search" in first and "web_search" in later


def test_long_arguments_are_capped_in_the_reminder():
    """判重永远用完整串，但提醒里的引用要截断——否则打转的长参数会原样滚进下一次请求。"""
    g = RepeatGuard(thresholds=(2, 3))  # 第 2 档才是引用参数的详细版
    payload = {"q": "亚" * 5000}
    for _ in range(3):
        note = g.check("web_search", payload)
    assert note is not None and len(note) < 1000
    assert "省略" in note


def test_reset_clears_the_chain():
    g = RepeatGuard(thresholds=(2,))
    g.check("web_search", {"q": "x"})
    g.reset()
    assert g.check("web_search", {"q": "x"}) is None


def test_invalid_thresholds_fail_loud():
    """配置错误必须响——静默回落默认值会让 bug 一直藏着。"""
    for bad in ((), (1,), (0, 3)):
        with pytest.raises(ValueError):
            RepeatGuard(thresholds=bad)


def test_unserializable_args_do_not_crash():
    g = RepeatGuard(thresholds=(2,))
    obj = object()
    g.check("t", {"x": obj})
    assert g.check("t", {"x": obj}) is not None  # 同一对象判为重复，且不抛异常


# ---------- 工具包装 ----------

def test_guard_tool_appends_reminder_to_string_result():
    g = RepeatGuard(thresholds=(2,))

    async def web_search(q: str) -> str:
        return f"结果：{q}"

    wrapped = guard_tool(web_search, g)
    first = asyncio.run(wrapped(q="亚庇"))
    second = asyncio.run(wrapped(q="亚庇"))
    assert first == "结果：亚庇"          # 首次原样，不打扰
    assert second.startswith("结果：亚庇")  # 提醒是追加，不替换（工具结果保持可审计）
    assert "系统提示" in second


def test_guard_tool_counts_positional_and_keyword_the_same():
    """同一次调用无论位置传还是关键字传，必须落到同一个链键。"""
    g = RepeatGuard(thresholds=(2,))

    async def web_search(q: str) -> str:
        return "ok"

    wrapped = guard_tool(web_search, g)
    asyncio.run(wrapped("亚庇"))          # 位置
    assert "系统提示" in asyncio.run(wrapped(q="亚庇"))  # 关键字 → 同一链


def test_guard_tool_preserves_signature_for_schema_inference():
    """langchain 靠签名推工具 schema，包装不能把它弄丢。

    Phase 95 起会额外追加一个 `config` 参数（LangChain 注入用），原有参数必须原样保留、
    顺序不变。
    """
    import inspect

    g = RepeatGuard()

    async def amap_poi(city: str, kw: str = "") -> str:
        """查 POI。"""
        return "ok"

    wrapped = guard_tool(amap_poi, g)
    assert wrapped.__name__ == "amap_poi"
    assert wrapped.__doc__ == "查 POI。"
    assert list(inspect.signature(wrapped).parameters) == ["city", "kw", "config"]


def test_failed_calls_still_count():
    """模型反复砸一个失败的调用，正是最该打断的循环（dsh 明确点名）。"""
    g = RepeatGuard(thresholds=(2,))

    async def flaky(q: str) -> str:
        return "调用失败：配额已用尽"

    wrapped = guard_tool(flaky, g)
    asyncio.run(wrapped(q="x"))
    assert "系统提示" in asyncio.run(wrapped(q="x"))


def test_non_string_results_pass_through_untouched():
    g = RepeatGuard(thresholds=(2,))

    async def structured(q: str) -> dict:
        return {"data": 1}

    wrapped = guard_tool(structured, g)
    asyncio.run(wrapped(q="x"))
    assert asyncio.run(wrapped(q="x")) == {"data": 1}  # 不硬塞提示进结构化结果


def test_guard_tools_keeps_unwrappable_tools():
    """包装失败不能让整个工具集构建失败。"""

    def sync_tool(q: str) -> str:  # 同步函数，包装会抛
        return "ok"

    async def ok_tool(q: str) -> str:
        return "ok"

    out = guard_tools([sync_tool, ok_tool], RepeatGuard())
    assert len(out) == 2 and out[0] is sync_tool  # 原样保留


# ---------- 按调用方分链（Phase 95） ----------

def _cfg(ns: str) -> dict:
    """构造一个带 checkpoint_ns 的 config，形如 LangChain 注入的那个。"""
    return {"configurable": {"checkpoint_ns": ns}}


def test_concurrent_owners_do_not_accumulate_into_one_chain():
    """核心：并发子代理用相同参数调同一工具，不该互相累加成假重复。

    这是整个改动的理由——误报会往模型上下文里注入一句事实错误的系统提示
    （「你已经连续 3 次调用 X」，而它其实是第一次调），模型无从核对真伪。
    """
    g = RepeatGuard(thresholds=(3,))
    a, b, c = "task:x", "task:x|1", "task:x|2"
    # 三个子代理交替各调一次同样的参数：换成共享单链时第三次就会误报
    assert g.check("amap_city_brief", {"city": "杭州"}, a) is None
    assert g.check("amap_city_brief", {"city": "杭州"}, b) is None
    assert g.check("amap_city_brief", {"city": "杭州"}, c) is None
    # 各自再调两次才各自到 3 次
    for owner in (a, b, c):
        assert g.check("amap_city_brief", {"city": "杭州"}, owner) is None
        assert g.check("amap_city_brief", {"city": "杭州"}, owner) is not None


def test_main_agent_and_subagent_are_separate_chains():
    """主 agent（owner 空串）与子代理互不干扰。"""
    g = RepeatGuard(thresholds=(2,))
    assert g.check("fetch_url", {"url": "u"}, "") is None
    assert g.check("fetch_url", {"url": "u"}, "task:s") is None  # 子代理首次，不该报
    assert g.check("fetch_url", {"url": "u"}, "") is not None    # 主 agent 第二次才报


def test_same_owner_chain_survives_across_supersteps():
    """同一子代理跨 superstep：ns 尾段每步都变，前缀不变 → 链必须连着。

    这正是不能直接用 parent_run_id 的原因（它每个 superstep 都变）。
    """
    g = RepeatGuard(thresholds=(3,))
    steps = [
        _cfg("task:abc|model:s1"),
        _cfg("task:abc|tools:s2"),
        _cfg("task:abc|model:s3"),
    ]
    owners = [owner_from_config(c) for c in steps]
    assert owners == ["task:abc"] * 3          # 前缀稳定
    got = [g.check("amap_poi", {"kw": "西湖"}, o) for o in owners]
    assert got[0] is None and got[1] is None and got[2] is not None


def test_owner_of_top_level_graph_is_empty_string():
    """主 agent 在顶层图，ns 只有一段 → owner 为空串。"""
    assert owner_from_config(_cfg("tools:abc")) == ""


@pytest.mark.parametrize("bad", [
    None, {}, "not-a-dict", 123,
    {"configurable": None},
    {"configurable": "x"},
    {"configurable": {}},
    {"configurable": {"checkpoint_ns": None}},
    {"configurable": {"checkpoint_ns": 42}},
    {"configurable": {"checkpoint_ns": ""}},
])
def test_owner_from_config_never_raises(bad):
    """身份识别失败只该退化成共享单链，绝不能打断工具调用。"""
    assert owner_from_config(bad) == ""


def test_reset_clears_every_owner():
    g = RepeatGuard(thresholds=(2,))
    g.check("t", {"q": 1}, "a")
    g.check("t", {"q": 1}, "b")
    g.reset()
    assert g.check("t", {"q": 1}, "a") is None  # 清零后是首次
    assert g.check("t", {"q": 1}, "b") is None


def test_owner_table_does_not_grow_without_bound():
    """异常情况下 owner 键不能无限堆积。"""
    g = RepeatGuard(thresholds=(2,), max_owners=4)
    for i in range(50):
        g.check("t", {"q": 1}, f"owner-{i}")
    assert len(g._chains) <= 4


# ---------- config 注入（Phase 95 的三个静默失效点） ----------

def test_config_is_not_part_of_the_chain_key():
    """config 每次调用都带新 uuid，一旦进链键，守卫会完全失效且不报错。"""
    g = RepeatGuard(thresholds=(2,))

    async def amap_poi(kw: str) -> str:
        """查 POI。"""
        return "ok"

    wrapped = guard_tool(amap_poi, g)
    asyncio.run(wrapped(kw="西湖", config=_cfg("task:abc|tools:step-1")))
    second = asyncio.run(wrapped(kw="西湖", config=_cfg("task:abc|tools:step-2")))
    assert "系统提示" in second  # ns 尾段变了，但 owner 与链键都没变


def test_wrapped_tool_routes_by_injected_config():
    """端到端：包装后的工具靠注入的 config 分链。"""
    g = RepeatGuard(thresholds=(2,))

    async def fetch_url(url: str) -> str:
        """抓取网页。"""
        return "ok"

    wrapped = guard_tool(fetch_url, g)
    a, b = _cfg("task:a|tools:1"), _cfg("task:b|tools:1")
    assert "系统提示" not in asyncio.run(wrapped(url="u", config=a))
    assert "系统提示" not in asyncio.run(wrapped(url="u", config=b))  # 另一个子代理，首次
    assert "系统提示" in asyncio.run(wrapped(url="u", config=a))      # a 的第二次


def test_wrapping_does_not_pollute_original_annotations():
    """functools.wraps 复制的是同一个 __annotations__ dict，改之前必须先拷贝。"""

    async def amap_poi(kw: str) -> str:
        """查 POI。"""
        return "ok"

    before = dict(amap_poi.__annotations__)
    wrapped = guard_tool(amap_poi, RepeatGuard())
    assert "config" in wrapped.__annotations__
    assert amap_poi.__annotations__ == before  # 原函数没被污染


def test_config_is_hidden_from_the_model_visible_schema():
    """config 是给 LangChain 注入用的，绝不能出现在模型看到的参数里。"""
    from langchain_core.tools import StructuredTool

    async def amap_poi(keyword: str, city: str = "") -> str:
        """查 POI。"""
        return "ok"

    wrapped = guard_tool(amap_poi, RepeatGuard())
    tool = StructuredTool.from_function(coroutine=wrapped, name="amap_poi",
                                        description="查 POI")
    assert set(tool.args) == {"keyword", "city"}


def test_tool_declaring_config_itself_gets_it_passed_through():
    """原函数自己声明了 config 就透传，不能被 wrapper 吞掉。"""
    seen = {}

    async def needs_config(q: str, config=None) -> str:
        """自己要 config 的工具。"""
        seen["config"] = config
        return "ok"

    wrapped = guard_tool(needs_config, RepeatGuard(thresholds=(2,)))
    cfg = _cfg("task:abc|tools:1")
    asyncio.run(wrapped(q="x", config=cfg))
    assert seen["config"] is cfg
    # 且 config 仍不进链键
    assert "系统提示" in asyncio.run(wrapped(q="x", config=_cfg("task:abc|tools:2")))


def test_guard_tool_still_works_without_any_config():
    """没有 config 的直接调用（本地单测、非 LangChain 路径）退化成共享单链，不报错。"""
    g = RepeatGuard(thresholds=(2,))

    async def web_search(q: str) -> str:
        """搜。"""
        return "ok"

    wrapped = guard_tool(web_search, g)
    asyncio.run(wrapped(q="亚庇"))
    assert "系统提示" in asyncio.run(wrapped(q="亚庇"))


def test_toolnode_really_injects_distinct_owners_for_concurrent_subagents():
    """集成：真实执行路径（langgraph ToolNode，deepagents 子代理内部走的就是它）
    确实注入 config，且并发两个子图拿到不同 owner。

    这条是整个方案的地基——若哪天 LangGraph 不再注入 config，守卫会**静默**退回
    共享单链（不报错、只是变回老行为），必须有测试钉住。无 LLM。
    """
    from typing import Annotated, TypedDict

    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages
    from langgraph.prebuilt import ToolNode

    owners: list[str] = []

    async def amap_city_brief(city: str) -> str:
        """查城市概况。"""
        return f"{city} 晴"

    g = RepeatGuard(thresholds=(2,))
    wrapped = guard_tool(amap_city_brief, g)

    original_check = g.check

    def spy(tool_name, kwargs, owner=""):
        owners.append(owner)
        return original_check(tool_name, kwargs, owner)

    g.check = spy  # type: ignore[method-assign]

    class S(TypedDict):
        messages: Annotated[list, add_messages]

    sub = StateGraph(S)
    sub.add_node("tools", ToolNode([wrapped]))
    sub.add_edge(START, "tools")
    sub.add_edge("tools", END)
    subgraph = sub.compile()

    def call(city: str) -> AIMessage:
        return AIMessage(content="", tool_calls=[
            {"name": "amap_city_brief", "args": {"city": city}, "id": f"c-{city}"}])

    async def dispatch(state: S, config):
        await asyncio.gather(
            subgraph.ainvoke({"messages": [call("杭州")]}, config=config),
            subgraph.ainvoke({"messages": [call("杭州")]}, config=config),
        )
        return {"messages": []}

    root = StateGraph(S)
    root.add_node("task", dispatch)
    root.add_edge(START, "task")
    root.add_edge("task", END)
    asyncio.run(root.compile().ainvoke({"messages": []}))

    assert len(owners) == 2
    assert all(o for o in owners), f"config 没被注入，owner 全空：{owners}"
    assert owners[0] != owners[1], f"并发子代理拿到了同一个 owner：{owners}"


def test_every_real_research_tool_survives_wrapping():
    """对**真实**的 build_tools 产物逐个校验，新增工具时不会漏掉。

    三条同时成立才算对：能被 LangChain 转成工具（deepagents 内部就这么做）、
    签名里有 config（否则不会注入）、模型可见 schema 里没有 config（否则模型会去填它）。
    `BrowserSession.__init__` 是惰性的（worker task 首次 call 才起），构造它不碰浏览器。
    """
    import inspect

    from langchain_core.tools import tool as to_tool

    from app.agent.research_tools import BrowserSession, build_tools

    session = BrowserSession("cid-test", "user-test")
    main_tools, sub_tools = build_tools("cid-test", "user-test", session, [])
    assert main_tools and sub_tools

    for fn in main_tools + sub_tools:
        built = to_tool(fn)
        sig = list(inspect.signature(fn).parameters)
        assert "config" in sig, f"{built.name} 签名缺 config → LangChain 不会注入"
        assert "config" not in built.args, f"{built.name} 把 config 泄漏进了模型 schema"
        # 原有参数一个不少、顺序不变（config 只能追加在最后）
        assert sig[:-1] == [p for p in sig if p != "config"]


# ==================== 2. 上下文清单 ====================

def test_manifest_records_verbatim_mode():
    m = build_manifest(history=[{"role": "user", "content": "你好"}], summary="")
    assert m["history_mode"] == "verbatim"
    assert m["history_count"] == 1 and m["history_chars"] == 2


def test_manifest_records_compacted_mode():
    """有摘要 = 当时超了全文上限走了压缩装配。这正是事后要回溯的那个事实。"""
    m = build_manifest(history=[{"role": "user", "content": "x"}], summary="早期对话摘要")
    assert m["history_mode"] == "summary+recent"
    assert m["summary_chars"] == 6


def test_manifest_totals_cover_every_part():
    m = build_manifest(
        history=[{"role": "user", "content": "1234"}],
        summary="12",
        sources=[{"summary": "123"}, {"summary": "45"}],
    )
    assert m["source_count"] == 2 and m["source_chars"] == 5
    assert m["total_chars"] == 4 + 2 + 5  # 排查「这轮为什么慢/贵」的第一个数


def test_manifest_caps_memory_ids():
    m = build_manifest(memory_ids=[str(i) for i in range(100)])
    assert m["memory_count"] == 100        # 计数是真实的
    assert len(m["memory_ids"]) == 40      # 但清单只留线索，不是副本


def test_attach_is_a_noop_without_manifest():
    meta = {"sources": []}
    assert attach(meta, None) == {"sources": []}


def test_attach_puts_manifest_under_a_stable_key():
    meta = attach({"sources": []}, build_manifest(history=[]))
    assert "context_manifest" in meta and meta["context_manifest"]["history_count"] == 0


# ==================== 3. 幂等中段截断 ====================

def test_short_text_is_returned_untouched():
    assert TOOL_RESULT.apply("短文本") == "短文本"


def test_long_text_keeps_head_marker_tail():
    text = "A" * 20000
    out = TOOL_RESULT.apply(text)
    assert out.startswith("A" * 100)
    assert TOOL_RESULT.marker in out
    assert out.endswith("A" * 100)
    assert len(out) <= TOOL_RESULT.threshold


def test_truncation_is_idempotent():
    """核心不变式：截过一次的东西再截一次必须原样返回。

    不幂等的话，同一段内容在链路里被截多次，最后只剩个头尾拼盘，
    而且连截断痕迹本身都会被截掉，事后无法判断这是原文还是产物。
    """
    text = "B" * 50000
    once = TOOL_RESULT.apply(text)
    assert TOOL_RESULT.apply(once) == once
    assert TOOL_RESULT.apply(TOOL_RESULT.apply(once)) == once


def test_output_is_strictly_smaller_than_an_over_budget_input():
    text = "C" * (TOOL_RESULT.threshold + 1)
    assert len(TOOL_RESULT.apply(text)) < len(text)


def test_budget_rejects_inconsistent_configuration():
    """head + marker + tail > threshold 会导致反复截断，必须在构造期就拒绝。"""
    with pytest.raises(ValueError, match="不自洽"):
        TruncateBudget(threshold=100, head=90, tail=90)


def test_budget_rejects_nonsense_numbers():
    with pytest.raises(ValueError):
        TruncateBudget(threshold=0, head=0, tail=0)
    with pytest.raises(ValueError):
        TruncateBudget(threshold=100, head=-1, tail=0)


def test_tail_zero_budget_keeps_head_only():
    out = BRIEF.apply("D" * 500)
    assert out.startswith("D" * 160) and out.endswith("…")
    assert BRIEF.apply(out) == out  # 同样幂等


def test_was_truncated_distinguishes_original_from_product():
    text = "E" * 50000
    assert not TOOL_RESULT.was_truncated("原文")
    assert TOOL_RESULT.was_truncated(TOOL_RESULT.apply(text))
