"""每用户浏览器池（Phase 19）单测。注入假 launcher，不拉真 Chrome，全离线。"""

import threading
import time

import pytest

from app.tools.browser_pool import BrowserAcquireTimeout, BrowserPool


class FakeProc:
    def __init__(self):
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self._alive = False


def make_pool(max_size=2, **kw):
    launches = []

    def launch(port, profile_dir):
        launches.append((port, profile_dir))
        return FakeProc()

    pool = BrowserPool(
        max_size=max_size, port_start=9400, profile_base="/tmp/prof",
        idle_timeout_s=kw.get("idle_timeout_s", 600),
        acquire_timeout_s=kw.get("acquire_timeout_s", 5),
        launch=launch, ready=lambda port: True,
    )
    return pool, launches


def test_acquire_reuses_same_user_instance():
    pool, launches = make_pool()
    url1 = pool.acquire("u1")
    pool.release("u1")
    url2 = pool.acquire("u1")
    assert url1 == url2
    assert len(launches) == 1  # 复用，未二次拉起


def test_distinct_users_distinct_instances():
    pool, launches = make_pool(max_size=2)
    u1 = pool.acquire("u1"); pool.release("u1")
    u2 = pool.acquire("u2"); pool.release("u2")
    assert u1 != u2
    assert len(launches) == 2


def test_evict_lru_idle_when_full():
    pool, launches = make_pool(max_size=2)
    pool.acquire("u1"); pool.release("u1")
    time.sleep(0.01)
    pool.acquire("u2"); pool.release("u2")
    pool.acquire("u3"); pool.release("u3")  # 满 → 驱逐最久空闲 u1
    assert "u1" not in pool._insts
    assert set(pool._insts) == {"u2", "u3"}
    assert len(launches) == 3


def test_same_user_serialized():
    pool, _ = make_pool(max_size=2)
    pool.acquire("u1")  # 持有 busy，不释放
    got = []

    def second():
        try:
            pool.acquire("u1", )
            got.append("acquired")
        except BrowserAcquireTimeout:
            got.append("timeout")

    t = threading.Thread(target=second, daemon=True)
    t.start()
    t.join(timeout=0.3)
    assert got == []  # 同用户第二次被阻塞
    pool.release("u1")
    t.join(timeout=2)
    assert got == ["acquired"]


def test_all_busy_queues_and_on_wait_fires():
    pool, _ = make_pool(max_size=1)
    pool.acquire("u1")  # 唯一槽位被占
    waited = []
    done = threading.Event()

    def second():
        pool.acquire("u2", on_wait=lambda pos: waited.append(pos))
        done.set()

    t = threading.Thread(target=second, daemon=True)
    t.start()
    time.sleep(0.2)
    assert waited == [1]  # 排队提示：前面 1 个在用
    assert not done.is_set()
    pool.release("u1")  # 释放 → u2 驱逐空闲 u1 后拿到
    assert done.wait(timeout=2)
    assert "u2" in pool._insts and "u1" not in pool._insts


def test_acquire_timeout():
    pool, _ = make_pool(max_size=1, acquire_timeout_s=0.4)
    pool.acquire("u1")  # 占满不放
    with pytest.raises(BrowserAcquireTimeout):
        pool.acquire("u2")


def test_restart_kills_and_respawns():
    pool, launches = make_pool()
    pool.acquire("u1"); pool.release("u1")
    pool.restart("u1")
    assert "u1" not in pool._insts
    pool.acquire("u1")
    assert len(launches) == 2  # 重新拉起


def test_reap_idle():
    pool, _ = make_pool(idle_timeout_s=0)
    pool.acquire("u1"); pool.release("u1")
    time.sleep(0.01)
    assert pool.reap_idle() == 1
    assert pool._insts == {}


def test_busy_instance_not_reaped():
    pool, _ = make_pool(idle_timeout_s=0)
    pool.acquire("u1")  # busy
    assert pool.reap_idle() == 0
    assert "u1" in pool._insts


def test_launch_failure_rolls_back():
    def bad_launch(port, profile_dir):
        raise RuntimeError("boom")

    pool = BrowserPool(max_size=1, port_start=9400, profile_base="/tmp/prof",
                       launch=bad_launch, ready=lambda p: True)
    with pytest.raises(RuntimeError):
        pool.acquire("u1")
    assert pool._insts == {}  # 回滚，槽位释放
    # 槽位已释放，换个能启动的用户可用
    pool._launch = lambda port, profile_dir: FakeProc()
    assert pool.acquire("u2").startswith("http://127.0.0.1:")
