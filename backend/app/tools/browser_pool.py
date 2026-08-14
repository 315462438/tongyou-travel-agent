"""每用户浏览器 profile 池（Phase 19）

目标：每个 user_id 一个独立 Chrome + 独立 profile（各自扫码登录、互不覆盖、磁盘持久），
不同用户可并行浏览（受 `browser_pool_max` 内存约束），同一用户的并发轮次串行。

线程安全：每个后台任务跑在自己线程的独立事件循环里，所以用 threading.Condition
（而非 asyncio）保护池状态。acquire/release 由 ChromeMCP 在 asyncio.to_thread 里调用。

内存约束：服务器内存小，池上限默认 2；按需拉起、用完/空闲即回收（fresh 实例占用远低于
长跑实例），profile 目录保留登录态。超上限时排队，可选 on_wait 回调写「排队中」提示。
"""

import logging
import os
import socket
import subprocess
import threading
import time
import urllib.request

from app.config import settings

logger = logging.getLogger(__name__)


class BrowserAcquireTimeout(Exception):
    pass


def _default_is_alive(proc) -> bool:
    return proc is not None and proc.poll() is None


def _default_launch(port: int, profile_dir: str):
    os.makedirs(profile_dir, exist_ok=True)
    args = [
        settings.chromium_path,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",  # 小内存机器稳定性
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--lang=zh-CN",
        "--window-size=1440,900",
    ]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _cdp_ready(port: int, timeout_s: float = 22.0) -> bool:
    """轮询 /json/version 直到 Chrome 调试端口就绪。本机直连（绕开 HTTP_PROXY）。

    snap chromium 冷启动（首次解压/挂载）可能 10s+，超时给足。
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=3) as resp:
                if resp.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    return False


class _Instance:
    __slots__ = ("user_id", "port", "profile_dir", "proc", "busy", "starting", "last_used")

    def __init__(self, user_id: str, port: int, profile_dir: str):
        self.user_id = user_id
        self.port = port
        self.profile_dir = profile_dir
        self.proc = None
        self.busy = False
        self.starting = True
        self.last_used = time.monotonic()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


class BrowserPool:
    def __init__(self, *, max_size=None, port_start=None, profile_base=None,
                 idle_timeout_s=None, acquire_timeout_s=None,
                 launch=_default_launch, is_alive=_default_is_alive, ready=_cdp_ready):
        self.max_size = max_size if max_size is not None else settings.browser_pool_max
        self.port_start = port_start if port_start is not None else settings.browser_pool_port_start
        self.profile_base = profile_base or settings.browser_profile_base
        self.idle_timeout_s = idle_timeout_s if idle_timeout_s is not None else settings.browser_idle_timeout_s
        self.acquire_timeout_s = (
            acquire_timeout_s if acquire_timeout_s is not None else settings.browser_acquire_timeout_s
        )
        self._launch = launch
        self._is_alive = is_alive
        self._ready = ready
        self._insts: dict[str, _Instance] = {}
        self._cond = threading.Condition()
        self._reaper_started = False

    # ---------- 内部（持锁）----------

    def _alive_insts(self) -> list[_Instance]:
        return [i for i in self._insts.values() if i.starting or self._is_alive(i.proc)]

    def _free_port(self) -> int:
        used = {i.port for i in self._insts.values()}
        for port in range(self.port_start, self.port_start + max(8, self.max_size * 4)):
            if port in used:
                continue
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", port)) != 0:  # 未被占用
                    return port
        raise BrowserAcquireTimeout("无空闲调试端口")

    def _kill(self, inst: _Instance) -> None:
        self._insts.pop(inst.user_id, None)
        if inst.proc is not None:
            try:
                inst.proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        logger.info("browser pool: killed instance user=%s port=%s", inst.user_id, inst.port)

    def _lru_idle_victim(self, alive: list[_Instance]) -> _Instance | None:
        idle = [i for i in alive if not i.busy and not i.starting]
        return min(idle, key=lambda i: i.last_used) if idle else None

    def _queue_position(self, user_id: str) -> int:
        return sum(1 for i in self._insts.values() if i.busy and i.user_id != user_id)

    # ---------- 公开 API ----------

    def acquire(self, user_id: str, on_wait=None, cancel_check=None) -> str:
        """确保 user_id 有一个存活空闲的 Chrome，标记 busy 并返回其 browser_url。

        池满且都 busy 时阻塞排队（首次等待回调 on_wait(position)），超时抛 BrowserAcquireTimeout。
        cancel_check：可选同步回调，排队等待期间周期性调用（2026-08-13）——用户点停止时
        抛异常让 acquire 立即中止（异常会随锁释放向上传播），否则排队最长要等
        browser_acquire_timeout_s（120s）且期间停止按钮无效。
        """
        self._ensure_reaper()
        deadline = time.monotonic() + self.acquire_timeout_s
        notified = False
        with self._cond:
            while True:
                if cancel_check is not None:
                    cancel_check()  # 每轮循环（含唤醒后）检查停止
                inst = self._insts.get(user_id)
                if inst is not None:
                    if inst.starting or inst.busy:  # 同用户另一轮次在用/在启动 → 等
                        notified = self._wait_or_timeout(user_id, deadline, on_wait, notified)
                        continue
                    if self._is_alive(inst.proc):
                        inst.busy = True
                        inst.last_used = time.monotonic()
                        return inst.url
                    self._insts.pop(user_id, None)  # 进程已死，重建
                    continue
                # 该用户尚无实例 → 需要一个存活槽位
                alive = self._alive_insts()
                if len(alive) >= self.max_size:
                    victim = self._lru_idle_victim(alive)
                    if victim is None:  # 都 busy，等别人释放
                        notified = self._wait_or_timeout(user_id, deadline, on_wait, notified)
                        continue
                    self._kill(victim)
                # 占位：先在锁内登记（reserve 槽 + 端口），spawn 在锁外做
                port = self._free_port()
                inst = _Instance(user_id, port, os.path.join(self.profile_base, user_id))
                inst.busy = True
                self._insts[user_id] = inst
                break  # 出锁去 spawn

        # 锁外拉起（慢操作不占锁），失败则回滚
        try:
            proc = self._launch(inst.port, inst.profile_dir)
            if not self._ready(inst.port):
                raise RuntimeError(f"chrome :{inst.port} 未就绪")
        except Exception:
            with self._cond:
                self._insts.pop(user_id, None)
                self._cond.notify_all()
            raise
        with self._cond:
            inst.proc = proc
            inst.starting = False
            inst.last_used = time.monotonic()
            self._cond.notify_all()
        logger.info("browser pool: spawned user=%s port=%s", user_id, inst.port)
        return inst.url

    def _wait_or_timeout(self, user_id, deadline, on_wait, notified) -> bool:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BrowserAcquireTimeout("排队等待浏览器超时")
        if on_wait and not notified:  # 首次等待：另起线程写「排队中」提示，不占池锁
            pos = self._queue_position(user_id)
            threading.Thread(target=_safe_call, args=(on_wait, pos), daemon=True).start()
            notified = True
        self._cond.wait(min(remaining, 5.0))
        return notified

    def release(self, user_id: str) -> None:
        with self._cond:
            inst = self._insts.get(user_id)
            if inst is not None:
                inst.busy = False
                inst.last_used = time.monotonic()
            self._cond.notify_all()

    def restart(self, user_id: str) -> None:
        """杀掉某用户实例（自愈用），下次 acquire 重拉。"""
        with self._cond:
            inst = self._insts.get(user_id)
            if inst is not None:
                self._kill(inst)
            self._cond.notify_all()

    def reap_idle(self) -> int:
        """回收空闲超时且非 busy 的实例，返回回收数。"""
        killed = 0
        now = time.monotonic()
        with self._cond:
            for inst in list(self._insts.values()):
                if not inst.busy and not inst.starting and now - inst.last_used > self.idle_timeout_s:
                    self._kill(inst)
                    killed += 1
            if killed:
                self._cond.notify_all()
        return killed

    def _ensure_reaper(self) -> None:
        if self._reaper_started:
            return
        self._reaper_started = True
        threading.Thread(target=self._reaper_loop, daemon=True).start()

    def _reaper_loop(self) -> None:
        while True:
            time.sleep(60)
            try:
                self.reap_idle()
            except Exception:  # noqa: BLE001
                logger.warning("browser pool reaper error", exc_info=True)


def _safe_call(fn, *a) -> None:
    try:
        fn(*a)
    except Exception:  # noqa: BLE001
        logger.warning("browser pool on_wait callback failed", exc_info=True)


_pool: BrowserPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> BrowserPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = BrowserPool()
        return _pool


def cleanup_orphans() -> None:
    """启动清理：杀掉端口段内残留的 chromium（上次崩溃遗留，profile 会被锁）。"""
    start = settings.browser_pool_port_start
    for port in range(start, start + max(8, settings.browser_pool_max * 4)):
        try:
            subprocess.run(["pkill", "-f", f"remote-debugging-port={port}"], timeout=10)
        except Exception:  # noqa: BLE001
            pass
