"""把已加载 Skill 动态注册为斜杠命令。

注册流程会先清理旧的 Skill 命令，再为当前 catalog 生成命令处理器，
根据 Skill 模式选择 fork 异步执行或 inline 注入执行。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from zerocode.commands.registry import Command, CommandContext, CommandRegistry, CommandType

if TYPE_CHECKING:
    from zerocode.skills.executor import SkillExecutor
    from zerocode.skills.loader import SkillLoader

log = logging.getLogger(__name__)

_REGISTERED_SKILL_NAMES: set[str] = set()


# 【讲解】这是"斜杠命令是怎么变出来的"的关键一环：Skill 不是提前写死在
# ALL_COMMANDS 列表里的，而是根据当前加载到的 skill 目录/文件，运行期
# 动态地为每一个 skill 生成一个同名命令（比如 commit skill 就变成了
# /commit）。make_handler(name) 用了个经典的闭包技巧：如果直接在 for 循环
# 里定义 async def handler 并引用循环变量 skill_name，所有生成的 handler
# 最后会共享同一个循环结束时的 skill_name 值（Python 闭包捕获变量而非
# 值的经典坑）；用一个额外的工厂函数把 name 当参数传进去、在函数体内部
# 生成新的 handler，才能让每个命令绑定到正确的 skill 名字。
# 重新加载 Skill 后会调用该函数刷新动态命令，避免旧命令残留或与内置命令冲突。
def register_skill_commands(
    registry: CommandRegistry,
    loader: SkillLoader,
    executor: SkillExecutor | None = None,
) -> None:
    for name in list(_REGISTERED_SKILL_NAMES):
        if registry.find(name) is not None:
            registry._commands.pop(name, None)
            registry._alias_map = {
                k: v for k, v in registry._alias_map.items() if v != name
            }
        _REGISTERED_SKILL_NAMES.discard(name)

    for skill_name, skill_desc in loader.get_catalog():
        if registry.find(skill_name) is not None:
            continue

        s_name = skill_name
        s_desc = skill_desc


        def make_handler(name: str) -> callable:


            async def handler(ctx: CommandContext) -> None:
                exe = ctx.config.get("skill_executor") if executor is None else executor
                if exe is None:
                    ctx.ui.add_system_message("Skill 执行器未初始化")
                    return

                skill_loader: SkillLoader | None = ctx.config.get("skill_loader")
                if skill_loader is None:
                    ctx.ui.add_system_message("Skill 加载器未初始化")
                    return

                skill = skill_loader.get(name)
                if skill is None:
                    ctx.ui.add_system_message(f"未找到 Skill：{name}")
                    return

                if skill.mode == "fork":
                    ctx.ui.add_system_message(f"⏳ Running {name} skill...")


                    async def _run_fork() -> None:
                        try:
                            result = await exe.execute_fork(skill, ctx.args)
                            ctx.ui.add_system_message(
                                f"[{name} skill result]\n{result}"
                            )
                        except Exception as e:
                            ctx.ui.add_system_message(
                                f"Skill {name} failed: {e}"
                            )

                    asyncio.create_task(_run_fork())
                else:
                    exe.execute_inline(skill, ctx.args)
                    tools_info = ""
                    if skill.allowed_tools:
                        tools_info = f" · {len(skill.allowed_tools)} tools allowed"
                    ctx.ui.add_system_message(
                        f"skill({name})\nSuccessfully loaded skill{tools_info}"
                    )
                    trigger = ctx.args if ctx.args else f"/{name}"
                    ctx.ui.send_user_message(trigger)

            return handler

        cmd = Command(
            name=s_name,
            description=f"{s_desc} [skill]",
            usage=f"/{s_name} [args]",
            type=CommandType.PROMPT,
            handler=make_handler(s_name),
        )

        try:
            registry.register_sync(cmd)
            _REGISTERED_SKILL_NAMES.add(s_name)
        except ValueError as e:
            log.warning("Cannot register skill command '%s': %s", s_name, e)
