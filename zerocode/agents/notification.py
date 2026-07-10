"""后台任务完成通知的格式化与注入。"""
# 【讲解】小工具模块：把 task_manager.py 里的 BackgroundTask 对象翻译成一段
# 人类/模型都能读的文本块（<task-notification>...），再用
# conversation.add_user_message 塞进对话——这样父 agent 下一轮请求就能
# "看到"后台任务的结果，就像收到一条系统消息一样。
from __future__ import annotations

from typing import TYPE_CHECKING

from zerocode.conversation import ConversationManager

if TYPE_CHECKING:
    from zerocode.agents.task_manager import BackgroundTask

MAX_NOTIFICATION_RESULT_LENGTH = 5000


def format_task_notification(task: BackgroundTask) -> str:
    result = task.result
    if len(result) > MAX_NOTIFICATION_RESULT_LENGTH:
        result = result[:MAX_NOTIFICATION_RESULT_LENGTH] + "\n... (truncated)"

    elapsed = ""
    if task.end_time is not None:
        secs = task.end_time - task.start_time
        if secs >= 60:
            elapsed = f"{secs / 60:.1f}m"
        else:
            elapsed = f"{secs:.1f}s"


    tokens = ""
    if task.progress.input_tokens or task.progress.output_tokens:
        tokens = (
            f"\nTokens: input={task.progress.input_tokens}, "
            f"output={task.progress.output_tokens}"
        )

    return (
        f"<task-notification>\n"
        f"Task ID: {task.id}\n"
        f"Agent: {task.name}\n"
        f"Status: {task.status}\n"
        f"Elapsed: {elapsed}\n"
        f"{tokens}\n"
        f"Result:\n{result}\n"
        f"</task-notification>"
    )


def inject_task_notifications(
    conversation: ConversationManager,
    completed_tasks: list[BackgroundTask],
) -> None:
    for task in completed_tasks:
        notification = format_task_notification(task)
        conversation.add_user_message(notification)

