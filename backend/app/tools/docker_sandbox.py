"""Docker 沙箱代码执行 backend（Phase 27b）。

复用服务器已装的 Docker（同机 Langfuse 也用它跑），不需要新守护进程/内核/重启——
但共享宿主内核（namespace/cgroup 隔离），不是 Cube Sandbox/E2B 那种 VM 级边界，
见 docs/pitfalls/Docker沙箱共享内核隔离与非root挂载权限.md。

设计：agent 的 ls/read/write/edit/grep/glob 由 `FilesystemBackend` 直接在一个
per-turn 的 host 临时目录上操作（`virtual_mode=True` 限定在这个目录内，不经容器，
快且简单——同一批 pitfall 提醒过 virtual_mode 默认 False 的坑，这里必须显式传 True）；
只有 `execute()`（真正跑 agent 指定的任意命令）才启动一个一次性、高度限制的容器，
把这个临时目录挂进去当 /workspace。
"""

from __future__ import annotations

import logging
import os
import subprocess
import uuid
from pathlib import Path

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import ExecuteResponse, SandboxBackendProtocol

from app.config import settings


def _dir_size(path: str) -> int:
    """目录内所有普通文件的字节数之和（不跟随软链，软链不计入）。"""
    total = 0
    for dirpath, _dirs, names in os.walk(path, followlinks=False):
        for n in names:
            p = os.path.join(dirpath, n)
            if os.path.islink(p):
                continue
            try:
                total += os.lstat(p).st_size
            except OSError:
                continue
    return total

logger = logging.getLogger(__name__)

# execute() 把 root_dir 挂载到容器内的这个路径（-v root_dir:/workspace -w /workspace）
MOUNT_POINT = "/workspace"


def _combine(stdout: str, stderr: str) -> str:
    if stdout and stderr:
        return stdout + "\n" + stderr
    return stdout or stderr or ""


