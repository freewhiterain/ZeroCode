"""用户提问工具模块。

本模块实现 AskUserQuestion 系统工具，用于在代码和上下文无法确定答案时
向用户发起结构化问题。工具会创建待处理事件并等待外部界面回填答案，
最后将问题名称与回答整理为文本结果。
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from zerocode.tools.base import Tool, ToolResult


# 单个问题的结构定义，供前端按类型渲染输入控件。
class QuestionItem(BaseModel):
    type: str = Field(description="Question type: text, radio, select, checkbox")
    name: str = Field(description="Question identifier")
    message: str = Field(description="Question text to display")
    options: list[str] = Field(
        default_factory=list,
        description="Options for radio/select/checkbox types",
    )


class AskUserParams(BaseModel):
    questions: list[QuestionItem] = Field(
        description="List of questions to ask the user"
    )


class AskUserEvent:


    def __init__(
        self,
        questions: list[dict[str, Any]],
        future: asyncio.Future[dict[str, str]],
    ) -> None:
        self.questions = questions
        self.future = future


# 【讲解】和 agent.py 里 PermissionRequest 用的是同一套"Future 暂停/唤醒"手法：
# execute() 创建一个 asyncio.Future 存进 self._pending_event，然后 await 它。
# UI 层拿到 _pending_event 后渲染问题界面，用户作答后调用
# future.set_result(答案)，这里的 await 就返回了。300 秒没人回答就超时退出，
# 避免 Agent 无限期挂起。should_defer = True 让它作为"延迟工具"按需加载。
class AskUserTool(Tool):
    name = "AskUserQuestion"
    description = (
        "Ask the user one or more questions when you need information "
        "that cannot be determined from code or context alone. Supports "
        "text input, radio (single select), select, and checkbox (multi select) "
        "question types."
    )
    params_model = AskUserParams
    category: str = "read"
    is_system_tool = True
    should_defer = True


    def __init__(self) -> None:
        self._pending_event: AskUserEvent | None = None

    async def execute(self, params: AskUserParams) -> ToolResult:
        questions_data = [q.model_dump() for q in params.questions]

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, str]] = loop.create_future()

        self._pending_event = AskUserEvent(questions=questions_data, future=future)

        try:
            answers = await asyncio.wait_for(future, timeout=300)
        except asyncio.TimeoutError:
            return ToolResult(
                output="User did not respond within 5 minutes", is_error=True
            )
        finally:
            self._pending_event = None

        lines = []
        for q in params.questions:
            answer = answers.get(q.name, "(no answer)")
            lines.append(f"{q.name}: {answer}")

        return ToolResult(output="\n".join(lines))
