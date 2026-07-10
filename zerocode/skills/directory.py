"""目录型 Skill 的自定义工具注册支持。

读取 skill 目录中的 tool.json，动态加载 references 下同名 Python 实现，
并把这些实现包装成统一的 Tool 注册到工具注册表中。
"""
from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from zerocode.tools import ToolRegistry
from zerocode.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


def parse_tool_json(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Failed to parse tool.json at %s: %s", path, e)
        return []

    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        log.warning("tool.json at %s must be a JSON array or object", path)
        return []

    return raw


# 【讲解】这是全项目最"动态"的一段代码：目录型 skill 的 tool.json 声明了
# 工具名和参数 schema，真正的执行逻辑是 references/<工具名>.py 文件里的
# 一个 `execute` 函数——但这个文件在启动时并不存在于任何 import 语句里，
# 而是运行期用 importlib.util 动态把它当模块加载进来（Python 的"运行时
# 反射式导入"，类似 JS 的 `import()`）。这样每个 skill 就能带上自己专属
# 的、内置代码库里压根不知道的自定义工具。加载失败（脚本缺失、
# 没有 execute 函数）都只记警告不崩溃，保证一个坏 skill 不会拖垮整个启动。
def load_tool_implementation(
    references_dir: Path, tool_name: str
) -> Callable[..., Any] | None:
    script = references_dir / f"{tool_name}.py"
    if not script.is_file():
        return None

    module_name = f"ZeroCode_skill_tool_{tool_name}"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        log.warning("Cannot create module spec for %s", script)
        return None

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        log.warning("Failed to load tool implementation %s: %s", script, e)
        return None

    execute_fn = getattr(module, "execute", None)
    if execute_fn is None:
        log.warning("Tool implementation %s has no 'execute' function", script)
        return None

    return execute_fn


class _DynamicParams(BaseModel):
    model_config = {"extra": "allow"}


# 【讲解】SkillCustomTool 是给"动态加载的 Python 函数"套上标准 Tool 外壳的
# 适配器——因为 Agent 主循环只认识 Tool 接口（execute(params) -> ToolResult），
# 不管这个工具背后是内置类还是 skill 目录里临时加载出来的函数。
# _DynamicParams 用 `model_config = {"extra": "allow"}` 关掉了 pydantic 的
# 严格字段校验，因为参数结构由 tool.json 里的 schema 动态决定，Python 端
# 没法提前定义固定字段。
class SkillCustomTool(Tool):


    def __init__(
        self,
        tool_name: str,
        description: str,
        schema: dict[str, Any],
        impl: Callable[..., Any] | None,
    ) -> None:
        self.name = tool_name
        self.description = description
        self.params_model = _DynamicParams
        self.category = "command"
        self.is_concurrency_safe = False
        self._schema = schema
        self._impl = impl


    def get_schema(self) -> dict[str, Any]:
        input_schema = self._schema.get("parameters", self._schema.get("input_schema", {}))
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": input_schema,
        }


    async def execute(self, params: BaseModel) -> ToolResult:
        if self._impl is None:
            return ToolResult(
                output=f"Error: no implementation found for tool '{self.name}'",
                is_error=True,
            )
        try:
            kwargs = params.model_dump()
            import asyncio
            if asyncio.iscoroutinefunction(self._impl):
                result = await self._impl(**kwargs)
            else:
                result = self._impl(**kwargs)
            return ToolResult(output=str(result))
        except Exception as e:
            return ToolResult(output=f"Tool execution error: {e}", is_error=True)


def register_skill_tools(skill_dir: Path, registry: ToolRegistry) -> int:
    tool_json_path = skill_dir / "tool.json"
    if not tool_json_path.is_file():
        return 0

    schemas = parse_tool_json(tool_json_path)
    references_dir = skill_dir / "references"
    count = 0

    for schema in schemas:
        tool_name = schema.get("name", "")
        if not tool_name:
            log.warning("Skipping tool with no name in %s", tool_json_path)
            continue

        if registry.get(tool_name) is not None:
            log.debug("Tool '%s' already registered, skipping", tool_name)
            continue

        description = schema.get("description", "")
        impl = load_tool_implementation(references_dir, tool_name) if references_dir.is_dir() else None

        if impl is None:
            log.warning("No implementation for tool '%s' in %s", tool_name, references_dir)

        tool = SkillCustomTool(tool_name, description, schema, impl)
        registry.register(tool)
        count += 1

    return count
