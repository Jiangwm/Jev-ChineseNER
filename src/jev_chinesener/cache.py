"""纯内存响应缓存与本地准入计数；不记录原文，不提供磁盘持久化。"""

import hashlib
import json
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from threading import Lock

from .config import Settings
from .models import SegmentRequest, SegmentResponse


def fingerprint(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def response_key(request: SegmentRequest, settings: Settings, versions: dict, backend: str) -> str:
    # 保留显式 null/空串及所有请求、配置字段，新增字段也不会默默漏出缓存边界。
    return fingerprint(
        {
            "schema": "response-cache-v1",
            "request": request.model_dump(mode="json"),
            "settings": settings.model_dump(mode="json"),
            "versions": versions,
            "backend": backend,
        }
    )


class ResponseCache:
    def __init__(
        self, max_entries: int, ttl_seconds: float, clock: Callable[[], float] = time.monotonic
    ):
        if max_entries < 1 or not 0 < ttl_seconds < float("inf"):
            raise ValueError("invalid_cache_policy")
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._entries: OrderedDict[str, tuple[float, SegmentResponse]] = OrderedDict()
        self._lock = Lock()
        self._hits = self._misses = self._evictions = self._expirations = 0

    def _expire(self, now: float):
        for key, (deadline, _) in list(self._entries.items()):
            if deadline <= now:
                del self._entries[key]
                self._expirations += 1

    def get(self, key: str) -> SegmentResponse | None:
        with self._lock:
            self._expire(self.clock())
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return entry[1].model_copy(deep=True)

    def put(self, key: str, response: SegmentResponse):
        with self._lock:
            now = self.clock()
            self._expire(now)
            self._entries[key] = (now + self.ttl_seconds, response.model_copy(deep=True))
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
                self._evictions += 1

    def stats(self) -> dict[str, int]:
        with self._lock:
            self._expire(self.clock())
            return {
                "hits": self._hits,
                "misses": self._misses,
                "entries": len(self._entries),
                "evictions": self._evictions,
                "expirations": self._expirations,
            }


class LocalLimitError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ProcessLimits:
    """按入站请求计数（含缓存命中），不是 token 估价或计费上限。"""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self._lock = Lock()
        self._windows: dict[float, deque[float]] = {}
        self._accepted = self._rejected = 0

    def admit(self, settings: Settings):
        if not settings.rate_limit_requests and not settings.request_budget:
            return
        with self._lock:
            now = self.clock()
            window = self._windows.setdefault(settings.rate_limit_window_seconds, deque())
            # 各窗口独立保存时间戳，避免不同配置实例相互裁剪窗口。
            for seconds, timestamps in self._windows.items():
                while timestamps and timestamps[0] <= now - seconds:
                    timestamps.popleft()
            code = None
            if settings.request_budget and self._accepted >= settings.request_budget:
                code = "request_budget_exhausted"
            elif settings.rate_limit_requests and len(window) >= settings.rate_limit_requests:
                code = "rate_limit_exceeded"
            if code:
                self._rejected += 1
                raise LocalLimitError(code)
            self._accepted += 1
            for timestamps in self._windows.values():
                timestamps.append(now)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"accepted": self._accepted, "rejected": self._rejected}


# 默认同一进程内共享准入计数；测试可注入独立计数器，不跨 worker/进程协调。
PROCESS_LIMITS = ProcessLimits()
