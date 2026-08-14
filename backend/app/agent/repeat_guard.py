"""重复工具调用守卫（Phase 89，借鉴 dsh 的 repeat-tool-reminder）

Phase 28 的**硬配额**治的是「总量超标」（搜 ≤3 次、读 ≤10 个），治不了另一半：
同一个查询被反复调用三次，总数没超但时间和上下文都白烧了。而长上下文里 prompt
纪律必然漂移——模型不会因为你写了「别重复」就不重复。

这里补上另一半：**检测连续重复，注入升级式建议**。刻意不阻断——
合法的重复调用（换了参数的翻页、确实需要重查）一次都不该被拦，
决定权留给模型：换思路、补证据、还是收敛出稿。

## 与 dsh 的一处已知差异

dsh 用 `WeakMap<Agent, Chain>` 按**活的 agent 对象**分链，一个 agent 的重复不会
触发另一个的提醒。本项目的工具闭包是**主 agent 与全部 subagent 共享**的
（见 `build_tools` 注释，配额也是这么共享的），拿不到调用方身份，所以并发子代理
调同一个工具同一参数时会误判成重复。

代价可接受：提醒是**建议性**的，误报的成本只是多一句无害的提示；
阈值相应放宽（3/6/10 而非 dsh 的 3/5/8）以降低并发误报。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 连续第几次相同调用触发提醒。第一档是轻提示，之后是点名工具+次数+参数的详细版。
DEFAULT_THRESHOLDS: tuple[int, ...] = (3, 6, 10)

# 提醒里引用参数的长度上限。链的判重永远用**完整**规范串，这个上限只约束提醒文本
# ——否则一个正在打转的长参数调用会把自己原样带进下一次请求，越滚越大。
ARGS_PREVIEW_CHARS = 200


def canonical_key(tool_name: str, kwargs: dict[str, Any]) -> str:
    """(工具名, 规范化参数) 作为链键。

    参数按 key 深度排序后序列化——只有属性顺序不同的两次调用必须判为同一次。
    不可序列化的值退化成 repr，宁可判重保守一点也不要抛异常。
    """
    try:
        args = json.dumps(kwargs, sort_keys=True, ensure_ascii=False, default=repr)
    except Exception:  # noqa: BLE001 — 守卫绝不能因为参数奇怪就打断工具调用
        args = repr(sorted(kwargs.items(), key=lambda kv: kv[0]))
    return f"{tool_name}|{args}"


class RepeatGuard:
    """按轮记账的连续重复检测。`build_tools` 每轮建一个，闭包内共享。"""

    def __init__(
        self,
        thresholds: tuple[int, ...] = DEFAULT_THRESHOLDS,
        exclude: tuple[str, ...] = (),
    ) -> None:
        cleaned = sorted({int(t) for t in thresholds})
        if not cleaned or cleaned[0] < 2:
            # 失败要响：静默回落默认值会让配置错误一直藏着（dsh 的 fail-loud 原则）
            raise ValueError(f"repeat guard thresholds 非法：{thresholds}")
        self.thresholds = tuple(cleaned)
        self.exclude = set(exclude)
        self._key: str | None = None
        self._count = 0
        self._fired: set[int] = set()

    def check(self, tool_name: str, kwargs: dict[str, Any]) -> str | None:
        """记一次调用，需要提醒时返回提醒文本。

        **未跟踪的工具对链是透明的**——既不累加也不重置。否则一个记账类工具插进来
        就能把循环「洗白」：`search X → read_source → search X` 仍应算连续两次 search X。
        """
        if tool_name in self.exclude:
            return None
        key = canonical_key(tool_name, kwargs)
        if key == self._key:
            self._count += 1
        else:
            self._key, self._count, self._fired = key, 1, set()
        if self._count not in self.thresholds or self._count in self._fired:
            return None
        self._fired.add(self._count)
        return self._reminder(tool_name, kwargs, self._count)

    def _reminder(self, tool_name: str, kwargs: dict[str, Any], run: int) -> str:
        if run == self.thresholds[0]:
            return (
                f"\n\n[系统提示] 你已经连续 {run} 次用完全相同的参数调用 `{tool_name}`，"
                "结果不会变。请重读上一次的返回内容，然后换个思路或直接开始产出。"
            )
        try:
            args = json.dumps(kwargs, ensure_ascii=False, sort_keys=True, default=repr)
        except Exception:  # noqa: BLE001
            args = repr(kwargs)
        if len(args) > ARGS_PREVIEW_CHARS:
            args = args[:ARGS_PREVIEW_CHARS] + f"…（省略 {len(args) - ARGS_PREVIEW_CHARS} 字）"
        return (
            f"\n\n[系统提示] 你已经连续 {run} 次用同样的参数调用 `{tool_name}`：{args}\n"
            "重复调用不会带来新信息。现在必须二选一：**换完全不同的查询/工具**，"
            "或者**基于已有资料开始写结论**。不要再发起同样的调用。"
        )

    def reset(self) -> None:
        """新一轮用户输入：链清零（上一轮的重复不该影响这一轮）。"""
        self._key, self._count, self._fired = None, 0, set()


def guard_tool(fn, guard: RepeatGuard):
    """包一层重复检测；提醒**追加**在工具原始返回之后，不替换内容。

    不替换是有意的：工具结果要保持原样可审计（dsh 把提醒放在 additionalContexts 里，
    我们没有那条独立通道，追加是等价做法）。
    """
    import functools
    import inspect

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        result = await fn(*args, **kwargs)
        try:
            # **调用失败/被拒也计数**：模型反复砸一个失败的调用，正是最该打断的循环
            note = guard.check(getattr(fn, "__name__", "tool"), _named_args(fn, args, kwargs))
        except Exception:  # noqa: BLE001 — 守卫出问题绝不能影响工具本身
            logger.warning("repeat guard check failed", exc_info=True)
            return result
        # 只在字符串返回上追加；非字符串返回（结构化结果）原样放行，不硬塞提示进去
        return result + note if (note and isinstance(result, str)) else result

    if not inspect.iscoroutinefunction(fn):
        raise TypeError(f"repeat guard 只包装异步工具，收到 {fn!r}")
    return wrapper


def _named_args(fn, args: tuple, kwargs: dict) -> dict[str, Any]:
    """把位置参数并进关键字参数，保证同一次调用无论怎么传都得到同一个链键。"""
    import inspect

    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except Exception:  # noqa: BLE001
        return {"_args": list(args), **kwargs}


def guard_tools(tools: list, guard: RepeatGuard) -> list:
    """批量包装。异常一律原样返回该工具——守卫是增强，不能让工具集构建失败。"""
    out = []
    for fn in tools:
        try:
            out.append(guard_tool(fn, guard))
        except Exception:  # noqa: BLE001
            logger.warning("repeat guard wrap failed for %r", fn, exc_info=True)
            out.append(fn)
    return out
