"""分布式锁：优先 Redis SET NX（TTL），不可用时降级为进程内锁（开发/测试）。"""
import secrets
import threading
import time
from contextlib import contextmanager

import redis

from .config import get_settings

settings = get_settings()

_local_locks: dict = {}
_local_locks_guard = threading.Lock()


def _get_local_lock(key: str) -> threading.Lock:
    with _local_locks_guard:
        if key not in _local_locks:
            _local_locks[key] = threading.Lock()
        return _local_locks[key]


class _RedisClient:
    """惰性连接 Redis；连接失败时自动降级本地锁。"""

    def __init__(self):
        self._client = None
        self._broken = False

    def _ensure(self):
        if self._client is None and not self._broken and settings.redis_url:
            try:
                self._client = redis.from_url(
                    settings.redis_url, socket_connect_timeout=2, socket_timeout=2
                )
                self._client.ping()
            except Exception:
                self._client = None
                self._broken = True
        return self._client

    def acquire(self, key: str, token: str, ttl: int) -> bool:
        c = self._ensure()
        if c is None:
            return None  # 表示降级为本地锁
        try:
            return bool(c.set(key, token, nx=True, ex=ttl))
        except Exception:
            return None

    def release(self, key: str, token: str) -> None:
        c = self._ensure()
        if c is None:
            return
        try:
            # Lua 脚本保证只有持有者才能释放
            c.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) else return 0 end",
                1,
                key,
                token,
            )
        except Exception:
            pass


_redis_client = _RedisClient()


@contextmanager
def submission_lock(submission_id: int, ttl: int | None = None, wait_timeout: float = 15.0):
    """以 submission_id 为键的应用层分布式锁（SET NX + 校验 token 释放）。"""
    key = f"lock:submission:{submission_id}"
    with _lock(key, ttl or settings.lock_ttl, wait_timeout):
        yield


@contextmanager
def cron_lock(key: str, ttl: int | None = None):
    with _lock(f"cron:{key}", ttl or settings.cron_lock_ttl, wait_timeout=0.1):
        yield


@contextmanager
def _lock(key: str, ttl: int, wait_timeout: float):
    token = secrets.token_hex(16)
    local = _get_local_lock(key)
    acquired_local = False
    deadline = time.time() + wait_timeout
    while True:
        acquired = _redis_client.acquire(key, token, ttl)
        if acquired is True:
            break
        if acquired is None:
            # 无 Redis：使用进程内锁（阻塞式）
            local.acquire()
            acquired_local = True
            break
        if time.time() > deadline:
            raise TimeoutError(f"获取分布式锁超时: {key}")
        time.sleep(0.2)
    try:
        yield
    finally:
        if acquired_local:
            local.release()
        else:
            _redis_client.release(key, token)
