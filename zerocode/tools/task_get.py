"""共享任务详情工具模块。

本模块实现 TaskGet 工具，用于根据任务 ID 获取团队任务的完整详情。
返回内容覆盖标题、状态、负责人、创建者、描述以及阻塞/被阻塞依赖，
适合在多 Agent 协作中查看单个任务的上下文。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from zerocode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from zerocode.teams.manager import TeamManager


# 详情查询入参：通过任务 ID 定位团队任务看板中的单个任务。
class TaskGetParams(BaseModel):
    task_id: str


class TaskGetTool(Tool):
    name = "TaskGet"
    description = "Get details of a shared task by ID, including dependency information."
    params_model = TaskGetParams
    category = "read"
    is_concurrency_safe = True


    def __init__(self, team_manager: TeamManager, team_name: str) -> None:
        self._team_manager = team_manager
        self._team_name = team_name


    async def execute(self, params: BaseModel) -> ToolResult:
        p: TaskGetParams = params  # type: ignore[assignment]

        store = self._team_manager.get_task_store(self._team_name)
        if store is None:
            return ToolResult(output=f"Task store not found for team '{self._team_name}'", is_error=True)

        task = store.get(p.task_id)
        if task is None:
            return ToolResult(output=f"Task '{p.task_id}' not found", is_error=True)

        lines = [
            f"Task {task.id}:",
            f"  Title:      {task.title}",
            f"  Status:     {task.status}",
            f"  Assignee:   {task.assignee or '(unassigned)'}",
            f"  Created by: {task.created_by or '(unknown)'}",
        ]
        if task.description:
            lines.append(f"  Description: {task.description}")
        if task.blocks:
            lines.append(f"  Blocks:     {', '.join(task.blocks)}")
        if task.blocked_by:
            lines.append(f"  Blocked by: {', '.join(task.blocked_by)}")

        return ToolResult(output="\n".join(lines))
