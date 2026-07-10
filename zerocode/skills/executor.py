"""Skill 执行器。

根据 SkillDef 的执行模式，将 skill 正文注入当前 agent 或创建隔离的 fork agent
执行，并按声明的 allowedTools 过滤可用工具。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, AsyncIterator

from zerocode.conversation import ConversationManager, Message
from zerocode.skills.parser import SkillDef, substitute_arguments
from zerocode.tools import ToolRegistry

if TYPE_CHECKING:
    from zerocode.agent import Agent, AgentEvent
    from zerocode.client import LLMClient

log = logging.getLogger(__name__)

SYSTEM_TOOL_NAMES = frozenset({"LoadSkill"})

FORK_RECENT_COUNT = 5


class SkillDependencyError(Exception):
    pass


def filter_tool_registry(
    registry: ToolRegistry, allowed: list[str]
) -> ToolRegistry:
    if not allowed:
        return registry

    filtered = ToolRegistry()
    for name in allowed:
        tool = registry.get(name)
        if tool is None:
            raise SkillDependencyError(
                f"Skill requires tool '{name}' but it is not registered"
            )
        filtered.register(tool)

    for tool in registry.list_tools():
        if getattr(tool, "is_system_tool", False) and filtered.get(tool.name) is None:
            filtered.register(tool)

    return filtered


# 【讲解】execute_inline 和 execute_fork 对应 SkillDef.mode 的两种执行方式：
#   inline — 就是 tools/load_skill.py 里做的事：把 SOP 正文钉进当前 agent
#     的 active_skills，不新建任何 agent，当前对话流程原地继续。
#   fork — 真正创建一个全新的、隔离的子 Agent 实例（复用 agent.py 的
#     Agent 类）来专门执行这个 skill，执行完把最终文本结果作为字符串返回，
#     不会污染主对话的工具调用历史。_build_fork_context 决定这个子 agent
#     能看到主对话的多少内容（对应 SkillDef.context 的 full/recent/none）。
#     filter_tool_registry 则按 skill 声明的 allowedTools 白名单砍工具集
#     （逻辑上和 agents/tool_filter.py 的 resolve_agent_tools 是近亲）。
class SkillExecutor:


    def __init__(
        self,
        agent: Agent,
        client: LLMClient,
        protocol: str,
    ) -> None:
        self.agent = agent
        self.client = client
        self.protocol = protocol


    def execute_inline(self, skill: SkillDef, args: str) -> None:
        prompt = substitute_arguments(skill.prompt_body, args)
        self.agent.activate_skill(skill.name, prompt)
        if getattr(self.agent, "recovery_state", None) is not None:
            self.agent.recovery_state.record_skill_invocation(skill.name, prompt)


    async def execute_fork(
        self, skill: SkillDef, args: str
    ) -> str:
        prompt = substitute_arguments(skill.prompt_body, args)
        if getattr(self.agent, "recovery_state", None) is not None:
            self.agent.recovery_state.record_skill_invocation(
                skill.name, skill.prompt_body
            )

        fork_conv = ConversationManager()

        context_messages = self._build_fork_context(skill.context)
        for msg in context_messages:
            if msg.role == "user":
                fork_conv.add_user_message(msg.content)
            else:
                fork_conv.add_assistant_message(msg.content)

        fork_conv.add_user_message(prompt)

        try:
            filtered_registry = filter_tool_registry(
                self.agent.registry, skill.allowed_tools
            )
        except SkillDependencyError as e:
            return f"Skill execution failed: {e}"

        from zerocode.agent import Agent as AgentClass, StreamText, LoopComplete, ErrorEvent

        fork_agent = AgentClass(
            client=self.client,
            registry=filtered_registry,
            protocol=self.protocol,
            work_dir=self.agent.work_dir,
            max_iterations=self.agent.max_iterations,
            permission_checker=None,
            context_window=self.agent.context_window,
        )

        result_parts: list[str] = []
        async for event in fork_agent.run(fork_conv):
            if isinstance(event, StreamText):
                result_parts.append(event.text)
            elif isinstance(event, ErrorEvent):
                result_parts.append(f"\n[Error: {event.message}]")
            elif isinstance(event, LoopComplete):
                break

        return "".join(result_parts)


    def _build_fork_context(self, mode: str) -> list[Message]:
        if mode == "none":
            return []

        history = self.agent._conversation.history if hasattr(self.agent, '_conversation') else []
        if not history:
            main_history = []
        else:
            main_history = history

        if mode == "recent":
            content_messages = [
                m for m in main_history
                if m.content and not m.tool_results
            ]
            return content_messages[-FORK_RECENT_COUNT:]

        if mode == "full":
            content_messages = [
                m for m in main_history
                if m.content and not m.tool_results
            ]
            if not content_messages:
                return []
            summary_parts = []
            for m in content_messages:
                prefix = "User" if m.role == "user" else "Assistant"
                text = m.content[:200]
                if len(m.content) > 200:
                    text += "..."
                summary_parts.append(f"{prefix}: {text}")
            summary = "## Previous conversation summary\n\n" + "\n\n".join(summary_parts)
            return [Message(role="user", content=summary)]

        return []
