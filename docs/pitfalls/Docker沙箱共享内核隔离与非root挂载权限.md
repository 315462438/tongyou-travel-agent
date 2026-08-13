# 踩坑：Docker 沙箱的隔离边界、非 root 挂载权限、超时后的孤儿容器

Phase 27b 给深度研究 agent 接轻量代码执行能力时（Cube Sandbox 因服务器硬件不够被移除后
改用已装的 Docker），记录三处容易漏掉的细节。

## 1. 隔离边界：共享宿主内核，不是真 VM

Docker 容器靠 Linux namespace + cgroup 隔离，和 Cube Sandbox/E2B/Firecracker 那种基于
KVM 的微 VM**共享同一个宿主内核**——容器逃逸历史上确实发生过，只是比 VM 逃逸罕见。
对个人项目、非多租户 SaaS 场景，配合下面这组加固参数（`--network=none` 断网、
`--read-only` 只读根文件系统、`--cap-drop=ALL` 丢弃全部 capability、
`--security-opt=no-new-privileges` 禁提权、`--user nobody` 非 root、
`--pids-limit` 限进程数防 fork bomb、`--memory`/`--memory-swap` 相等封顶内存防用 swap
绕过限额）是常见且合理的折中，但**必须让用户知道这不是 VM 级边界**，不能含糊其辞地说
"沙箱"就当成同等安全性——已在 `docs/task_plans/` 里向用户明确过这个权衡。

## 2. 非 root 容器用户写不进 host 挂载目录

`tempfile.mkdtemp()` 创建的目录默认 `0o700`（仅属主可读写）。容器里用
`--user nobody` 跑（uid 通常是 65534，且不会跟宿主机 `ubuntu` 用户的 uid 对齐），
对这个 `0o700` 目录**没有写权限**——挂进去后容器内 `write_file`/脚本写文件全部
`Permission denied`，现象上很容易先怀疑是挂载参数错了，其实是权限问题。

**解法**：在 `deep_research.py::_build_backend` 创建临时目录后显式
`os.chmod(tmp_dir, 0o777)`。可以放宽到这个程度是因为这个目录本身就是
per-turn、短生命周期、轮末立刻 `shutil.rmtree` 删除的临时目录，不是长期存在、
跨用户共享的位置——不是什么权限都能这样放。

## 3. `docker run --rm` 的客户端进程被杀 ≠ 容器被杀

`subprocess.run(["docker","run","--rm",...], timeout=N)` 超时后 Python 只是杀了
**本地 `docker` CLI 客户端进程**；`dockerd` 独立管理容器生命周期，容器本身可能继续在
后台跑，`--rm` 的"退出后自动删除"这时候根本没触发（容器没有"退出"，是客户端断开了）。
不处理的话，超时的沙箱执行会在服务器上累积孤儿容器，长期占用内存（这台服务器已经
因为内存紧张放弃了 Cube Sandbox，更不能再悄悄攒一堆没人管的容器）。

**解法**：每次 `execute()` 生成一个唯一 `--name`，`subprocess.TimeoutExpired` 时显式
`docker kill <name>`（配合 `--rm`，kill 之后容器会被自动清理）。
回归测试：`test_execute_timeout_kills_container`（断言真的调用了对应容器名的 kill）。

## 推广
接任何"共享宿主的进程级沙箱"（Docker/容器/chroot 等，区别于真 VM）时，至少检查这三件事：
1. 明确告知这是共享内核隔离，不是 VM 级边界，别让"沙箱"这个词掩盖安全模型的差异；
2. 挂载目录的属主/权限跟容器内运行身份是否匹配，非 root 容器很容易踩权限坑；
3. 客户端超时 ≠ 后台进程真的被杀，凡是"客户端发起、后端独立生命周期"的资源
   （容器、远程 job、子进程组…）都要显式补一次终止操作。
