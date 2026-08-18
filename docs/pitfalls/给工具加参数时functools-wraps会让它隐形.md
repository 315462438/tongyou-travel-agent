# 给工具加参数时 functools.wraps 会让它「隐形」

2026-08-18　Phase 95（重复调用守卫按调用方分链）

## 场景

要让 LangChain/LangGraph 在调用工具时注入 `config`（拿调用方身份），
做法是给工具函数多声明一个 `config: RunnableConfig` 参数。而我们的工具外面
包了一层装饰器（`repeat_guard.guard_tool`），所以参数得加在 **wrapper** 上。

这一步有三个坑，共同特征是：**出问题时不抛任何异常**，功能只是悄悄不生效。
不写测试就永远发现不了。

## 坑 1：`functools.wraps` 让新参数对 LangChain 不可见

```python
@functools.wraps(fn)
async def wrapper(*args, config=None, **kwargs): ...
```

看起来 wrapper 接受 config 了，但 `functools.wraps` 会设 `wrapper.__wrapped__ = fn`，
而 `inspect.signature()` 默认 `follow_wrapped=True`——它会顺着 `__wrapped__` 拿到
**原函数**的签名。LangChain 建工具 schema 时看到的是原函数的参数表，里面根本没有
config，于是**不会注入**。

**现象**：一切正常运行，`config` 永远是 `None`，按身份分链静默退化成全局共享单链。

**解法**：显式构造并设置 `__signature__`（`inspect.signature` 遇到有 `__signature__`
的对象会停止 unwrap），同时 `del wrapper.__wrapped__` 消除歧义：

```python
params = list(sig.parameters.values())
params.insert(idx, inspect.Parameter("config", inspect.Parameter.KEYWORD_ONLY,
                                     default=None, annotation=RunnableConfig))
wrapper.__signature__ = sig.replace(parameters=params)
del wrapper.__wrapped__
```

`idx` 要算成 `**kwargs` 之前的位置，否则签名非法。

## 坑 2：`functools.wraps` 复制的是**同一个** `__annotations__` 对象

只改 `__signature__` 还不够——LangChain 建 schema 的部分路径读的是 type hints
（`__annotations__`），不是签名。所以还得：

```python
wrapper.__annotations__["config"] = RunnableConfig   # ❌ 会污染原函数！
```

`functools.update_wrapper` 的实现是 `setattr(wrapper, attr, getattr(wrapped, attr))`，
`__annotations__` 是**按引用赋值**的——`wrapper.__annotations__` 和
`fn.__annotations__` 是同一个 dict。上面这行会把 `config` 塞进原函数的注解里。

**现象**：原函数在别处被当普通函数用时，注解里凭空多出一个 config。

**解法**：先拷贝再改。

```python
wrapper.__annotations__ = dict(fn.__annotations__)
wrapper.__annotations__["config"] = RunnableConfig
```

## 坑 3：新参数混进了「调用指纹」

守卫用 `(工具名, 规范化参数)` 做链键判重。`config` 里含 `checkpoint_ns`，
每个 superstep 都带新 uuid——一旦它进了链键，**每次调用的键都不一样**，
链永远长不到阈值，守卫等于被彻底关掉。

**现象**：守卫再也不触发，日志干净，测试（如果只测 `check()` 不测包装后的工具）全绿。

**解法**：wrapper 里先把 config 摘出来，剩下的参数才拿去算键；并写一条测试专门钉住
「两次调用 config 内容不同但仍判为同一条链」。

## 一般化

> **给被装饰的函数「加参数」，本质是在改它对外的契约，而 `functools.wraps` 的
> 全部工作就是让 wrapper 伪装成原函数——这两件事天然打架。**

凡是靠 introspection 驱动的框架（LangChain 的 tool schema、FastAPI 的依赖注入、
pytest fixture），装饰器改签名都要同时处理 `__signature__` 和 `__annotations__`，
并且验证的方式必须是**让框架自己去解析一遍**，而不是自己 `assert` 签名对不对。

用例 `test_config_is_hidden_from_the_model_visible_schema` 就是这么写的——
真的调 `StructuredTool.from_function`，然后断言 `tool.args`。

另外配一条**集成**测试（真实 `ToolNode` 跑一遍，断言 owner 非空且并发两个不相同）：
这三个坑都属于「静默退化」，只有让真实框架跑一遍才证明得了注入确实发生。

## 附：探针期间的两个小绊

- `ToolNode([fn])` 会要求工具**必须有 docstring**（否则
  `ValueError: Function must have a docstring if description not provided`）。
- 直接 `ToolNode(...).ainvoke(...)` 会报 `Missing required config key 'N/A' for 'tools'`，
  它得放进一个编译好的图里跑。测试里就是这么组的。
