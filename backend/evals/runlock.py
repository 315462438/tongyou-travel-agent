"""同一评估集不许并发跑（2026-08-14）。

**踩过的坑**：同一个 `--tag` 起了两个 `extract_eval`，先启动的那个**后写盘**，
用它进程里那份**修复前**的检查器结果，把后启动那次的 5/5 快照覆盖成了 4/5。
排查时看到的是「代码明明修了、报表还是红的」——最难查的那种。

两个特点让它特别隐蔽：
- 快照只在最后落盘，所以谁先启动不决定谁的结果留下来，**谁后结束才决定**
- Python 在进程启动时就把检查器 import 进内存了，中途改磁盘上的代码不影响在跑的那个

所以这里用最笨但可靠的办法：一个带 PID 的锁文件，检测到活着的同名进程就直接拒绝启动。
"""

from __future__ import annotations

import os
import pathlib
from contextlib import contextmanager

LOCKS = pathlib.Path(__file__).parent / "runs" / ".locks"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)          # 信号 0 = 只探测存在性，不真的发信号
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:      # 存在但不属于当前用户
        return True
    return True


@contextmanager
def single_run(name: str):
    """`name` 相同的评估同一时刻只允许一个在跑。"""
    LOCKS.mkdir(parents=True, exist_ok=True)
    path = LOCKS / f"{name}.pid"
    if path.exists():
        try:
            old = int(path.read_text().strip() or 0)
        except ValueError:
            old = 0
        if old and old != os.getpid() and _alive(old):
            raise SystemExit(
                f"已有一个 {name} 评估在跑（pid {old}）。并发跑会互相覆盖快照，"
                f"而且后结束的那个可能还持有改动前的代码——先等它结束，或 kill 掉它。"
            )
        path.unlink(missing_ok=True)   # 陈旧锁（进程已死）直接清掉
    path.write_text(str(os.getpid()), encoding="utf-8")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
