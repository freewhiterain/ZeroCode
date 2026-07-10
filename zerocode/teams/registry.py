from __future__ import annotations

import threading


# 【讲解】"单例"（Singleton）模式：整个进程只有一份 AgentNameRegistry 实例，
# 通过 instance() 拿到，而不是像别的类那样每次 new 一个。用途是给
# SendMessage 这类工具一个全局的"名字 -> agent_id"查找表——队友互相发消息
# 时用人类可读的名字（"reviewer"），底层要转换成内部的 agent_id。双重
# check 锁（`if cls._instance is None` 判断两次）是并发安全创建单例的经典
# 写法：避免多个协程同时看到 None 都去创建一次。
class AgentNameRegistry:
    """线程安全初始化的单例名称注册表。"""
    _instance: AgentNameRegistry | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._names: dict[str, str] = {}  # name -> agent_id


    @classmethod
    def instance(cls) -> AgentNameRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance


    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._instance = None


    def register(self, name: str, agent_id: str) -> None:
        self._names[name] = agent_id

    def resolve(self, name_or_id: str) -> str | None:
        if name_or_id in self._names:
            return self._names[name_or_id]
        if name_or_id in self._names.values():
            return name_or_id
        return None

    def unregister(self, name: str) -> None:
        self._names.pop(name, None)


    def list_all(self) -> dict[str, str]:
        return dict(self._names)
