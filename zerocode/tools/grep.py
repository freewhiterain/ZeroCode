"""正则内容搜索工具模块。

本模块实现 Grep 工具，用于在指定目录下按正则表达式搜索文件内容。
搜索时会应用文件名 glob 过滤，并跳过项目中常见的缓存、虚拟环境和
依赖目录，以减少无关结果。
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from zerocode.tools.base import SKIP_DIRS, Tool, ToolResult


# 内容搜索入参：正则表达式必填，路径和文件名过滤可选。
class Params(BaseModel):
    pattern: str = Field(description="Regex pattern to search for")
    path: str = Field(default=".", description="Base directory to search from")
    include: str = Field(default="", description="Glob filter for filenames (e.g. '*.py')")


class Grep(Tool):
    name = "Grep"
    description = "Search file contents using a regex pattern, returning file:line:content matches."
    params_model = Params
    category = "read"
    is_concurrency_safe = True


    async def execute(self, params: Params) -> ToolResult:
        base = Path(params.path)
        if not base.exists():
            return ToolResult(output=f"Error: path not found: {params.path}", is_error=True)

        try:
            regex = re.compile(params.pattern)
        except re.error as e:
            return ToolResult(output=f"Error: invalid regex: {e}", is_error=True)

        glob_pattern = params.include if params.include else "**/*"
        if not glob_pattern.startswith("**/"):
            glob_pattern = "**/" + glob_pattern

        # 【讲解】朴素实现：逐文件读入内存、按行用正则匹配，没有用外部 ripgrep
        # 这类高性能工具。对大仓库会慢，但逻辑简单直观，适合先理解"搜索工具
        # 该返回什么格式"（file:line:content，和 grep -n 的输出习惯一致）。
        results: list[str] = []
        for file_path in sorted(base.glob(glob_pattern)):
            if not file_path.is_file():
                continue
            if any(part in SKIP_DIRS for part in file_path.parts):
                continue
            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue
            for line_num, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    rel = file_path.relative_to(base)
                    results.append(f"{rel}:{line_num}:{line}")

        if not results:
            return ToolResult(output="No matches found.")
        return ToolResult(output="\n".join(results))

