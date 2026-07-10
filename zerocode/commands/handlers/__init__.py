"""内置斜杠命令处理器集合。

本模块汇总默认启用的命令对象，并提供一次性注册函数，供应用
启动时把内置命令装载到命令注册表中。
"""

from __future__ import annotations

from zerocode.commands.handlers.clear import CLEAR_COMMAND
from zerocode.commands.handlers.compact import COMPACT_COMMAND
from zerocode.commands.handlers.help import HELP_COMMAND
from zerocode.commands.handlers.mcp import MCP_COMMAND
from zerocode.commands.handlers.memory import MEMORY_COMMAND
from zerocode.commands.handlers.permission import PERMISSION_COMMAND
from zerocode.commands.handlers.plan import PLAN_COMMAND
from zerocode.commands.handlers.session import SESSION_COMMAND
from zerocode.commands.handlers.skill import SKILL_COMMAND
from zerocode.commands.handlers.rewind import REWIND_COMMAND
from zerocode.commands.handlers.status import STATUS_COMMAND
from zerocode.commands.registry import CommandRegistry


# 【讲解】handlers/ 目录下每个文件实现一个斜杠命令，共同的模式是：
#   ① 写一个 `async def handle_xxx(ctx: CommandContext)` 处理函数——直接
#     读写 ctx.ui / ctx.agent / ctx.session 等字段完成命令逻辑；
#   ② 用 Command(...) 包一层元数据（name、别名、用法提示、类型）；
#   ③ 模块末尾导出一个 XXX_COMMAND 常量。
# 有几个命令（tasks.py/trace.py/worktree.py）需要额外依赖（TaskManager、
# TraceManager 等），它们改用"工厂函数" create_xxx_command(dep) 模式，
# 通过闭包把依赖捕获进 handler，而不是像其他命令那样在模块顶层直接定义。
# 本文件的 register_all_commands() 是启动时的入口，把 ALL_COMMANDS 一次性
# 灌进 CommandRegistry；不在 ALL_COMMANDS 里的几个（tasks/trace/worktree）
# 是运行期动态注册的，因为它们需要在别处先构造好依赖对象。
ALL_COMMANDS = [
    HELP_COMMAND,
    COMPACT_COMMAND,
    CLEAR_COMMAND,
    PLAN_COMMAND,
    SESSION_COMMAND,
    MCP_COMMAND,
    MEMORY_COMMAND,
    PERMISSION_COMMAND,
    REWIND_COMMAND,
    STATUS_COMMAND,
    SKILL_COMMAND,
]


def register_all_commands(registry: CommandRegistry) -> None:
    for cmd in ALL_COMMANDS:
        registry.register_sync(cmd)

