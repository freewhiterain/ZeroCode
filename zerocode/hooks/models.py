"""Hook 配置与运行时上下文模型。

这些 dataclass 描述 Hook 动作、执行结果、触发条件以及模板展开所需
上下文，是加载器、执行器和引擎之间传递数据的统一结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from zerocode.hooks.conditions import ConditionGroup


@dataclass
class Action:
    type: str
    command: str = ""
    message: str = ""
    url: str = ""
    method: str = "POST"
    body: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    prompt: str = ""
    timeout: int = 30


@dataclass
class ActionResult:
    output: str = ""
    success: bool = True


# 【讲解】Action 描述"钩子触发时具体干什么"（四选一：跑 shell 命令 /
# 注入一段提示文字 / 发 HTTP 请求 / 交给 agent 处理，见 executors.py）。
# Hook 则是"什么时候、在什么条件下触发这个 Action"的完整配置：event 对应
# LifecycleEvent、condition 是可选的过滤条件（见 conditions.py）、reject
# 表示这个钩子能直接否决工具调用（只用于 pre_tool_use）、once 表示只触发
# 一次。HookContext.expand() 是个简易模板引擎：把钩子命令/消息里的
# `$TOOL_NAME`、`$FILE_PATH` 这类占位符替换成本次调用的实际值。
@dataclass
class Hook:
    id: str
    event: str
    action: Action
    condition: ConditionGroup | None = None
    reject: bool = False
    once: bool = False
    async_exec: bool = False
    executed: bool = False


    def should_run(self) -> bool:
        if self.once and self.executed:
            return False
        return True


    def mark_executed(self) -> None:
        self.executed = True


@dataclass
class HookContext:
    event_name: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    file_path: str = ""
    message: str = ""
    error: str = ""

    def get_field(self, name: str) -> str:
        if name == "tool":
            return self.tool_name
        if name == "event":
            return self.event_name
        if name.startswith("args."):
            key = name[5:]
            value = self.tool_args.get(key, "")
            return str(value) if value else ""
        return ""

    def expand(self, template: str) -> str:
        result = template
        result = result.replace("$EVENT", self.event_name)
        result = result.replace("$TOOL_NAME", self.tool_name)
        result = result.replace("$FILE_PATH", self.file_path)
        result = result.replace("$MESSAGE", self.message)
        result = result.replace("$ERROR", self.error)
        for key, value in self.tool_args.items():
            result = result.replace(f"$TOOL_ARGS.{key}", str(value))
        return result


class ToolRejectedError(Exception):
    def __init__(self, tool: str, reason: str, hook_id: str) -> None:
        self.tool = tool
        self.reason = reason
        self.hook_id = hook_id
        super().__init__(f"Tool '{tool}' rejected by hook '{hook_id}': {reason}")
