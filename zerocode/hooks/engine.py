"""Hook 匹配与调度引擎。

HookEngine 负责按生命周期事件筛选 Hook、处理 once/条件匹配、同步
或异步执行动作，并收集提示消息、通知和工具拒绝结果。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from zerocode.hooks.executors import execute_action
from zerocode.hooks.models import ActionResult, Hook, HookContext, ToolRejectedError

log = logging.getLogger(__name__)


@dataclass
class HookNotification:
    hook_id: str
    event: str
    output: str
    success: bool


# 【讲解】★ hooks 子系统的总调度器 ★，agent.py 持有一个实例。核心方法
# run_hooks(event, ctx) 在生命周期的每个时间点被调用：先用
# find_matching_hooks 筛出"事件名对上 + 条件满足 + 没被 once 用掉"的钩子，
# 逐个执行。同步钩子会 await 等它跑完，异步钩子用
# asyncio.ensure_future"发射后不管"（不阻塞主流程）。run_pre_tool_hooks
# 是特化版本：专门给 pre_tool_use 用，因为它需要能真正"拒绝"工具调用
# （返回 ToolRejectedError），这是唯一一种能改变 Agent 主循环行为的钩子，
# 其余钩子的输出只是"记录下来"（prompt 类型会被塞进下一次的 system
# prompt，其余的存进 _notifications 供 UI 展示或注入对话）。
class HookEngine:
    def __init__(self, hooks: list[Hook] | None = None) -> None:
        self.hooks: list[Hook] = hooks or []
        self._prompt_messages: list[str] = []
        self._notifications: list[HookNotification] = []


    def find_matching_hooks(self, event: str, ctx: HookContext) -> list[Hook]:
        matched: list[Hook] = []
        for hook in self.hooks:
            if hook.event != event:
                continue
            if not hook.should_run():
                continue
            if hook.condition is not None and not hook.condition.evaluate(ctx):
                continue
            matched.append(hook)
        return matched


    # 普通生命周期 Hook：异步 Hook 只调度不阻塞，同步 Hook 则按顺序等待执行完成。
    async def run_hooks(self, event: str, ctx: HookContext) -> None:
        matched = self.find_matching_hooks(event, ctx)
        for hook in matched:
            hook.mark_executed()
            if hook.async_exec:
                asyncio.ensure_future(self._run_single(hook, ctx))
            else:
                await self._run_single(hook, ctx)


    async def _run_single(self, hook: Hook, ctx: HookContext) -> None:
        try:
            result = await execute_action(hook.action, ctx)
            if hook.action.type == "prompt" and result.success:
                self._prompt_messages.append(result.output)
            self._notifications.append(
                HookNotification(
                    hook_id=hook.id,
                    event=hook.event,
                    output=result.output,
                    success=result.success,
                )
            )
            if not result.success:
                log.warning(
                    "Hook '%s' action failed: %s", hook.id, result.output
                )
        except Exception as e:
            log.warning("Hook '%s' execution error: %s", hook.id, e)
            self._notifications.append(
                HookNotification(
                    hook_id=hook.id,
                    event=hook.event,
                    output=str(e),
                    success=False,
                )
            )


    async def run_pre_tool_hooks(
        self, ctx: HookContext
    ) -> ToolRejectedError | None:
        matched = self.find_matching_hooks("pre_tool_use", ctx)
        for hook in matched:
            hook.mark_executed()
            try:
                result = await execute_action(hook.action, ctx)
                self._notifications.append(
                    HookNotification(
                        hook_id=hook.id,
                        event="pre_tool_use",
                        output=result.output,
                        success=result.success,
                    )
                )
                if hook.reject:
                    return ToolRejectedError(
                        tool=ctx.tool_name,
                        reason=result.output,
                        hook_id=hook.id,
                    )
            except Exception as e:
                log.warning("Hook '%s' execution error: %s", hook.id, e)
        return None

    def get_prompt_messages(self) -> list[str]:
        messages = list(self._prompt_messages)
        self._prompt_messages.clear()
        return messages


    def drain_notifications(self) -> list[HookNotification]:
        notifications = list(self._notifications)
        self._notifications.clear()
        return notifications
