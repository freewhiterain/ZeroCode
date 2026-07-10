"""工具注册表与默认工具装配模块。

本模块维护运行时可用工具集合，负责工具注册、启停、延迟工具发现、
按协议输出 schema，以及创建默认的文件读写、编辑、命令和搜索工具。
注册表是 Agent 与各工具实例之间的统一入口。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from zerocode.tools.base import Tool

if TYPE_CHECKING:
    from zerocode.cache import FileCache


# 工具注册表：集中管理工具实例、禁用状态和延迟工具的发现状态。
# 【讲解】ToolRegistry 是"所有工具的花名册"——Agent 不直接持有工具对象，
# 而是通过它按名字查工具、判断是否启用、生成要发给模型的 schema 列表。
# 内部只是三个简单的字典/集合，没有什么魔法：
#   _tools      — name -> Tool 实例
#   _disabled   — 被临时禁用的工具名（比如某些模式下砍掉写权限工具）
#   _discovered — "延迟工具"里，模型已经通过 ToolSearch 主动加载过 schema 的
# 延迟工具（should_defer=True）机制：启动时只把工具名字告诉模型（省 token），
# 模型需要时调用 ToolSearch 按需加载完整 schema，加载后记入 _discovered，
# 之后 get_all_schemas() 才会把它塞进正式的工具列表里。
class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._disabled: set[str] = set()
        self._discovered: set[str] = set()

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)


    def is_enabled(self, name: str) -> bool:
        return name in self._tools and name not in self._disabled

    def enable(self, name: str) -> None:
        self._disabled.discard(name)


    def disable(self, name: str) -> None:
        if name in self._tools:
            self._disabled.add(name)

    def enable_all(self) -> None:
        self._disabled.clear()


    def mark_discovered(self, name: str) -> None:
        self._discovered.add(name)

    def is_discovered(self, name: str) -> bool:
        return name in self._discovered


    def get_deferred_tool_names(self) -> list[str]:
        return [
            name
            for name, tool in self._tools.items()
            if getattr(tool, "should_defer", False)
            and name not in self._discovered
            and name not in self._disabled
        ]

    def search_deferred(
        self, query: str, max_results: int, protocol: str = "anthropic"
    ) -> list[dict[str, Any]]:
        query_lower = query.lower()
        scored: list[tuple[int, str, Tool]] = []
        for name, tool in self._tools.items():
            if not getattr(tool, "should_defer", False):
                continue
            if name in self._disabled:
                continue
            score = 0
            name_lower = name.lower()
            desc_lower = (tool.description or "").lower()
            if query_lower in name_lower:
                score += 10
            if query_lower in desc_lower:
                score += 5
            for word in query_lower.split():
                if word in name_lower:
                    score += 3
                if word in desc_lower:
                    score += 1
            if score > 0:
                scored.append((score, name, tool))
        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[dict[str, Any]] = []
        for _, _name, tool in scored[:max_results]:
            base = tool.get_schema()
            if protocol in ("openai", "openai-compat"):
                results.append({
                    "type": "function",
                    "name": base["name"],
                    "description": base["description"],
                    "parameters": base["input_schema"],
                })
            else:
                results.append(base)
        return results

    def find_deferred_by_names(
        self, names: list[str], protocol: str = "anthropic"
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for name in names:
            tool = self._tools.get(name)
            if tool is None:
                continue
            if not getattr(tool, "should_defer", False):
                continue
            base = tool.get_schema()
            if protocol in ("openai", "openai-compat"):
                results.append({
                    "type": "function",
                    "name": base["name"],
                    "description": base["description"],
                    "parameters": base["input_schema"],
                })
            else:
                results.append(base)
        return results

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())


    def get_all_schemas(self, protocol: str = "anthropic") -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for name, tool in self._tools.items():
            if name in self._disabled:
                continue
            if getattr(tool, "should_defer", False) and name not in self._discovered:
                continue
            base = tool.get_schema()
            if protocol in ("openai", "openai-compat"):
                schemas.append({
                    "type": "function",
                    "name": base["name"],
                    "description": base["description"],
                    "parameters": base["input_schema"],
                })
            else:
                schemas.append(base)
        return schemas


# 【讲解】组装函数：把几个最基础的文件/命令工具实例化并注册成一个默认
# 注册表——注意这里只注册了 6 个"核心"工具，AgentTool、TeamCreate 等更
# "重"的工具是在 __main__.py / app.py 里按需追加注册的（因为它们需要
# 更多上下文，比如 parent_agent、team_manager）。三个文件类工具共享同一个
# FileStateCache 实例，这样"先读后写"的保护才能在读写工具之间生效。
def create_default_registry(file_cache: FileCache | None = None, file_history: Any = None) -> ToolRegistry:
    from zerocode.tools.bash import Bash
    from zerocode.tools.edit_file import EditFile
    from zerocode.tools.file_state_cache import FileStateCache
    from zerocode.tools.glob import Glob
    from zerocode.tools.grep import Grep
    from zerocode.tools.read_file import ReadFile
    from zerocode.tools.write_file import WriteFile

    file_state_cache = FileStateCache()

    registry = ToolRegistry()
    registry.register(ReadFile(file_cache=file_cache, file_state_cache=file_state_cache))
    registry.register(WriteFile(file_cache=file_cache, file_history=file_history, file_state_cache=file_state_cache))
    registry.register(EditFile(file_cache=file_cache, file_history=file_history, file_state_cache=file_state_cache))
    registry.register(Bash())
    registry.register(Glob())
    registry.register(Grep())
    return registry
