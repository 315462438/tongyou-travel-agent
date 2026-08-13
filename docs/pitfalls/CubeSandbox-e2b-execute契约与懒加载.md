# 踩坑：接 Cube Sandbox（E2B 协议）时 execute() 的两个隐藏契约

> **状态**：这套 Cube Sandbox 集成后来因为服务器硬件够不到官方最低要求（内存/CPU/KVM/
> 磁盘文件系统均不满足，安装还要换内核重启生产机）被移除，`app/tools/cube_sandbox.py`
> 等代码已不在仓库里。保留本文档是因为记录的两个契约（`BaseSandbox.execute()` 不能抛
> 异常、`CompositeBackend.execute()` 不可路径路由）是 deepagents 框架本身的通用知识，
> 以后接任何沙箱 backend 都用得上。

Phase 27 给深度研究 agent 接 Cube Sandbox（自托管、E2B SDK 兼容）代码执行能力时，
读 deepagents 源码（`deepagents/backends/sandbox.py` + 自带的 `LangSmithSandbox` 参考实现）
才发现两处不写代码不会注意到的契约，记录下来避免以后接别的沙箱 provider 时重踩。

## 1. `sandbox.commands.run()` 对非零退出码是**抛异常**，不是返回带 exit_code 的结果

装了 `e2b` SDK 后天然会以为 `sandbox.commands.run(cmd)` 会像 `subprocess.run` 一样返回一个
"无论成功失败都能读 exit_code" 的结果对象。实际上 e2b SDK 的 `CommandHandle.wait()`
（`run()` 内部调用）源码写得很清楚：

```python
if self._result.exit_code != 0:
    raise CommandExitException(stdout=..., stderr=..., exit_code=..., error=...)
```

而 `deepagents` 的 `BaseSandbox`/`execute` 工具契约是**永远返回 `ExecuteResponse`，不能
抛异常**——很多派生操作（`ls`/`grep`/`glob` 都是拼一段 shell 脚本丢给 `execute()` 再解析
输出）依赖这一点，`sandbox.py` 里 grep 命令甚至显式拼了 `|| true` 就是为了确保底层
shell 命令永远零退出码。如果直接把 `sandbox.commands.run()` 包一层就当 `execute()`
用，agent 一旦跑了个失败的命令（很常见，比如脚本里有个笔误），`CommandExitException`
会直接冒穿整个工具调用栈，把这一整轮深度研究搞挂，而不是像预期那样"这条命令失败了，
agent 看到错误信息后自己调整重试"。

**解法**：`CubeSandboxBackend.execute()` 显式 catch `CommandExitException`
（`app/tools/cube_sandbox.py`），把它携带的 `stdout`/`stderr`/`exit_code` 原样转成
`ExecuteResponse`，和成功路径统一处理，两条路径都不抛异常。

## 2. `execute()` 在 `CompositeBackend` 里"不可按路径路由，永远走 default"

一开始设想的是"技能路径 `/main/` `/researcher/` `/user/` 路由到 `StateBackend`，其余路径
（含 `execute` 隐含的沙箱根目录）路由到 Cube Sandbox"，以为 `CompositeBackend` 会按某种
路径把 `execute()` 也分流。看源码才发现 `CompositeBackend.execute()`/`aexecute()`
根本不接受路径参数，注释直接写明：

> Unlike file operations, execution is not path-routable — it always delegates to
> the default backend.

即：`execute()` 只认 `CompositeBackend(default=...)` 里的 `default`，`routes` 参数对
`execute()` 完全不起作用。所以装配时必须把 Cube Sandbox 放在 `default` 位置，技能路径放
`routes` 里（`app/agent/deep_research.py::_build_backend`），顺序反了会导致
`isinstance(self.default, SandboxBackendProtocol)` 检查失败，`execute` 工具直接报
"Default backend doesn't support command execution"。

## 推广
接入任何"某个 backend 只实现部分能力（比如只能 execute，不适合当通用文件存储）"的
第三方沙箱/执行环境时：
- 先假设它的成功/失败路径**返回形状不同**（成功是返回值，失败是异常），不要照抄
  "看起来像"的示例代码就收工——检查目标契约（这里是 `ExecuteResponse` 永不抛异常）
  是否真的被满足；
- 如果宿主框架提供了"多 backend 组合路由"的机制（这里是 `CompositeBackend`），先看清楚
  它对每种操作的路由粒度——不是所有操作都同等可路由，`execute()` 就是反例。
