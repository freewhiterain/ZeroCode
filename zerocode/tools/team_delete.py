"""团队删除工具模块。

本模块实现 TeamDelete 工具，用于删除已有 Agent 团队并清理相关资源。
执行过程委托 TeamManager 完成终止成员、移除工作区和清理邮箱等操作，
并在协调模式下恢复父 Agent 的完整工具注册表。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from zerocode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from zerocode.agent import Agent
    from zerocode.teams.manager import TeamManager


# 删除团队只需要团队名称，实际清理细节由 TeamManager 封装。
class TeamDeleteParams(BaseModel):
    team_name: str


# 团队删除工具：清理团队资源，并在需要时退出父 Agent 的协调模式。
class TeamDeleteTool(Tool):
    name = "TeamDelete"
    description = (
        "Delete an Agent Team. Terminates all pane processes, removes worktrees, "
        "cleans up mailbox and team directory. Requires all members to be idle."
    )
    params_model = TeamDeleteParams
    category = "command"
    is_concurrency_safe = False


    def __init__(self, team_manager: TeamManager, parent_agent: Agent | None = None) -> None:
        self._team_manager = team_manager
        self._parent_agent = parent_agent


    async def execute(self, params: BaseModel) -> ToolResult:
        p: TeamDeleteParams = params  # type: ignore[assignment]

        from zerocode.teams.manager import TeamError

        try:
            self._team_manager.delete_team(p.team_name)
        except TeamError as e:
            return ToolResult(output=str(e), is_error=True)
        except Exception as e:
            return ToolResult(output=f"Failed to delete team: {e}", is_error=True)

        coordinator_note = ""
        if self._parent_agent and self._parent_agent.coordinator_mode:
            full_registry = getattr(self._parent_agent, '_full_registry', None)
            if full_registry is not None:
                self._parent_agent.registry = full_registry
                self._parent_agent._full_registry = None
            self._parent_agent.coordinator_mode = False
            coordinator_note = "\nCoordinator Mode deactivated: full tools restored."

        return ToolResult(output=f"Team '{p.team_name}' deleted successfully.{coordinator_note}")
