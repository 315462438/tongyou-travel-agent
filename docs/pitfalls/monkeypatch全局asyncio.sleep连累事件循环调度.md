# 踩坑：monkeypatch 全局 `asyncio.sleep` 会连累事件循环自身，测试直接卡死

写 Phase 26 `test_invoke_with_cancel_seeds_skill_files`（验证 `_invoke_with_cancel` 的
`agent.ainvoke` payload 带上技能种子）时，为了让测试不真的等 1 秒，想当然地把
`_invoke_with_cancel` 内部的 `await asyncio.sleep(1)` monkeypatch 成立即返回：

```python
async def fake_sleep(_):
    return None
monkeypatch.setattr("app.agent.deep_research.asyncio.sleep", fake_sleep)
```

## 现象
测试**直接卡死**，`pytest -q` 挂起不返回（不是变慢，是永远不结束）；就算在测试里另外
包一层 `asyncio.wait_for(coro, timeout=5)` 兜底也照样卡死超过 60 秒——说明卡住的不是
被测代码本身的循环，而是 asyncio 事件循环的调度/超时机制本身被搞坏了。

## 原因
`app.agent.deep_research` 模块里 `import asyncio` 拿到的就是**全局唯一的** `asyncio`
模块对象，不是自己的私有拷贝。`monkeypatch.setattr("app.agent.deep_research.asyncio.sleep",
...)` 表面上看是"只改这个模块用到的 sleep"，实际上等价于直接执行
`asyncio.sleep = fake_sleep`——**进程内所有代码**（包括 asyncio/anyio 自己内部某些
依赖 `asyncio.sleep` 做轮询/让出控制权的机制、`asyncio.wait_for` 的实现细节等）都会用到
这个被替换的假实现。真实的 `asyncio.sleep` 会正确地把控制权交还给事件循环并注册一个
定时器回调；替换成"什么都不做直接 return"的协程后，某些依赖真实定时器语义的内部逻辑
永远等不到该发生的回调，整个事件循环卡死。

## 解法
**不要 monkeypatch 全局 `asyncio.sleep`**，哪怕看起来只是想让某个特定模块的调用变快。
如果被测代码就是会有一次真实的 `await asyncio.sleep(1)`，测试直接接受这 1 秒真实等待
（用 `asyncio.wait_for(..., timeout=10)` 兜底防止真正卡死即可），比冒险替换全局调度原语
安全得多：

```python
# 不 patch asyncio.sleep，让它真的睡 1 秒——比连累事件循环调度安全
result = asyncio.run(asyncio.wait_for(_invoke_with_cancel(...), timeout=10))
```

## 推广
`monkeypatch.setattr` 支持任意"看起来限定在某个模块"的点分路径，但如果目标模块的属性
本身是从标准库/框架"借用"过来的引用（`import asyncio` 而不是自己实现的包装），
patch 它等价于 patch 全局单例。凡是要 mock 时间/调度相关的标准库原语
（`asyncio.sleep`、`time.sleep`、事件循环本身），先确认作用域是否真的被限定住了，
拿不准就换成"接受真实等待 + 外层超时兜底"这种更保守的做法。