def _decode(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class DockerSandboxBackend(FilesystemBackend, SandboxBackendProtocol):
    """文件操作走本地临时目录（FilesystemBackend, virtual_mode=True）；
    execute() 把这个目录挂进一次性锁定容器里跑命令。
    """

    def __init__(self, root_dir: str) -> None:
        super().__init__(root_dir=root_dir, virtual_mode=True)

    @property
    def id(self) -> str:
        return f"docker-sandbox({self.cwd})"

    def _resolve_path(self, key: str) -> Path:
        """把挂载点前缀 `/workspace` 当作根目录 `/` 的别名。

        文件工具的虚拟根 `/` 和 execute() 容器里的 `/workspace` 是同一个目录，但模型
        必然照着 execute 输出里的容器路径来写文件（pwd=/workspace）。不做别名的话，
        `write_file("/workspace/x")` 会落在 host `root_dir/workspace/x`（容器里的
        `/workspace/workspace/x`），execute 在 `/workspace/x` 找不到，而 glob/read 又说
        文件存在——agent 被互相矛盾的工具反馈逼进死循环直到步数超限（线上踩坑，见
        docs/pitfalls/Docker沙箱workspace路径错位死循环.md）。

        只剥一层前缀：`/workspace/workspace/x` → `/workspace/x`（host `root_dir/workspace/x`），
        与容器视角一致；名叫 workspace 的真实子目录不受影响。
        """
        vpath = key if key.startswith("/") else "/" + key
        if vpath == MOUNT_POINT or vpath.startswith(MOUNT_POINT + "/"):
            vpath = vpath[len(MOUNT_POINT):] or "/"
        return super()._resolve_path(vpath)

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        run_timeout = timeout if timeout is not None else settings.docker_sandbox_timeout_s
        name = f"travel-sbx-{uuid.uuid4().hex[:12]}"
        argv = [
            "docker", "run", "--rm",
            "--name", name,
            "--network", "none",
            "--memory", settings.docker_sandbox_memory,
            "--memory-swap", settings.docker_sandbox_memory,  # 和 --memory 相等，禁止用 swap 绕过限额
            "--cpus", settings.docker_sandbox_cpus,
            "--pids-limit", "64",  # 防 fork bomb
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--read-only",
            "--tmpfs", "/tmp:rw,size=64m",
            "--user", "nobody",
            "-v", f"{self.cwd}:{MOUNT_POINT}:rw",
            "-w", MOUNT_POINT,
            settings.docker_sandbox_image,
            "sh", "-c", command,
        ]
        # Phase 69：/workspace 是宿主绑定挂载，没有磁盘配额（内存/CPU/pids 都限了，唯独磁盘没限）。
        # 实测容器内可 dd 出几百 MB 落到宿主盘，反复触发能打满 / 拖垮 PG/后端。
        # docker 的 --storage-opt size= 依赖存储驱动（overlay2 需 pquota），不能指望，
        # 因此在执行前后各查一次目录用量：超限就清掉本次新增并把错误如实告诉模型。
        before = _dir_size(self.cwd)
        try:
            proc = subprocess.run(  # noqa: S603 — argv 全是固定标志 + 受控 image/command，不经 shell
                argv, capture_output=True, text=True, timeout=run_timeout,
            )
            over = self._enforce_disk_quota(before)
            if over:
                return ExecuteResponse(output=over, exit_code=1)
            return ExecuteResponse(output=_combine(proc.stdout, proc.stderr), exit_code=proc.returncode)
        except subprocess.TimeoutExpired as e:
            # `docker run --rm` 的客户端进程被杀不等于容器被杀——dockerd 独立管理容器生命周期，
            # 必须显式 kill 一次，否则超时的沙箱会在后台继续跑并累积成孤儿容器（踩坑）。
            self._kill(name)
            partial = _combine(_decode(e.stdout), _decode(e.stderr))
            output = f"{partial}\n" if partial else ""
            return ExecuteResponse(output=f"{output}命令超时（>{run_timeout}s），已终止。", exit_code=124)
        except FileNotFoundError:
            logger.error("docker 命令不存在，无法执行沙箱代码")
            return ExecuteResponse(output="沙箱不可用：服务器没有安装 docker", exit_code=127)
        except Exception as e:  # noqa: BLE001 — execute() 契约：永远返回 ExecuteResponse，不抛异常
            logger.warning("docker sandbox execute failed", exc_info=True)
            return ExecuteResponse(output=f"沙箱执行出错：{type(e).__name__}: {e}", exit_code=1)

    def _enforce_disk_quota(self, before: int) -> str:
        """超出工作区磁盘上限就删掉本次新增的大文件，返回给模型看的错误文案（未超返回 ""）。"""
        limit = settings.docker_sandbox_workspace_max_bytes
        after = _dir_size(self.cwd)
        if after <= limit:
            return ""
        logger.warning("沙箱工作区超限：%d → %d 字节（上限 %d），清理新增大文件", before, after, limit)
        # 从大到小删，直到回到限额内（种子文件通常很小，先删大的等于优先删掉刷出来的垃圾）
        files: list[tuple[int, str]] = []
        for dirpath, _dirs, names in os.walk(self.cwd, followlinks=False):
            for n in names:
                p = os.path.join(dirpath, n)
                if os.path.islink(p):
                    continue
                try:
                    files.append((os.lstat(p).st_size, p))
                except OSError:
                    continue
        for size, p in sorted(files, reverse=True):
            if after <= limit:
                break
            try:
                os.remove(p)
                after -= size
            except OSError:
                continue
        return (f"工作区磁盘用量超出上限（{limit // (1024 * 1024)}MB），本次产生的大文件已被清理。"
                "请不要生成大体积文件，只保留必要的小结果文件。")

    def _kill(self, name: str) -> None:
        try:
            subprocess.run(["docker", "kill", name], capture_output=True, timeout=10)  # noqa: S603
        except Exception:  # noqa: BLE001
            logger.warning("failed to kill timed-out sandbox container %s", name, exc_info=True)
