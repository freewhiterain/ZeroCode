"""团队协作子系统的公共导出入口。

集中暴露团队模型、信箱、任务存储、名称注册表和进度对象，减少调用方对
内部模块布局的依赖。
"""

from zerocode.teams.mailbox import Mailbox, MailboxMessage, create_message
from zerocode.teams.models import (
    AgentTeam,
    BackendType,
    TeammateInfo,
    resolve_team_dir,
    unique_team_name,
)
from zerocode.teams.progress import TeammateProgress, ToolActivity
from zerocode.teams.registry import AgentNameRegistry
from zerocode.teams.shared_task import SharedTask, SharedTaskStore


__all__ = [
    "AgentTeam",
    "AgentNameRegistry",
    "BackendType",
    "Mailbox",
    "MailboxMessage",
    "SharedTask",
    "SharedTaskStore",
    "TeammateInfo",
    "TeammateProgress",
    "ToolActivity",
    "create_message",
    "resolve_team_dir",
    "unique_team_name",
]

