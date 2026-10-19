"""按攻略合并并发工作；线程锁可跨 asyncio.run 的不同事件循环使用。"""
import asyncio
import threading
from contextlib import asynccontextmanager

_registry_lock = threading.Lock()
_registry = {}


@asynccontextmanager
async def source_guard(key: str):
    with _registry_lock:
        entry = _registry.setdefault(key, [threading.Lock(), 0])
        entry[1] += 1
    acquired = False
    try:
        while not acquired:
            acquired = entry[0].acquire(blocking=False)
            if not acquired:
                await asyncio.sleep(0.05)
        yield
    finally:
        if acquired:
            entry[0].release()
        with _registry_lock:
            entry[1] -= 1
            if entry[1] == 0:
                _registry.pop(key, None)
