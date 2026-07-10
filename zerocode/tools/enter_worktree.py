"""进入隔离工作区工具模块。

本模块实现 EnterWorktree 工具，用于基于 git 创建隔离 worktree 并将
当前会话切换进去。工具会生成或校验工作区名称，防止非法路径片段，
并返回后续退出工作区的操作提示。
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from zerocode.tools.base import Tool, ToolResult
from zerocode.worktree.slug import validate_slug

if TYPE_CHECKING:
    from zerocode.worktree.manager import WorktreeManager


# 进入工作区入参：可选名称为空时会自动生成随机安全名称。
class EnterWorktreeParams(BaseModel):
    name: Optional[str] = Field(
        default=None,
        description=(
            'Optional name for the worktree. Each "/"-separated segment may '
            "contain only letters, digits, dots, underscores, and dashes; "
            "max 64 chars total. A random name is generated if not provided."
        ),
    )


class EnterWorktreeTool(Tool):
    name = "EnterWorktree"
    description = (
        "Creates an isolated worktree (via git) and switches the session into it"
    )
    params_model = EnterWorktreeParams
    category = "command"
    should_defer = True


    def __init__(self, worktree_manager: WorktreeManager) -> None:
        self._manager = worktree_manager


    # 【讲解】"worktree"是 git 的一个功能：可以从同一仓库检出多个独立的
    # 工作目录（各自可以在不同分支上），不用来回 checkout 主目录、不怕
    # 冲突或者互相污染。这个工具让 agent 能"钻进"一个隔离的临时目录里
    # 干活（比如尝试一个有风险的重构），完事后用 ExitWorktree 决定保留
    # 还是丢弃，主项目目录全程不受影响。
    async def execute(self, params: EnterWorktreeParams) -> ToolResult:
        if self._manager.get_current_session() is not None:
            return ToolResult(
                output="Already in a worktree session", is_error=True
            )

        slug = params.name or f"wt-{secrets.token_hex(4)}"

        err = validate_slug(slug)
        if err:
            return ToolResult(output=f"Invalid worktree name: {err}", is_error=True)

        try:
            wt = await self._manager.create(slug)
            session = await self._manager.enter(slug)
        except Exception as e:
            return ToolResult(
                output=f"Error creating worktree: {e}", is_error=True
            )

        branch_info = f" on branch {wt.branch}" if wt.branch else ""
        return ToolResult(
            output=(
                f"Created worktree at {session.worktree_path}{branch_info}. "
                "The session is now working in the worktree. "
                "Use ExitWorktree to leave mid-session, or exit the session to be prompted."
            )
        )
