"""命令子系统的公共导出入口。

对外集中暴露命令解析、补全、命令模型和注册表，避免调用方直接
依赖 commands 包内部文件布局。
"""

from zerocode.commands.parser import complete, parse_command
from zerocode.commands.registry import (
    Command,
    CommandContext,
    CommandHandler,
    CommandRegistry,
    CommandType,
    UIController,
)


__all__ = [
    "Command",
    "CommandContext",
    "CommandHandler",
    "CommandRegistry",
    "CommandType",
    "UIController",
    "complete",
    "parse_command",
]

