# 踩坑：CompositeBackend 多个路由共享同一个 StateBackend 实例，glob/ls 会二次拼前缀

Phase 27b 上线后拿真实线上环境测试 Docker 沙箱（打开 `DOCKER_SANDBOX_ENABLED` 跑了一轮
真实深度研究请求）才发现的 bug——纯静态测试/mock 没能覆盖到，值得记录。

## 现象

打开 `docker_sandbox_enabled=true` 后，agent 一次 `glob(pattern="/**/*.md")` 的结果里，
本该是 5 个真实技能文件（`/main/budget-estimation/SKILL.md` 等），实际返回了 15 条，
每条都被错误地重复拼了前缀：

```
/main/main/budget-estimation/SKILL.md
/main/main/trip-comparison/SKILL.md
/main/researcher/amap-data-lookup/SKILL.md
/researcher/main/budget-estimation/SKILL.md
/researcher/researcher/web-source-triage/SKILL.md
/user/main/budget-estimation/SKILL.md
...
```

同时污染了 `meta.skills_used`（Phase 27 从 `read_file` 调用提炼技能名的功能）——提取出的
是 "main"/"researcher" 这种路径片段，不是真实技能名。

## 原因

当时的装配方式（已废弃）：

```python
state = StateBackend()
backend = CompositeBackend(
    default=DockerSandboxBackend(tmp_dir),
    routes={"/main/": state, "/researcher/": state, "/user/": state},  # 三个路由共享同一实例
)
```

`CompositeBackend.glob()`（`deepagents/backends/composite.py`）在处理"路径没有明确匹配到
单一路由"（比如没传 `path` 参数的全局 glob）时，会对**每一个** route 分别调用
`backend.glob(route_pattern, "/")`，再用 `_remap_file_info_path` 把 `route_prefix` 拼回
结果路径上——**这个逻辑假设每个路由背后的 backend，返回的路径是相对它自己根目录的**
（比如一个真的只存了 `/budget-estimation/SKILL.md` 这种"局部"路径的独立 backend）。

但我们让三个路由背后是**同一个** `StateBackend()` 实例，而 `StateBackend` 内部根本没有
"路由隔离"这回事——它是一整块 flat 的 `{绝对虚拟路径: 内容}` 字典（`/main/xxx`、
`/researcher/xxx`、`/user/xxx` 全挤在同一份 dict 里，靠 key 前缀"看起来"分了组，实际上
`ls("/")`/`glob(..., "/")` 会把所有 key 都吐出来）。于是：

1. `CompositeBackend` 对路由 `/main/` 调 `state.glob(pattern, "/")` → 返回**全部** 5 个
   真实绝对路径（不是只属于 `/main/` 的那 3 个）；
2. `_remap_file_info_path` 把 `/main` 前缀拼到这 5 个**本来就已经是绝对路径**的结果上
   → 产生 `/main/main/...`、`/main/researcher/...` 这种二次拼接的错乱路径；
3. 对 `/researcher/`、`/user/` 路由重复上述过程，各自再拼一遍。

## 解法

**不要让 `CompositeBackend` 的多个路由指向同一个 `StateBackend` 实例**——这个组合本身就
违反了 `CompositeBackend` 的设计假设，而且创建多个 `StateBackend()` Python 对象也无法
解决问题（它们背后读写的是**同一个** LangGraph `files` 状态通道，不是各自独立的存储）。

改成沙箱开启时**完全不用 `CompositeBackend`**：技能文件在轮初直接物理写进沙箱自己的
per-turn 临时目录（`_write_skill_files_to_dir`），backend 就是单一的
`DockerSandboxBackend`（`FilesystemBackend` 的 `virtual_mode=True` 子类）。没有多路由
聚合这一层，`ls`/`glob` 直接对真实目录操作，问题不存在。见
`app/agent/deep_research.py::_build_backend`。

## 推广

用任何"路径前缀路由到不同 backend"的框架能力（`CompositeBackend` 或同类设计）时，
一定要确认：**每个被路由到的 backend，是否真的对"自己的根目录"有独立的地址空间**。
如果背后是一个全局共享、没有真正路径隔离的存储（内存字典、单一数据库表等），
"多个路由指向同一实例"这个看起来省事的写法会悄悄违反框架对"路由结果是局部相对路径"
的假设，产生数据错乱——而且这类 bug 很难被 mock 测试捕捉到（mock 通常会替身掉
真实的路由聚合逻辑本身），只有跑一次真实的、涉及跨路由聚合操作（全局 `glob`/`ls`）的
端到端请求才会暴露。
