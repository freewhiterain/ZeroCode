"""退出隔离工作区工具模块。

本模块实现 ExitWorktree 工具，用于离开由 EnterWorktree 创建的当前
工作区会话。删除工作区前会检查未提交文件和新增提交，避免在未确认
discard_changes 的情况下永久丢弃用户工作。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from zerocode.tools.base import Tool, ToolResult
from zerocode.worktree.changes import count_worktree_changes

if TYPE_CHECKING:
    from zerocode.worktree.manager import WorktreeManager


# 退出工作区入参：action 决定保留还是删除，discard_changes 用于显式确认丢弃。
class ExitWorktreeParams(BaseModel):
    action: str = Field(
        description='"keep" leaves the worktree and branch on disk; "remove" deletes both.',
    )
    discard_changes: Optional[bool] = Field(
        default=None,
        description=(
            'Required true when action is "remove" and the worktree has '
            "uncommitted files or unmerged commits. "
            "The tool will refuse and list them otherwise."
        ),
    )


class ExitWorktreeTool(Tool):
    name = "ExitWorktree"
    description = (
        "Exits a worktree session created by EnterWorktree and restores "
        "the original working directory"
    )
    params_model = ExitWorktreeParams
    category = "command"
    should_defer = True


    def __init__(self, worktree_manager: WorktreeManager) -> None:
        self._manager = worktree_manager


    async def execute(self, params: ExitWorktreeParams) -> ToolResult:
        session = self._manager.get_current_session()
        if session is None:
            return ToolResult(
                output=(
                    "No-op: there is no active EnterWorktree session to exit. "
                    "This tool only operates on worktrees created by EnterWorktree "
                    "in the current session — it will not touch worktrees created "
                    "manually or in a previous session. No filesystem changes were made."
                ),
                is_error=True,
            )

        action = params.action
        if action not in ("keep", "remove"):
            return ToolResult(
                output=f'Invalid action "{action}". Must be "keep" or "remove".',
                is_error=True,
            )

        discard = params.discard_changes or False

        # 【讲解】安全阀：删除 worktree 前先检查有没有"没提交的文件"或"没合并
        # 的提交"。如果有，且调用方没有显式传 discard_changes=true，就拒绝
        # 执行并把变更列出来——逼模型（进而逼用户）明确知情后再确认丢弃，
        # 防止一次 agent 的误操作悄悄抹掉一堆工作成果。
        if action == "remove" and not discard:
            changes = count_worktree_changes(
                session.worktree_path, session.original_head_commit
            )
            if changes.uncommitted > 0 or changes.new_commits > 0:
                parts = []
                if changes.uncommitted > 0:
                    word = "file" if changes.uncommitted == 1 else "files"
                    parts.append(f"{changes.uncommitted} uncommitted {word}")
                if changes.new_commits > 0:
                    word = "commit" if changes.new_commits == 1 else "commits"
                    parts.append(f"{changes.new_commits} {word}")
                return ToolResult(
                    output=(
                        f"Worktree has {' and '.join(parts)}. "
                        "Removing will discard this work permanently. "
                        "Confirm with the user, then re-invoke with "
                        'discard_changes: true — or use action: "keep" '
                        "to preserve the worktree."
                    ),
                    is_error=True,
                )

        worktree_path = session.worktree_path
        original_cwd = session.original_cwd
        wt_name = session.worktree_name

        try:
            await self._manager.exit(wt_name, action=action, discard_changes=discard)
        except Exception as e:
            return ToolResult(
                output=f"Error exiting worktree: {e}", is_error=True
            )

        if action == "keep":
            return ToolResult(
                output=(
                    f"Exited worktree. Your work is preserved at {worktree_path}. "
                    f"Session is now back in {original_cwd}."
                )
            )

        return ToolResult(
            output=(
                f"Exited and removed worktree at {worktree_path}. "
                f"Session is now back in {original_cwd}."
            )
        )
