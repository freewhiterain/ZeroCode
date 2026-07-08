"""提供线程安全的内存文件内容缓存。

该模块用于在进程内缓存已读取的文件文本，减少重复磁盘读取。
缓存以文件路径为键，并通过互斥锁保护并发访问。
"""

from __future__ import annotations

import threading


class FileCache:
    """基于路径索引的线程安全字符串缓存。"""
    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, path: str) -> str | None:
        """读取指定路径的缓存内容，不存在时返回 None。"""
        with self._lock:
            return self._store.get(path)


    def put(self, path: str, content: str) -> None:
        with self._lock:
            self._store[path] = content


    def invalidate(self, path: str) -> None:
        with self._lock:
            self._store.pop(path, None)


    def clear(self) -> None:
        with self._lock:
            self._store.clear()


    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
