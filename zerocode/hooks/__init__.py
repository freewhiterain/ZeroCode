"""Hooks 子系统的公共导出入口。

集中暴露条件解析、生命周期事件、Hook 模型、加载器与执行引擎，
便于其他模块以稳定接口接入 Hook 能力。
"""

from zerocode.hooks.conditions import (
    Condition,
    ConditionGroup,
    ConditionParseError,
    parse_condition,
)
from zerocode.hooks.engine import HookEngine
from zerocode.hooks.events import LifecycleEvent
from zerocode.hooks.loader import HookConfigError, load_hooks
from zerocode.hooks.models import (
    Action,
    ActionResult,
    Hook,
    HookContext,
    ToolRejectedError,
)


__all__ = [
    "Action",
    "ActionResult",
    "Condition",
    "ConditionGroup",
    "ConditionParseError",
    "Hook",
    "HookConfigError",
    "HookContext",
    "HookEngine",
    "LifecycleEvent",
    "ToolRejectedError",
    "load_hooks",
    "parse_condition",
]

