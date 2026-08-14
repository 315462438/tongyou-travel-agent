"""评估并发锁的单测（2026-08-14）。

对应的真实事故：同一个 `--tag` 起了两个 `extract_eval`，**先启动的那个后写盘**，
用它进程里那份修复前的检查器结果，把后启动那次的 5/5 快照覆盖成了 4/5。
现场表现是「代码明明修了、报表还是红的」。
"""

import os

import pytest

from evals.runlock import LOCKS, single_run


@pytest.fixture(autouse=True)
def _clean():
    yield
    for p in LOCKS.glob("*.pid"):
        p.unlink(missing_ok=True)


def test_lock_is_released_after_a_normal_run():
    with single_run("t_normal"):
        assert (LOCKS / "t_normal.pid").exists()
    assert not (LOCKS / "t_normal.pid").exists()


def test_lock_is_released_even_if_the_run_blows_up():
    """跑挂了也要放锁，否则一次异常就把这个评估集永久锁死。"""
    with pytest.raises(RuntimeError):
        with single_run("t_boom"):
            raise RuntimeError("boom")
    assert not (LOCKS / "t_boom.pid").exists()


def test_second_concurrent_run_is_refused():
    """并发跑会互相覆盖快照——直接拒绝，不是警告一句就继续。"""
    LOCKS.mkdir(parents=True, exist_ok=True)
    (LOCKS / "t_busy.pid").write_text(str(os.getpid() + 0))  # 当前进程 = 活着
    # 写自己的 pid 会被当成「同一个进程」放行，所以造一个确实活着的**别的** pid：
    # 父进程（pytest 的 launcher 或 shell）一定活着且不等于自己
    (LOCKS / "t_busy.pid").write_text(str(os.getppid()))
    with pytest.raises(SystemExit) as ei:
        with single_run("t_busy"):
            pytest.fail("不该进到这里")
    assert "并发" in str(ei.value) or "在跑" in str(ei.value)


def test_stale_lock_from_a_dead_process_is_cleared():
    """机器重启/进程被 kill 留下的陈旧锁不能把评估永久锁死。"""
    LOCKS.mkdir(parents=True, exist_ok=True)
    (LOCKS / "t_stale.pid").write_text("999999")  # 几乎不可能存在的 pid
    with single_run("t_stale"):
        assert (LOCKS / "t_stale.pid").read_text() == str(os.getpid())


def test_garbage_lock_file_does_not_crash():
    LOCKS.mkdir(parents=True, exist_ok=True)
    (LOCKS / "t_junk.pid").write_text("这不是个数字")
    with single_run("t_junk"):
        pass
