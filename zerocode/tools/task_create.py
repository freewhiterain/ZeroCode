"""共享任务创建工具模块。

本模块实现 TaskCreate 工具，用于向团队任务看板新增任务。
工具会记录标题、描述、负责人、依赖关系和创建者信息，并将任务存储
分配的 ID、状态和负责人摘要返回给调用方。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from zerocode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from zerocode.teams.manager import TeamManager


# 任务创建入参：支持基础信息、负责人以及双向依赖字段。
class TaskCreateParams(BaseModel):
    title: str
    description: str = ""
    assignee: str = ""
    blocks: list[str] | None = None
    blocked_by: list[str] | None = None


# 【讲解】TaskCreate/TaskGet/TaskList/TaskUpdate 四个文件是同一套"团队任务
# 看板"的增删改查工具（类似一个迷你 Jira），共用 team_manager.get_task_store()
# 拿到的 SharedTaskStore（实现见 teams/shared_task.py，JSON 文件持久化）。
# 团队里的多个 agent 靠这个共享看板协调"谁在做什么、谁在等谁"，而不是
# 只靠 SendMessage 互相口头通知。四个文件结构几乎一样：校验参数 → 调用
# store 对应方法 → 把结果格式化成给模型看的文本。读懂这一个就懂了另外三个。
class TaskCreateTool(Tool):
    name = "TaskCreate"
    description = (
        "Create a shared task in the team's task board. "
        "Supports dependency tracking with blocks/blocked_by fields."
    )
    params_model = TaskCreateParams
    category = "command"
    is_concurrency_safe = True


    def __init__(self, team_manager: TeamManager, team_name: str, agent_name: str = "") -> None:
        self._team_manager = team_manager
        self._team_name = team_name
        self._agent_name = agent_name


    async def execute(self, params: BaseModel) -> ToolResult:
        p: TaskCreateParams = params  # type: ignore[assignment]

        store = self._team_manager.get_task_store(self._team_name)
        if store is None:
            return ToolResult(output=f"Task store not found for team '{self._team_name}'", is_error=True)

        task = store.create(
            title=p.title,
            description=p.description,
            assignee=p.assignee,
            blocks=p.blocks,
            blocked_by=p.blocked_by,
            created_by=self._agent_name,
        )

        return ToolResult(
            output=(
                f"Task created:\n"
                f"  ID: {task.id}\n"
                f"  Title: {task.title}\n"
                f"  Status: {task.status}\n"
                f"  Assignee: {task.assignee or '(unassigned)'}"
            )
        )
