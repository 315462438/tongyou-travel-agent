"""协议层思考控制（Phase 108）单测。全离线：不发网络请求、不调 LLM。

背景：DeepSeek 思考模式对结构化抽取过度推理，我们撞过四次（Phase 11 ITINERARY /
101 quick_take / 102 五处抽取 / 105 视觉），前四次分别靠 prompt 纪律和借
`response_format` 刹车——都是间接手段。`reasoning_effort` 是对症的协议字段。

映射抄自上游 deepseek-harness `llm-deepseek/src/serialize.ts::resolveThinking`。
"""

import pytest
from pydantic import BaseModel

from app.config import settings
from app.llm.client import LLMClient, _thinking_kwargs


class _Tiny(BaseModel):
    ok: bool


# --------------------------------------------------------------------------- 档位映射

def test_none_sends_nothing():
    """回退路径：配成 none 必须等于「这个功能不存在」，请求体不多一个字段。"""
    for v in (None, "none", ""):
        assert _thinking_kwargs(v) == {}


def test_off_is_not_a_wire_effort():
    """最容易写错的一格：`off` 是 thinking=disabled，**不是** reasoning_effort="off"。"""
    kw = _thinking_kwargs("off")
    assert kw == {"extra_body": {"thinking": {"type": "disabled"}}}
    assert "reasoning_effort" not in kw


@pytest.mark.parametrize("effort", ["low", "high", "max"])
def test_wire_efforts_pair_enabled_with_effort(effort):
    """low/high/max 必须同时带 thinking=enabled——只发 effort 不发 thinking 是半个请求。"""
    kw = _thinking_kwargs(effort)
    assert kw["reasoning_effort"] == effort
    assert kw["extra_body"] == {"thinking": {"type": "enabled"}}


def test_unknown_effort_degrades_to_nothing():
    """配置写错时宁可退回旧行为，也不能让整条链路 400。"""
    assert _thinking_kwargs("bogus") == {}
    assert _thinking_kwargs("OFF") == {}  # 大小写敏感，不做模糊匹配


def test_thinking_goes_through_extra_body_not_as_kwarg():
    """`thinking` 不是 openai SDK 的已知参数，直接当 kwarg 传会 TypeError。

    它必须走 extra_body（SDK 会把 extra_body 的键合并到请求体**顶层**，
    满足协议要求的「顶层字段」——不是嵌套成 {"extra_body": {...}} 发出去）。
    """
    from openai.resources.chat.completions import Completions
    import inspect

    params = inspect.signature(Completions.create).parameters
    assert "thinking" not in params, "SDK 已原生支持 thinking，可以不再走 extra_body"
    assert "reasoning_effort" in params, "reasoning_effort 应能直接当 kwarg 传"
    for effort in ("off", "low", "high", "max"):
        assert "thinking" not in _thinking_kwargs(effort)


# --------------------------------------------------------------------------- 透传到请求

class _FakeCompletions:
    def __init__(self, sink):
        self._sink = sink

    def create(self, **kwargs):
        self._sink.append(kwargs)

        class _Msg:
            content = '{"ok": true}'

        class _Choice:
            message = _Msg()
            finish_reason = "stop"

        class _Resp:
            choices = [_Choice()]

        return _Resp()


class _FakeClient:
    def __init__(self, sink):
        self.chat = type("chat", (), {"completions": _FakeCompletions(sink)})()


def _client_with_sink():
    sink: list[dict] = []
    c = LLMClient.__new__(LLMClient)  # 绕开 __init__ 的真实 OpenAI 构造
    c._client = _FakeClient(sink)
    return c, sink


def test_parse_sends_nothing_unless_asked(monkeypatch):
    """parse() **刻意不读全局配置**：结构化 ≠ 机械。

    需求解析、自检 critique、记忆增删同样走 parse()，它们的质量依赖推理。全局默认会让
    将来任何新增的 parse() 调用静默继承一个它未必该有的档位。
    """
    monkeypatch.setattr(settings, "extract_reasoning_effort", "off")
    c, sink = _client_with_sink()
    c.parse("x", _Tiny)
    assert "reasoning_effort" not in sink[0]
    assert "extra_body" not in sink[0]


def test_explicit_effort_is_the_only_way_in():
    c, sink = _client_with_sink()
    c.parse("x", _Tiny, effort="off")
    assert "reasoning_effort" not in sink[0]
    assert sink[0]["extra_body"] == {"thinking": {"type": "disabled"}}

    c, sink = _client_with_sink()
    c.parse("x", _Tiny, effort="low")
    assert sink[0]["reasoning_effort"] == "low"


def test_effort_none_keeps_the_request_byte_identical():
    """回退开关的意义就在这条：设成 none，请求体与改造前一模一样。"""
    c, sink = _client_with_sink()
    c.parse("x", _Tiny, effort="none")
    assert "reasoning_effort" not in sink[0]
    assert "extra_body" not in sink[0]
    # 原有字段一个不少
    assert sink[0]["response_format"] == {"type": "json_object"}
    assert sink[0]["max_tokens"] == 8000


