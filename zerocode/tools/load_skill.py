"""技能加载工具模块。

本模块实现 LoadSkill 系统工具，用于按名称激活技能 SOP，并在目录型
技能存在专用工具时将其注册到当前 Agent 的工具注册表中。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from zerocode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from zerocode.agent import Agent
    from zerocode.skills.directory import register_skill_tools
    from zerocode.skills.loader import SkillLoader


# 技能加载入参：通过目录或目录清单中的技能名称定位 SOP。
class LoadSkillParams(BaseModel):
    name: str = Field(description="The name of the skill to load")


class LoadSkill(Tool):
    name = "LoadSkill"
    description = (
        "Load and activate a skill by name. "
        "The skill's SOP will be pinned to the environment context "
        "and any specialized tools will be registered."
    )
    params_model = LoadSkillParams
    category = "read"
    is_concurrency_safe = False
    is_system_tool = True


    def __init__(self) -> None:
        self._loader: SkillLoader | None = None
        self._agent: Agent | None = None


    def set_loader(self, loader: SkillLoader) -> None:
        self._loader = loader

    def set_agent(self, agent: Agent) -> None:
        self._agent = agent


    async def execute(self, params: BaseModel) -> ToolResult:
        assert isinstance(params, LoadSkillParams)

        if self._loader is None or self._agent is None:
            return ToolResult(
                output="Error: LoadSkill not properly initialized",
                is_error=True,
            )

        skill = self._loader.get(params.name)
        if skill is None:
            available = ", ".join(n for n, _ in self._loader.get_catalog())
            return ToolResult(
                output=f"Error: unknown skill '{params.name}'. Available skills: {available}",
                is_error=True,
            )

        # 【讲解】"激活技能"分两步：① 把技能的提示词正文（SOP）钉进环境上下文
        # （activate_skill，之后每轮都会带上，见 prompts.py build_environment_context）；
        # ② 如果是"目录型技能"（自带 tool.json 描述的专用工具），动态把那些
        # 工具注册进当前 agent 的工具表——这就是为什么有的技能激活后模型会
        # 突然"多出"几个新工具可用。
        self._agent.activate_skill(skill.name, skill.prompt_body)

        tool_count = 0
        if skill.is_directory and skill.source_path is not None:
            from zerocode.skills.directory import register_skill_tools
            skill_dir = skill.source_path.parent
            tool_count = register_skill_tools(skill_dir, self._agent.registry)

        parts = [f"Skill '{skill.name}' activated. SOP pinned to environment context."]
        if tool_count > 0:
            parts.append(f"{tool_count} specialized tool(s) registered.")
        return ToolResult(output=" ".join(parts))
