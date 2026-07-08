"""文件路径匹配工具模块。

本模块实现 Glob 工具，用于按 glob 模式查找文件并返回相对路径。
结果会排除缓存、依赖和版本控制目录，适合快速发现项目中的候选文件。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from zerocode.tools.base import SKIP_DIRS, Tool, ToolResult


# 路径匹配入参：以指定目录为基准解释 glob 模式。
class Params(BaseModel):
    pattern: str = Field(description="Glob pattern to match (e.g. '**/*.py')")
    path: str = Field(default=".", description="Base directory to search from")


class Glob(Tool):
    name = "Glob"
    description = "Find files matching a glob pattern, returning relative paths."
    params_model = Params
    category = "read"
    is_concurrency_safe = True


    async def execute(self, params: Params) -> ToolResult:
        base = Path(params.path)
        if not base.exists():
            return ToolResult(output=f"Error: path not found: {params.path}", is_error=True)

        try:
            matches = sorted(
                str(p.relative_to(base))
                for p in base.glob(params.pattern)
                if p.is_file() and not any(part in SKIP_DIRS for part in p.parts)
            )
        except Exception as e:
            return ToolResult(output=f"Error: {e}", is_error=True)

        if not matches:
            return ToolResult(output="No files matched the pattern.")
        return ToolResult(output="\n".join(matches))

