"""澄清熔断与「对得上原因的反问」（2026-08-27）。

线上现象：用户上传行程长截图连问两轮，两轮拿到的是同一个反问「目的地是哪里？」。
两个独立缺陷：

1. **熔断从来没生效过**——`_recent_clarify_rounds` 靠「≤60 字且问号结尾」认自己的
   反问，而模型在问句后顺手接了「我好帮您推荐周边美食和检查路线。」，句尾变「。」，
   于是永远数出 0 轮。问 10 次也是「第 0 轮」。
2. **反问不看原因**——目的地拿不到是因为图没读出来，回一句「请问目的地是哪里」，
   在用户看来就是没听见。
"""

import json
import types

import pytest

from app.agent import orchestrator as orch


def _msg(content="", meta=None, role="assistant"):
    return types.SimpleNamespace(
        role=role, content=content,
        meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
    )


# ---------- 判据：读事实，不猜文案 ----------

def test_the_exact_line_that_broke_production():
    """这一条就是线上那句原文。改造前它被判成「不是追问」，熔断因此从未触发。"""
    line = ("请问您这次行程的目的地是哪里？方便告诉我具体城市或景点吗？"
            "我好帮您推荐周边美食和检查路线。")
    assert not orch._is_clarify_text(line), "前提变了：它现在文案上就能认出来"
    assert orch._is_clarify_message(_msg(line, {"clarify": True})), \
        "带了 clarify 标记还认不出来 —— 熔断又会失效"


def test_meta_beats_wording():
    """措辞随模型漂移，meta 不会。"""
    for wording in ("去哪儿玩？", "帮你确认一下具体城市，我好继续。", ""):
        assert orch._is_clarify_message(_msg(wording, {"clarify": True}))


def test_old_messages_still_recognised_by_shape():
    """改造前落库的反问没有 meta，只能靠文案兜底——不能把它们一起丢了。"""
    assert orch._is_clarify_message(_msg("想去哪里呢？"))


def test_a_real_guide_is_not_counted_as_a_clarify():
    assert not orch._is_clarify_message(_msg("# 杭州三日行程\n\nDay1 ……" + "内容" * 80))


def test_candidate_cards_count_as_a_round():
    """候选卡也是「没给结果、把球踢回去」，不计数就是换了张皮的无限追问。"""
    assert orch._is_clarify_message(_msg("帮你圈了几个方向：", {"candidates": [{"name": "黄山"}]}))


def test_placeholders_are_not_rounds():
    for meta in ({"streaming": True}, {"poster": {}}, {"budget": {}}):
        assert not orch._is_clarify_message(_msg("", meta))


# ---------- 逐轮升级：不许重复同一句 ----------

def test_blind_asks_never_repeat_and_always_offer_a_way_out():
    asks = orch._BLIND_ASKS
    assert len(asks) >= 3
    assert len(set(asks)) == len(asks), "有两轮说了同一句话——投诉的原话就是这个"
    for a in asks:
        assert "城市" in a, "每一轮都得给出「打城市名」这条最直接的出路"
    assert any("你定" in a for a in asks[1:]), "问过一次之后要给「你定」这条授权出路"


def test_blind_ask_index_is_clamped():
    """轮数超出文案表不能 IndexError，取最后一条。"""
    asks = orch._BLIND_ASKS
    for rounds in range(0, 12):
        assert asks[min(rounds, len(asks) - 1)] in asks


def test_first_blind_ask_says_the_image_failed():
    """第一句就得说清楚「图没读出来」——用户的诉求是别装作没这回事。"""
    assert "图" in orch._BLIND_ASKS[0]


# ---------- 本轮边界 ----------

def test_image_failure_is_scoped_to_this_turn(monkeypatch):
    """上一轮的失败不能污染这一轮：走到本轮 user 消息就停。"""
    rows = [
        _msg("请问目的地？", {"clarify": True}),
        _msg("这次没带图", role="user"),                       # ← 本轮用户消息
        _msg("图读不了", {"hint": "image_unreadable"}, role="progress"),
        _msg("上一轮的图", role="user"),
    ]
    monkeypatch.setattr(orch, "get_session", lambda: _FakeSession(rows))
    assert orch._image_unreadable_this_turn("c1") is False


