"""构造 fork 子 Agent 的对话上下文。

fork 会复制当前对话历史、补齐中断工具调用的占位结果，并追加严格的子进程
工作规则，确保派生出的 agent 只执行被分配的范围且不能继续嵌套 fork。
"""
from __future__ import annotations

import copy

from zerocode.conversation import ConversationManager, Message, ToolResultBlock

FORK_BOILERPLATE_TAG = "<fork_boilerplate>"

FORK_BOILERPLATE = f"""{FORK_BOILERPLATE_TAG}
你是一个 Fork 出来的工作进程。你不是主 Agent。
规则（不可协商）：
1. 不能再 Fork。
2. 不要对话、不要提问、不要请求确认。
3. 直接使用工具：读文件、搜索代码、做修改。
4. 严格限制在你被分配的任务范围内。
5. 最终报告控制在 500 字以内，格式如下：

Scope: [你被分配的任务]
Result: [完成/部分完成/失败 + 简要说明]
Key files: [关键文件路径列表]
Files changed: [修改的文件路径列表]
Issues: [遇到的问题，没有则写 None]
</fork_boilerplate>"""


class ForkError(Exception):
    pass


# 【讲解】fork 出的子 agent 会拿到父 agent 当前对话历史的一份"深拷贝"
# （copy.deepcopy——连嵌套的列表/dataclass 都整体复制，不共享引用，子 agent
# 怎么改都不会影响父 agent 的历史）。有个边界情况需要处理：如果父 agent
# 正好在"刚发起了工具调用、还没拿到结果"的时刻被 fork（比如 Agent 工具
# 本身就是父 agent 发起的一次工具调用），那父对话历史末尾会有"悬空"的
# tool_use（没有配对的 tool_result）——这在 LLM API 里是不合法的。下面这段
# 就是给这些悬空调用补一个占位结果（content="interrupted"），让复制出来
# 的对话历史保持 API 要求的"工具调用必须成对"的完整性。
def build_forked_messages(
    conversation: ConversationManager,
    task: str,
) -> ConversationManager:
    for msg in conversation.history:
        if FORK_BOILERPLATE_TAG in msg.content:
            raise ForkError(
                "Cannot fork from a forked agent. "
                "Fork nesting is not allowed."
            )

    fork_conv = ConversationManager()
    fork_conv.history = copy.deepcopy(conversation.history)
    fork_conv.env_injected = conversation.env_injected
    fork_conv.ltm_injected = conversation.ltm_injected


    if fork_conv.history:
        last = fork_conv.history[-1]
        if last.role == "assistant" and last.tool_uses:
            existing_result_ids = set()
            if len(fork_conv.history) >= 2:
                candidate = fork_conv.history[-1]
                if candidate.tool_results:
                    existing_result_ids = {
                        tr.tool_use_id for tr in candidate.tool_results
                    }

            pending = [
                tu
                for tu in last.tool_uses
                if tu.tool_use_id not in existing_result_ids
            ]
            if pending:
                placeholders = [
                    ToolResultBlock(
                        tool_use_id=tu.tool_use_id,
                        content="interrupted",
                        is_error=False,
                    )
                    for tu in pending
                ]
                fork_conv.history.append(
                    Message(
                        role="user",
                        content="",
                        tool_results=placeholders,
                    )
                )

    fork_conv.add_user_message(f"{FORK_BOILERPLATE}\n\n你的任务：\n{task}")
    return fork_conv

