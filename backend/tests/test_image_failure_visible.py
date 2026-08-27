"""Phase 111：图读不出来时，必须让用户看见。

线上真实反馈的形状：前面刚播「正在看你发的 1 张图…」，视觉端 400 被 `logger.warning`
吞掉，接着助手反问「目的地是哪里？」。用户的结论是「这个智能体太死板」——
**其实是一次静默的硬失败**。进度说读了、实际没读，是最容易被误读成「它很蠢」的一种失败。
"""

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "app/agent/orchestrator.py"


def _turn_fn() -> ast.FunctionDef:
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_conversation_turn":
            return node
    raise AssertionError("run_conversation_turn 不见了")


def _calls(node) -> set[str]:
    """节点子树里被**调用**的名字。

    只数调用表达式，不做文本匹配——本仓库反复踩过「断言匹配到了注释/字符串」
    （见 CLAUDE.md 里那几次）。
    """
    out = set()
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        if isinstance(n.func, ast.Name):
            out.add(n.func.id)
        elif isinstance(n.func, ast.Attribute):   # vision.describe_user_images(...)
            out.add(n.func.attr)
    return out


def test_empty_description_tells_the_user():
    """`desc` 为空 = 图一个字没读出来，必须走可见提示。"""
    fn = _turn_fn()
    for node in ast.walk(fn):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                and node.test.id == "desc"):
            assert node.orelse, "desc 为空时什么都不做——失败对用户完全隐形"
            assert "_image_unreadable" in _calls(ast.Module(body=node.orelse, type_ignores=[]))
            return
    raise AssertionError("没找到 `if desc:` 分支")


def test_vision_exception_also_tells_the_user():
    """400 / 超时 / 模型下线走的是 except，那条路同样不能静默。"""
    fn = _turn_fn()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try):
            continue
        # 只认**那一个** try：body 里真的调了视觉，别撞上同函数里别的 try
        if "describe_user_images" not in _calls(ast.Module(body=node.body, type_ignores=[])):
            continue
        assert node.handlers, "视觉调用没有 except，一个 400 会炸掉整轮"
        for handler in node.handlers:
            calls = _calls(ast.Module(body=handler.body, type_ignores=[]))
            assert "_image_unreadable" in calls, "视觉失败的 except 分支没有通知用户"
        return
    raise AssertionError("没找到包住视觉调用的 try")


def test_notice_carries_meta_so_it_survives_cleanup():
    """`clear_plain_progress` 终稿后会删掉**无 meta** 的 progress。

    没有 meta 的话这条提示会在攻略出来的瞬间消失，用户永远看不到——
    而它恰恰是要解释「为什么我没用你的图」。
    """
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_image_unreadable":
            for call in ast.walk(node):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                        and call.func.id == "_progress"):
                    assert any(kw.arg == "meta" for kw in call.keywords), \
                        "提示没带 meta，会被 clear_plain_progress 清掉"
                    return
            raise AssertionError("_image_unreadable 没有发 progress")
    raise AssertionError("_image_unreadable 不存在")