def test_response_format_is_never_dropped():
    """Phase 105 实测 json_object 本身就是性能开关，思考档位是**叠加**不是替代。"""
    for effort in ("none", "off", "low", "high"):
        c, sink = _client_with_sink()
        c.parse("x", _Tiny, effort=effort)
        assert sink[0]["response_format"] == {"type": "json_object"}


def test_classify_passes_effort_through():
    c, sink = _client_with_sink()
    c.classify("x", _Tiny, effort="off")
    assert sink[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert sink[0]["model"] == settings.model_classifier


def test_vision_has_its_own_knob(monkeypatch):
    """exp 模型的字段支持与文本模型未必一致，且它已有一条实测验证过的刹车。"""
    monkeypatch.setattr(settings, "vision_reasoning_effort", "none")
    c, sink = _client_with_sink()
    c.parse_image("x", _Tiny, images=["https://example.com/a.jpg"])
    assert "extra_body" not in sink[0]
    assert "reasoning_effort" not in sink[0]


def test_generation_is_untouched():
    """自由文本生成的思考链是产品的一部分（前端「已深度思考」折叠面板），不受这个旋钮影响。"""
    c, sink = _client_with_sink()

    class _Msg:
        content = "hi"
        reasoning_content = "think"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    c._client.chat.completions.create = lambda **kw: (sink.append(kw), _Resp())[1]
    c.generate_with_reasoning("x")
    assert "reasoning_effort" not in sink[0]
    assert "extra_body" not in sink[0]


def test_retry_keeps_the_thinking_fields():
    """校验失败重试一次时档位不能丢——否则第二次请求又变回长思考，白省。"""
    sink: list[dict] = []

    class _BadThenGood:
        def __init__(self):
            self.n = 0

        def create(self, **kwargs):
            sink.append(kwargs)
            self.n += 1
            body = '{"nope": 1}' if self.n == 1 else '{"ok": true}'

            class _Msg:
                content = body

            class _Choice:
                message = _Msg()
                finish_reason = "stop"

            class _Resp:
                choices = [_Choice()]

            return _Resp()

    c = LLMClient.__new__(LLMClient)
    c._client = type("C", (), {"chat": type("ch", (), {"completions": _BadThenGood()})()})()
    c.parse("x", _Tiny, effort="low")
    assert len(sink) == 2
    for call in sink:
        assert call["reasoning_effort"] == "low"


# --------------------------------------------------------------------------- 配置面

def test_default_setting_is_explicit_and_supported():
    """默认值必须是映射表认得的档位，否则每次调用都记一条 warning 还静默降级。"""
    for name in ("extract_reasoning_effort", "vision_reasoning_effort"):
        v = getattr(settings, name)
        assert v in ("none", "off", "low", "high", "max"), f"{name}={v!r} 不是合法档位"


# --------------------------------------------------------------------------- 调用点护栏

def test_extraction_sites_are_tiered_by_derived_numbers():
    """分档判据：**输出里有没有模型要「推导」出来的数字**，不是「抽取 vs 生成」。

    第一版按「抽取就关思考」一刀切，被评估当场抓到：马来西亚样本的 headcount 三轮里错
    一轮（认成 1 人，正文是 2 人），而人数错会让整个预算面板的人均口径翻倍
    （Phase 67 不变式）。「两大一小=3」「2人合计→人均」「区间价取中间值」都是推导。

    机械档 = 输出只有照抄的名字/天号；判断档 = 输出含推导出来的数字。
    ⚠️ 判断档默认 `none`（不动），因为**写错方向的代价不对称**：机械路径误判成判断只是
    慢一点，判断路径误判成机械会给出错误金额。

    ⚠️ poster 的 critique 与本表无关——那是自检，两个旋钮都不吃。
    """
    import ast
    from pathlib import Path

    # 文件 → {机械档处数, 判断档处数}
    # 文件 → (机械, 判断, 人数兜底)
    expected = {
        "app/ontology/extract.py": (1, 1, 1),  # 逐日分块 / _parse 默认 / _headcount
        "app/agent/budget.py": (0, 1, 0),      # BudgetData 全是钱
        "app/agent/poster.py": (2, 0, 0),      # PosterData 没有任何数字
        "app/api/trip_api.py": (1, 1, 0),      # IMPORT_DAYS 机械 / IMPORT_SUMMARY 带 budget_items
    }
    root = Path(__file__).resolve().parent.parent
    for rel, (want_mech, want_judge, want_hc) in expected.items():
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        mech = judge = hc = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "effort":
                    continue
                # 表达式里找配置项名。不要求是裸 Attribute——ontology 的 `_parse` 写的是
                # `effort or settings.…`（形参兜底），那同样是合法的传法。
                names = {n.attr for n in ast.walk(kw.value) if isinstance(n, ast.Attribute)}
                # 但必须来自配置项，不能就地写死档位字符串——写死了没法一键回退
                known = {
                    "extract_reasoning_effort",
                    "extract_judgment_reasoning_effort",
                    "headcount_reasoning_effort",
                }
                assert names & known, f"{rel}: effort 应引用 settings.<配置项>，实际表达式里没有"
                assert not any(
                    isinstance(n, ast.Constant) and n.value in ("off", "low", "high", "max")
                    for n in ast.walk(kw.value)
                ), f"{rel}: effort 里出现写死的档位字面量"
                if "extract_reasoning_effort" in names:
                    mech += 1
                if "extract_judgment_reasoning_effort" in names:
                    judge += 1
                if "headcount_reasoning_effort" in names:
                    hc += 1
        assert (mech, judge, hc) == (want_mech, want_judge, want_hc), (
            f"{rel}: 期望 机械{want_mech}/判断{want_judge}/人数{want_hc}，"
            f"实际 机械{mech}/判断{judge}/人数{hc}"
        )


def test_days_chunk_schema_carries_no_derived_number():
    """机械档的正当性来自 schema 本身：TripDaysExtraction 里不能有 headcount 或金额。

    哪天有人往它加一个 `budget` 字段，这条会红——那时该做的是把它挪到判断档，
    而不是接受一个用 off 抽出来的金额。
    """
    from app.agent.trip_planner import TripImportDays
    from app.schemas.ontology_schema import TripDaysExtraction
    from app.schemas.poster_schema import PosterData

    for model in (TripDaysExtraction, TripImportDays, PosterData):
        fields = set(model.model_fields)
        assert "headcount" not in fields, f"{model.__name__} 有了 headcount，应改走判断档"
        text = str(model.model_json_schema())
        assert "amount" not in text, f"{model.__name__} 出现金额字段，应改走判断档"


def test_judgment_schemas_do_carry_derived_numbers():
    """反向钉住：判断档那几个 schema 确实带推导数字，否则这套分档就是空的。"""
    from app.agent.trip_planner import TripImportSummary
    from app.schemas.budget_schema import BudgetData
    from app.schemas.ontology_schema import TripCostExtraction, TripProfileExtraction

    assert "headcount" in TripProfileExtraction.model_fields
    assert "headcount" in TripCostExtraction.model_fields
    assert "headcount" in BudgetData.model_fields
    assert "budget_items" in TripImportSummary.model_fields


# --------------------------------------------------------------------------- 人数兜底路

def test_judgment_tier_is_never_off():
    """判断档降到 off 会整块丢内容——这条是数据打出来的护栏，不是保守起见。

    `evals/extract_eval` 5 篇固定攻略，全 off 跑了 10 轮出 5 次失败，且可复现：
    马来西亚 Day 6（正文里有「路线A/路线B」分支那天）整天丢失 2/4 轮；
    武汉一轮 Day 2/3 无停留点且**黄鹤楼**完全没抽到。分档配置 3 轮 0 失败。

    机械档可以是 off（那些 schema 里只有照抄的名字），判断档不行。
    """
    assert settings.extract_judgment_reasoning_effort in ("none", "low", "high", "max"), (
        "判断档不许是 off：实测会整天/整个主地标地丢内容"
    )


def test_headcount_lane_never_rides_the_fast_knob():
    """人数是唯一实测会被 off 弄错的字段，它必须有自己的保守旋钮。

    代价不对称：人数错会顺着「金额一律人均口径」（Phase 67）把整个预算面板一起弄错，
    而且不报错。多一次 200 token 的小调用换掉这个风险是划算的。
    """
    assert settings.headcount_reasoning_effort == "none", "人数兜底路不该跟着提速旋钮走"
    assert settings.headcount_lane_enabled is True


def test_headcount_lane_uses_its_own_effort_not_the_shared_one():
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "app/ontology/extract.py").read_text("utf-8")
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_headcount"
    )
    efforts = {
        kw.value.attr
        for call in ast.walk(fn) if isinstance(call, ast.Call)
        for kw in call.keywords
        if kw.arg == "effort" and isinstance(kw.value, ast.Attribute)
    }
    assert efforts == {"headcount_reasoning_effort"}, (
        f"_headcount 应只用 settings.headcount_reasoning_effort，实际 {efforts}"
    )


def test_headcount_merge_guards_the_low_direction():
    """合并用 max()：实测的失手方向是**偏小**（该 2 认成 1），max 天然防小。

    这条钉住方向——改成 min 或直接覆盖都会让兜底失去意义。
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "app/ontology/extract.py").read_text("utf-8")
    seg = src[src.index("hc_extra and not isinstance"):]
    seg = seg[: seg.index("\n\n")] if "\n\n" in seg else seg
    assert "max(trip.headcount" in seg, "人数合并必须用 max（失手方向是偏小）"


def test_headcount_lane_only_runs_with_the_cost_lane():
    """不点预算面板就没有金额要配人数，那次调用是纯浪费。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "app/ontology/extract.py").read_text("utf-8")
    assert "need_hc = LANE_COST in want and settings.headcount_lane_enabled" in src
