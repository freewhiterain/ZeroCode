"""实现 /clear 命令。

负责关闭当前会话、创建新会话、重置对话与 Agent 状态，并刷新界面。
"""

from __future__ import annotations

from zerocode.commands.registry import Command, CommandContext, CommandType
from zerocode.conversation import ConversationManager


# 【讲解】最简单的命令范例（对照 commands/handlers/__init__.py 顶部注释里
# 说的三步模式看）：直接操作 ctx 里的对象完成"关旧会话、开新会话、清空
# 对话历史、重置 agent 计数器、刷新界面"，最后调用 ctx.ui.add_system_message
# 显示一条反馈。ctx.config 字典里挂着几个"回调函数"（set_session、
# set_conversation、clear_chat）——这是因为创建新会话/对话对象这件事本该
# 由拥有这些状态的 app.py 完成，命令处理器不直接持有它们，只调用回调让
# app.py 去做替换，避免命令模块反向依赖 app.py。
async def handle_clear(ctx: CommandContext) -> None:
    if ctx.session:
        ctx.session.close()

    if ctx.session_manager:
        new_session = ctx.session_manager.create()
        ctx.config["set_session"](new_session)


    ctx.config["set_conversation"](ConversationManager())

    if ctx.agent:
        ctx.agent._loop_count = 0
        ctx.agent.clear_active_skills()

    ctx.config["clear_chat"]()
    ctx.ui.refresh_status()
    ctx.ui.add_system_message("对话已清除，新会话已创建")


CLEAR_COMMAND = Command(
    name="clear",
    description="清除对话历史",
    usage="/clear",
    type=CommandType.LOCAL_UI,
    handler=handle_clear,
)

