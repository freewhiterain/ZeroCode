"""对话消息到各 provider 请求格式的序列化适配。

内部 Message 结构保持统一；本模块按 Anthropic Messages、OpenAI Responses
和 OpenAI Chat Completions 三种协议生成对应的消息列表，隔离各家 API
对工具调用、工具结果和 thinking block 的格式差异。
"""

from __future__ import annotations

import json
from typing import Any

from zerocode.conversation import Message

# 把 provider 无关的内部消息序列化成各家 API 的请求格式。
# 这一层属于「适配器」职责，对话层（ConversationManager）只管消息、不懂线上格式。


# 【讲解】三个 build_* 函数结构几乎一样：遍历内部 Message 列表，按
# "这条消息是工具调用/工具结果/普通文本"分支，翻译成对应 API 要的 dict
# 形状。区别只在于三家 API 对"工具调用"和"工具结果"的表达方式不同：
#   Anthropic — 工具调用/结果都是 assistant/user 消息 content 里的一个 block
#   OpenAI Responses — 工具调用/结果各自独立成一条消息（function_call /
#     function_call_output），不嵌在 assistant/user 消息里
#   OpenAI Chat Completions — 工具调用挂在 assistant 消息的 tool_calls 字段，
#     结果是单独的 role="tool" 消息
# 对照着读这三个函数，能直观看到"同一份数据，三种法律文书格式"的感觉。
def build_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for m in messages:
        if m.tool_uses or m.thinking_blocks:
            content: list[dict[str, Any]] = []
            for tb in m.thinking_blocks:
                content.append({
                    "type": "thinking",
                    "thinking": tb.thinking,
                    "signature": tb.signature,
                })
            if m.content:
                content.append({"type": "text", "text": m.content})
            for tu in m.tool_uses:
                content.append({
                    "type": "tool_use",
                    "id": tu.tool_use_id,
                    "name": tu.tool_name,
                    "input": tu.arguments,
                })
            if not content:
                content.append({"type": "text", "text": ""})
            result.append({"role": "assistant", "content": content})
        elif m.tool_results:
            content = []
            for tr in m.tool_results:
                content.append({
                    "type": "tool_result",
                    "tool_use_id": tr.tool_use_id,
                    "content": tr.content,
                    "is_error": tr.is_error,
                })
            result.append({"role": "user", "content": content})
        else:
            # 【讲解】为什么要合并连续的 user 消息？因为 conversation.py 里
            # 一次可能连续调用好几次 add_system_reminder（比如"收到队友消息"+
            # "计划模式提醒"各算一条），如果原样各发一条 user 消息，Anthropic
            # 的 API 不允许两条连续的同角色消息紧挨着（一般要求 user/assistant
            # 交替）。所以这里把连续的纯文本 user 消息用换行拼成一条。
            # 合并连续的 user 纯文本消息（system-reminder 或普通 user 文本）。
            # 不合并到 tool_result 类型的 user 消息中（content 是 list）。
            if (
                m.role == "user"
                and result
                and result[-1]["role"] == "user"
                and isinstance(result[-1]["content"], str)
            ):
                result[-1]["content"] = result[-1]["content"] + "\n" + m.content
            else:
                result.append({"role": m.role, "content": m.content})
    return result


def build_openai_input(messages: list[Message]) -> list[dict[str, Any]]:
    """生成 OpenAI Responses API 的 input 消息列表。"""
    result: list[dict[str, Any]] = []
    for m in messages:
        if m.tool_uses:
            if m.content:
                result.append({"role": "assistant", "content": m.content})
            for tu in m.tool_uses:
                result.append({
                    "type": "function_call",
                    "name": tu.tool_name,
                    "call_id": tu.tool_use_id,
                    "arguments": json.dumps(tu.arguments),
                })
        elif m.tool_results:
            for tr in m.tool_results:
                result.append({
                    "type": "function_call_output",
                    "call_id": tr.tool_use_id,
                    "output": tr.content,
                })
        else:
            result.append({"role": m.role, "content": m.content})
    return result


def build_chat_completion_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """OpenAI Chat Completions 格式。

    - 用户消息：{"role": "user", "content": "..."}
    - 助手文本+工具调用：{"role": "assistant", "content": "...", "tool_calls": [...]}
    - 工具结果：{"role": "tool", "tool_call_id": "...", "content": "..."}
    - thinking 块被跳过（Chat Completions 不支持）。
    """
    result: list[dict[str, Any]] = []
    for m in messages:
        if m.tool_uses:
            tool_calls = []
            for tu in m.tool_uses:
                tool_calls.append({
                    "id": tu.tool_use_id,
                    "type": "function",
                    "function": {
                        "name": tu.tool_name,
                        "arguments": json.dumps(tu.arguments),
                    },
                })
            result.append({
                "role": "assistant",
                "content": m.content or None,
                "tool_calls": tool_calls,
            })
        elif m.tool_results:
            for tr in m.tool_results:
                result.append({
                    "role": "tool",
                    "tool_call_id": tr.tool_use_id,
                    "content": tr.content,
                })
        else:
            result.append({"role": m.role, "content": m.content})
    return result


def build_messages(messages: list[Message], protocol: str = "anthropic") -> list[dict[str, Any]]:
    if protocol == "openai":
        return build_openai_input(messages)
    if protocol == "openai-compat":
        return build_chat_completion_messages(messages)
    return build_anthropic_messages(messages)