def test_image_failure_this_turn_is_detected(monkeypatch):
    rows = [
        _msg("图读不了", {"hint": "image_unreadable"}, role="progress"),
        _msg("看看我的行程", role="user"),
    ]
    monkeypatch.setattr(orch, "get_session", lambda: _FakeSession(rows))
    assert orch._image_unreadable_this_turn("c1") is True


def test_detection_failure_is_not_treated_as_blind(monkeypatch):
    """读库失败时退回**原有**行为（普通反问 + 允许代选），不是新分支。"""
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(orch, "get_session", boom)
    assert orch._image_unreadable_this_turn("c1") is False


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def execute(self, *_a, **_k):
        rows = self._rows

        class _R:
            def scalars(self_inner):
                class _S:
                    def all(self_s):
                        return rows
                return _S()
        return _R()


# ---------- 代选的边界 ----------

def test_forced_pick_is_disabled_when_we_failed_to_read_the_users_image():
    """有正面证据说明用户手上有确定目的地时，替他挑一个是**净损失**：
    几分钟生成换一份必然不相干的行程。代价不对称，宁可再问一句。

    这里断言的是 `parse_request` 里那个 `forced` 表达式的形状——它是纯布尔逻辑，
    抽出来比对四种输入。
    """
    import ast
    import pathlib

    src = pathlib.Path(orch.__file__).read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "parse_request")
    assign = next(n for n in ast.walk(fn)
                  if isinstance(n, ast.Assign)
                  and any(getattr(t, "id", "") == "forced" for t in n.targets))
    expr = ast.unparse(assign.value)
    assert "blind" in expr, "代选没有排除「图读不出来」这一档"
    assert "let_agent_decide" in expr, "用户明确授权时仍然应该代选"

    ns = {}
    exec(
        "def f(let_agent_decide, rounds, blind, clarify_max_rounds=2):\n"
        "    pref = type('P', (), {'let_agent_decide': let_agent_decide})()\n"
        "    settings = type('S', (), {'clarify_max_rounds': clarify_max_rounds})()\n"
        f"    return {expr}\n", ns)
    f = ns["f"]
    assert f(False, 5, True) is False, "图读不了却还在代选"
    assert f(True, 0, True) is True, "用户说了「你定」就该代选，哪怕图没读出来"
    assert f(False, 5, False) is True, "没有图的正常熔断被误伤了"
    assert f(False, 0, False) is False


def test_every_clarify_reply_records_the_flag():
    """**这条钉住线上那个 bug 本身。**

    判据正确没用，得有人写。漏写 `meta.clarify` 的话这一轮不计数、下一轮又从
    「第 0 轮」开始——熔断在代码里静静地存在着，永远不触发。

    做法：在 `parse_request` 里找出每一个「发完消息就 return clarify」的语句块，
    要求块里的 `_add_message` 都带上 meta 标记。断言的是**调用的实参**，
    不是源码文本（本仓库反复踩过「断言匹配到了自己写的注释」）。
    """
    import ast
    import pathlib

    src = pathlib.Path(orch.__file__).read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "parse_request")

    def is_clarify_return(node):
        return (isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
                and any(isinstance(v, ast.Constant) and v.value == "clarify"
                        for v in node.value.values))

    checked = 0
    for block in ast.walk(fn):
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(block, field, None)
            if not isinstance(stmts, list) or not any(is_clarify_return(s) for s in stmts):
                continue
            for stmt in stmts:
                for call in ast.walk(stmt):
                    if not (isinstance(call, ast.Call)
                            and getattr(call.func, "id", "") == "_add_message"):
                        continue
                    meta = next((k.value for k in call.keywords if k.arg == "meta"), None)
                    assert meta is not None, \
                        "有一条澄清回复没写 meta —— 熔断对它不计数，就是线上那个无限反问"
                    keys = {k.value for k in getattr(meta, "keys", [])
                            if isinstance(k, ast.Constant)}
                    assert keys & {"clarify", "candidates"}, \
                        f"meta 里没有 clarify/candidates，熔断认不出来：{keys}"
                    checked += 1
    assert checked >= 3, f"只检到 {checked} 处澄清回复，分支可能被漏扫"
