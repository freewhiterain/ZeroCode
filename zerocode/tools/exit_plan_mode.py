"""退出计划模式工具模块。

本模块实现 ExitPlanMode 工具，用于在计划文件已写好后结束计划模式，
并触发用户审批流程。它只负责校验当前状态和返回退出提示，不执行
后续文件或任务操作。
"""

from __future__ import annotations

from typing import Callable

from pydantic import BaseModel

from zerocode.tools.base import Tool, ToolResult


# 退出计划模式无需参数，状态检查由构造时注入的回调完成。
class ExitPlanModeParams(BaseModel):
    pass


class ExitPlanModeTool(Tool):
    name = "ExitPlanMode"
    description = (
        "Exit plan mode and present the plan for user approval. "
        "Call this when your plan is complete and written to the plan file."
    )
    params_model = ExitPlanModeParams
    category = "read"

    def __init__(
        self,
        is_plan_mode: Callable[[], bool] | None = None,
        plan_exists: Callable[[], bool] | None = None,
    ) -> None:
        self._is_plan_mode = is_plan_mode
        self._plan_exists = plan_exists

    # 【讲解】这个工具很特别：它自己不做任何实质操作，只做状态校验，返回值
    # 其实是"说给模型听的指令"（"不要再调用工具了，结束这一轮"）。真正的
    # "结束计划模式、弹审批框"逻辑在 agent.py 的 run() 里通过检测
    # `tc.tool_name == "ExitPlanMode"` 来触发（搜索 exit_plan_called）。
    async def execute(self, params: ExitPlanModeParams) -> ToolResult:
        if self._is_plan_mode is not None and not self._is_plan_mode():
            return ToolResult(
                output="You are not in plan mode. This tool is only for exiting plan mode after writing a plan.",
                is_error=True,
            )
        if self._plan_exists is not None and not self._plan_exists():
            return ToolResult(
                output="No plan file found. Please write your plan to the plan file before calling ExitPlanMode.",
                is_error=True,
            )
        return ToolResult(
            output=(
                "Plan mode will be exited after this turn. "
                "The user will be shown the plan approval dialog. "
                "Do not call any more tools — end your turn now."
            )
        )
