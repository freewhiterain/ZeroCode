"""CodeExplore tool: exact symbol source plus bounded call-graph context."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from zerocode.codegraph.formatter import format_query
from zerocode.codegraph.indexer import GraphIndexer
from zerocode.codegraph.store import IndexCorruptError
from zerocode.tools.base import Tool, ToolResult


class CodeExploreParams(BaseModel):
    symbols: list[str] = Field(
        min_length=1,
        max_length=3,
        description="One to three exact function, method, or class names.",
    )
    max_depth: int = Field(
        default=1,
        ge=0,
        le=2,
        description="Call relationship depth: 0 for source only, up to 2.",
    )


class CodeExplore(Tool):
    name = "CodeExplore"
    description = (
        "Read exact Python symbols with their current source and bounded caller/callee "
        "relationships. Requires `/graph init` once per project."
    )
    params_model = CodeExploreParams
    category = "read"
    is_concurrency_safe = False
    should_defer = False

    def __init__(self, root: str | Path = ".") -> None:
        self.indexer = GraphIndexer(root)

    async def execute(self, params: BaseModel) -> ToolResult:
        request = CodeExploreParams.model_validate(params)
        if not self.indexer.exists():
            return ToolResult(
                "Code graph index is missing. Run `/graph init`, then call CodeExplore again."
            )
        try:
            await asyncio.to_thread(self.indexer.refresh)
            store = await asyncio.to_thread(self.indexer.load)
            output = await asyncio.to_thread(
                format_query,
                store,
                self.indexer.root,
                request.symbols,
                request.max_depth,
            )
            return ToolResult(output)
        except IndexCorruptError as exc:
            return ToolResult(f"Code graph index is invalid: {exc}. Run `/graph rebuild`.")
        except Exception as exc:
            return ToolResult(
                f"CodeExplore failed safely: {type(exc).__name__}: {exc}",
                is_error=True,
            )
