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


def test_any_unread_image_tells_the_user():
    """**有图没读出来**就必须走可见提示——不是「一张都没读出来」才提示。

    Phase 112 改的正是这条判据。旧代码写的是 `if desc: ... else: _image_unreadable()`，
    于是传 3 张读出 1 张时 `desc` 非空、走了 if 分支，完全不吭声——而前面刚播过
    「正在看你发的 3 张图…」。判据必须来自**逐图统计**（`any_unread`），
    不能来自「产出文本空不空」这个形状。
    """
    fn = _turn_fn()
    for node in ast.walk(fn):
        if not (isinstance(node, ast.If) and isinstance(node.test, ast.Attribute)):
            continue
        if node.test.attr != "any_unread":
            continue
        assert "_image_unreadable" in _calls(ast.Module(body=node.body, type_ignores=[])), \
            "any_unread 分支没有通知用户"
        return
    raise AssertionError("没找到 `if <reading>.any_unread:` 分支——"
                         "判据又回到了「产出空不空」的形状上")


def test_reading_note_reaches_the_prompt():
    """读图说明必须真的并进 `user_text`，否则它只是个没人读的字段。

    模型不知道自己看的是一张缩糊了的图，就会把缩糊了的价格和日期当成看清楚了的。
    """
    fn = _turn_fn()
    for node in ast.walk(fn):
        if not (isinstance(node, ast.If) and isinstance(node.test, ast.Attribute)):
            continue
        if node.test.attr != "note":
            continue
        targets = [t.id for n in ast.walk(ast.Module(body=node.body, type_ignores=[]))
                   if isinstance(n, ast.Assign)
                   for t in n.targets if isinstance(t, ast.Name)]
        assert "user_text" in targets, "note 分支没有把说明并进 user_text"
        return
    raise AssertionError("没找到 `if <reading>.note:` 分支")


def test_reading_note_stays_outside_wrap_external():
    """说明是**我们自己的话**，不能包进 `wrap_external`。

    包进去审计时就分不清哪句是模型「看」出来的、哪句是我们说的
    （同 Phase 31 对来源编号的处理）。
    """
    fn = _turn_fn()
    for node in ast.walk(fn):
        if not (isinstance(node, ast.If) and isinstance(node.test, ast.Attribute)):
            continue
        if node.test.attr != "note":
            continue
        assert "wrap_external" not in _calls(ast.Module(body=node.body, type_ignores=[])), \
            "读图说明被包进了 wrap_external"
        return
    raise AssertionError("没找到 `if <reading>.note:` 分支")


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
