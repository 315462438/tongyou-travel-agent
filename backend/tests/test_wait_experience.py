"""Phase 71：长任务等待体验（快答先行 / 发现式进度）的后端保证。全部离线。

背景：深度研究 4-6 分钟，用户常以为卡死就退出。这里锁住两条关键不变式：
1. 「初步回答」不能被 _is_running 当成终稿——否则前端停止轮询，完整版永远收不到；
2. 进度摘要 _gist 在各种脏输入下都要产出可读短句，不能抛异常拖垮采集。
"""

import json

import pytest

from app.agent.research_tools import _gist
from app.api.chat_api import _is_running


class _M:
    def __init__(self, role, meta=None, created_at=None):
        from datetime import datetime
        self.role = role
        self.meta_json = json.dumps(meta) if meta else None
        self.created_at = created_at or datetime.now()


# ---------- 初步回答不算终稿 ----------

def test_preliminary_answer_keeps_turn_running():
    """有初步回答 + 流式占位 → 仍在运行（完整版还没来）。"""
    msgs = [_M("user"), _M("assistant", {"streaming": True}), _M("assistant", {"preliminary": True})]
    assert _is_running(msgs) is True


def test_preliminary_alone_does_not_finish_turn():
    """即使流式占位缺失（stream 关闭等），初步回答也不得判为完成。"""
    msgs = [_M("user"), _M("assistant", {"preliminary": True})]
    assert _is_running(msgs) is True


def test_real_answer_after_preliminary_finishes_turn():
    """完整版落地（非 preliminary、非 streaming）→ 本轮结束。"""
    msgs = [_M("user"), _M("assistant", {"preliminary": True}), _M("assistant")]
    assert _is_running(msgs) is False


def test_plain_answer_still_finishes_turn():
    """不涉及初步回答的普通轮次行为不变。"""
    assert _is_running([_M("user"), _M("assistant")]) is False


def test_streaming_still_means_running():
    assert _is_running([_M("user"), _M("assistant", {"streaming": True})]) is True


# ---------- 进度摘要 ----------

@pytest.mark.parametrize("raw,expect", [
    ("", "（没读到正文）"),
    ("    \n\t ", "（没读到正文）"),
    (None, "（没读到正文）"),
])
def test_gist_handles_empty(raw, expect):
    assert _gist(raw) == expect


def test_gist_strips_a11y_noise():
    out = _gist('uid=3_2 link "首页" 成都三日游攻略，第一天去宽窄巷子。')
    assert "uid=" not in out and "link" not in out
    assert out.startswith("成都")


def test_gist_prefers_a_complete_sentence():
    out = _gist("这家火锅店真的绝了！排队要两小时，建议提前取号避开高峰期哦")
    assert out.endswith("！") or out.endswith("…") or len(out) <= 42


def test_gist_truncates_long_text():
    out = _gist("A" * 500)
    assert len(out) <= 45 and out.endswith("…")


def test_gist_collapses_whitespace():
    assert "\n" not in _gist("第一行\n\n第二行   第三行")
