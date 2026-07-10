"""命令系统的核心数据结构与注册表。

这里定义命令类型、执行上下文、UI 协议以及注册表，供各个命令
处理器统一声明、注册、查询和展示命令。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol


# 【讲解】斜杠命令（/clear、/session 等）分三种执行方式：
#   LOCAL    — 纯本地逻辑，不碰 UI，也不用发消息给模型（比如清空某个状态）
#   LOCAL_UI — 本地逻辑但需要操作界面（弹窗、刷新显示，通过 UIController）
#   PROMPT   — 命令本身就是拼一段提示词，直接当作一条消息发给模型
# CommandContext 是每个命令处理函数（CommandHandler）执行时能拿到的"全部
# 家当"——agent、对话、session、UI 控制器等等，处理函数只需要从这一个
# 参数里取所需的东西，不用命令注册时逐个声明依赖。
class CommandType(str, Enum):
    LOCAL = "local"
    LOCAL_UI = "local_ui"
    PROMPT = "prompt"


class UIController(Protocol):
    def add_system_message(self, text: str) -> None: ...


    def send_user_message(self, text: str) -> None: ...
    def set_plan_mode(self, enabled: bool) -> None: ...
    def get_token_count(self) -> tuple[int, int]: ...
    def refresh_status(self) -> None: ...


@dataclass
class CommandContext:
    args: str
    agent: Any
    conversation: Any
    session: Any
    session_manager: Any
    memory_manager: Any
    ui: UIController
    config: Any


CommandHandler = Callable[[CommandContext], Awaitable[None]]


@dataclass
class Command:
    name: str
    description: str
    type: CommandType
    handler: CommandHandler
    aliases: list[str] = field(default_factory=list)
    usage: str = ""
    arg_prompt: str = ""
    hidden: bool = False


# 【讲解】命令注册表，和 tools/__init__.py 的 ToolRegistry 是同一种设计：
# 一个"名字 -> 对象"的字典，外加别名映射表（比如 /q 是 /quit 的别名）。
# register()（异步、带锁）用于运行期动态注册（比如 skill_register.py 把
# 加载到的 Skill 现场注册成命令，多个协程可能同时触发，需要锁防止竞态）；
# register_sync() 是启动阶段的同步版本，那时还没有并发问题，不需要锁。
class CommandRegistry:


    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}
        self._alias_map: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def register(self, command: Command) -> None:
        async with self._lock:
            if command.name in self._commands or command.name in self._alias_map:
                raise ValueError(
                    f"Command name '{command.name}' conflicts with an existing command or alias"
                )
            for alias in command.aliases:
                if alias in self._alias_map or alias in self._commands:
                    raise ValueError(
                        f"Alias '{alias}' conflicts with an existing command or alias"
                    )
            self._commands[command.name] = command
            for alias in command.aliases:
                self._alias_map[alias] = command.name

    def register_sync(self, command: Command) -> None:
        if command.name in self._commands or command.name in self._alias_map:
            raise ValueError(
                f"Command name '{command.name}' conflicts with an existing command or alias"
            )
        for alias in command.aliases:
            if alias in self._alias_map or alias in self._commands:
                raise ValueError(
                    f"Alias '{alias}' conflicts with an existing command or alias"
                )
        self._commands[command.name] = command
        for alias in command.aliases:
            self._alias_map[alias] = command.name


    def find(self, name: str) -> Command | None:
        if name in self._commands:
            return self._commands[name]
        canon = self._alias_map.get(name)
        if canon:
            return self._commands.get(canon)
        return None


    def list_commands(self) -> list[Command]:
        return [cmd for cmd in self._commands.values() if not cmd.hidden]
