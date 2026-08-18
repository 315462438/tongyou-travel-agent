"""重复工具调用守卫（Phase 89，借鉴 dsh 的 repeat-tool-reminder）

Phase 28 的**硬配额**治的是「总量超标」（搜 ≤3 次、读 ≤10 个），治不了另一半：
同一个查询被反复调用三次，总数没超但时间和上下文都白烧了。而长上下文里 prompt
纪律必然漂移——模型不会因为你写了「别重复」就不重复。

这里补上另一半：**检测连续重复，注入升级式建议**。刻意不阻断——
合法的重复调用（换了参数的翻页、确实需要重查）一次都不该被拦，
决定权留给模型：换思路、补证据、还是收敛出稿。

## 按调用方分链（Phase 95）

工具闭包是**主 agent 与全部 subagent 共享**的（见 `build_tools` 注释，配额也是这么
共享的），最初拿不到调用方身份，所以并发子代理调同一个工具同一参数时会互相累加，
被误判成重复。当时的判断是「误报只是多一句无害提示」，后来复核认为偏乐观：误报注入的
是一句**事实错误**的系统提示（「你已经连续 3 次调用 X」，而它其实是第一次调），
模型无从核对真伪，只能采信，可能因此放弃一次合法的首次查询。

现在按**调用方**分链。身份取自 LangChain 注入的 `config` 里的 `checkpoint_ns`
父链前缀（见 `owner_from_config`）——实测它在同一子代理跨 superstep 时稳定、
并发子代理之间互不相同，而 `parent_run_id` 每个 superstep 都变，不能直接当键。

**不用 dsh 的 `WeakMap`**：它需要弱引用是因为那张链表长生命周期、靠 agent 对象被 GC
自动清理；我们的 guard 由 `build_tools` 每轮新建、轮末整体丢弃，普通 dict 就够。

分链落地后，放宽阈值的理由（并发误报）已消失，阈值改回 dsh 的 3/5/8。
残留风险：若某条路径没传 config，owner 一律为空串 → 退化成共享单链。
`tests/test_dsh_ports.py` 有 ToolNode 集成测试钉住「真实路径确实注入 config」。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

try:  # langchain 是既有依赖；退化分支只为让守卫在最小环境里仍可导入
    from langchain_core.runnables import RunnableConfig
except Exception:  # noqa: BLE001 # pragma: no cover
    RunnableConfig = dict  # type: ignore[misc,assignment]

# 连续第几次相同调用触发提醒。第一档是轻提示，之后是点名工具+次数+参数的详细版。
DEFAULT_THRESHOLDS: tuple[int, ...] = (3, 5, 8)

# 提醒里引用参数的长度上限。链的判重永远用**完整**规范串，这个上限只约束提醒文本
# ——否则一个正在打转的长参数调用会把自己原样带进下一次请求，越滚越大。
ARGS_PREVIEW_CHARS = 200

# 同时跟踪的调用方上限。一轮里 owner 就是「主 agent + 几个子代理」，正常远低于此；
# 这是异常情况下防止 dict 无限增长的兜底。淘汰一个活跃 owner 只是让它的链清零，无害。
MAX_OWNERS = 64

# LangGraph 的 checkpoint_ns 分隔符
_NS_SEP = "|"


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


def owner_from_config(config: Any) -> str:
    """从 LangChain 注入的 config 推出「谁在调我」。

    `checkpoint_ns` 形如 `task:<uuid>|1|tools:<uuid>`：最后一段是当前 node，
    **前缀**才是「哪一次子代理调用」。取前缀的原因是同一个子代理会跨多个 superstep
    （model → tools → model …），每个 superstep 的 node 段都不同，只有前缀稳定。

    主 agent 在顶层图，ns 形如 `tools:<uuid>`，前缀为空串——空串就是主 agent 的 owner。
    取不到一律返回空串（退化成共享单链，即 Phase 89 的老行为），绝不抛。
    """
    try:
        if not isinstance(config, dict):
            return ""
        configurable = config.get("configurable")
        if not isinstance(configurable, dict):
            return ""
        ns = configurable.get("checkpoint_ns")
        if not isinstance(ns, str) or not ns:
            return ""
        return _NS_SEP.join(ns.split(_NS_SEP)[:-1])
    except Exception:  # noqa: BLE001 — 身份识别失败只该退化，不该打断工具
        logger.warning("owner_from_config failed", exc_info=True)
        return ""


@dataclass
class _Chain:
    """一个调用方的连续调用链。"""

    key: str | None = None
    count: int = 0
    fired: set[int] = field(default_factory=set)


class RepeatGuard:
    """按轮记账的连续重复检测。`build_tools` 每轮建一个，闭包内共享。

    共享一个实例但**按 owner 分链**：并发子代理互不干扰。
    """

    def __init__(
        self,
        thresholds: tuple[int, ...] = DEFAULT_THRESHOLDS,
        exclude: tuple[str, ...] = (),
        max_owners: int = MAX_OWNERS,
    ) -> None:
        cleaned = sorted({int(t) for t in thresholds})
        if not cleaned or cleaned[0] < 2:
            # 失败要响：静默回落默认值会让配置错误一直藏着（dsh 的 fail-loud 原则）
            raise ValueError(f"repeat guard thresholds 非法：{thresholds}")
        self.thresholds = tuple(cleaned)
        self.exclude = set(exclude)
        self.max_owners = max(1, int(max_owners))
        self._chains: dict[str, _Chain] = {}

    def _chain(self, owner: str) -> _Chain:
        chain = self._chains.get(owner)
        if chain is None:
            # dict 保持插入序：超上限时淘汰最旧的一个
            while len(self._chains) >= self.max_owners:
                self._chains.pop(next(iter(self._chains)))
            chain = self._chains[owner] = _Chain()
        return chain

    def check(
        self, tool_name: str, kwargs: dict[str, Any], owner: str = ""
    ) -> str | None:
        """记一次调用，需要提醒时返回提醒文本。

        `owner` 是调用方标识（见 `owner_from_config`），默认空串 = 主 agent /
        拿不到身份。不同 owner 的链完全独立。

        **未跟踪的工具对链是透明的**——既不累加也不重置。否则一个记账类工具插进来
        就能把循环「洗白」：`search X → read_source → search X` 仍应算连续两次 search X。
        """
        if tool_name in self.exclude:
            return None
        chain = self._chain(owner if isinstance(owner, str) else "")
        key = canonical_key(tool_name, kwargs)
        if key == chain.key:
            chain.count += 1
        else:
            chain.key, chain.count, chain.fired = key, 1, set()
        if chain.count not in self.thresholds or chain.count in chain.fired:
            return None
        chain.fired.add(chain.count)
        return self._reminder(tool_name, kwargs, chain.count)

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
        """新一轮用户输入：全部调用方的链清零（上一轮的重复不该影响这一轮）。"""
        self._chains.clear()


def guard_tool(fn, guard: RepeatGuard):
    """包一层重复检测；提醒**追加**在工具原始返回之后，不替换内容。

    不替换是有意的：工具结果要保持原样可审计（dsh 把提醒放在 additionalContexts 里，
    我们没有那条独立通道，追加是等价做法）。

    包装后的函数比原函数多一个 keyword-only 的 `config`，由 LangChain 在调用时注入
    （`RunnableConfig` 注解的参数**不会**进入模型可见的工具 schema）。原函数若自己
    声明了 `config` 则透传，否则由 wrapper 吞掉。
    """
    import functools
    import inspect

    if not inspect.iscoroutinefunction(fn):
        raise TypeError(f"repeat guard 只包装异步工具，收到 {fn!r}")

    sig = inspect.signature(fn)
    fn_takes_config = "config" in sig.parameters

    @functools.wraps(fn)
    async def wrapper(*args, config=None, **kwargs):
        if fn_takes_config:
            kwargs["config"] = config
        result = await fn(*args, **kwargs)
        try:
            # config 绝不能进链键：它每次调用都带新 uuid，一旦进键，链永远长不到阈值
            # → 守卫**完全失效**，且不报任何错。
            named = _named_args(fn, args, {k: v for k, v in kwargs.items() if k != "config"})
            # **调用失败/被拒也计数**：模型反复砸一个失败的调用，正是最该打断的循环
            note = guard.check(
                getattr(fn, "__name__", "tool"), named, owner_from_config(config)
            )
        except Exception:  # noqa: BLE001 — 守卫出问题绝不能影响工具本身
            logger.warning("repeat guard check failed", exc_info=True)
            return result
        # 只在字符串返回上追加；非字符串返回（结构化结果）原样放行，不硬塞提示进去
        return result + note if (note and isinstance(result, str)) else result

    if not fn_takes_config:
        _expose_config_param(wrapper, fn, sig)
    return wrapper


def _expose_config_param(wrapper, fn, sig) -> None:
    """让 LangChain 看得见 wrapper 上新增的 `config` 参数。

    两处都要改，漏一处就静默失效（守卫退回共享单链，不报错）：

    1. `__signature__`：`functools.wraps` 设了 `__wrapped__`，`inspect.signature`
       默认会跟随它拿到**原函数**的签名，wrapper 新增的 config 根本不可见。
       显式设 `__signature__` 并删掉 `__wrapped__` 消除歧义。
    2. `__annotations__`：LangChain 建 schema 时会读 type hints。注意
       `functools.wraps` 复制的是**同一个 dict 对象**，必须先拷贝再改，
       否则会污染原函数的注解。
    """
    import inspect

    try:
        params = list(sig.parameters.values())
        config_param = inspect.Parameter(
            "config",
            inspect.Parameter.KEYWORD_ONLY,
            default=None,
            annotation=RunnableConfig,
        )
        # 必须插在 **kwargs 之前，否则签名非法
        idx = next(
            (i for i, p in enumerate(params) if p.kind is inspect.Parameter.VAR_KEYWORD),
            len(params),
        )
        params.insert(idx, config_param)
        wrapper.__signature__ = sig.replace(parameters=params)
        wrapper.__annotations__ = dict(getattr(fn, "__annotations__", {}))
        wrapper.__annotations__["config"] = RunnableConfig
        if hasattr(wrapper, "__wrapped__"):
            del wrapper.__wrapped__
    except Exception:  # noqa: BLE001 — 暴露失败只该退化成共享单链，不该让工具集构建失败
        logger.warning("repeat guard failed to expose config param on %r", fn, exc_info=True)


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
