"""工具基础类型与流式事件定义模块。

本模块定义所有工具共享的 Tool 抽象基类、ToolResult 返回结构、工具分类、
输出限制常量，以及 LLM 流式响应过程中使用的事件数据结构。
具体工具通过继承 Tool 并实现 execute 方法接入统一调用协议。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".tox", ".mypy_cache"}

MAX_OUTPUT_CHARS = 10000

ToolCategory = Literal["read", "write", "command"]


# 所有工具统一返回该结构，is_error 用于区分正常输出和可恢复错误。
@dataclass
class ToolResult:
    output: str
    is_error: bool = False


class Tool(ABC):
    """【讲解】所有工具的抽象基类（ABC = Abstract Base Class）。

    "工具"就是模型可以请求执行的一个能力（读文件、跑命令……）。每个具体
    工具只需继承本类、填好几个类属性、实现 execute() 方法，就自动接入了
    整个调用体系（schema 上报给模型 → 权限检查 → 参数校验 → 执行）。
    想看最简单的例子可以读 tools/glob.py，三十几行就是一个完整工具。

    各属性含义：
      name / description — 上报给 LLM 的工具名和说明书，模型靠它决定何时调用。
      params_model — 一个 pydantic 模型类，声明参数的名字和类型；既用来给
        模型生成 JSON Schema，也用来校验模型实际传来的参数。
      category — read/write/command 三类，权限系统按类别决定"放行/询问/拒绝"。
      is_concurrency_safe — 是否允许和其他工具并行执行（只读工具才安全）。
      is_system_tool — 系统内部工具（如 ExitPlanMode），不受常规启停控制。
      should_defer — "延迟工具"：启动时只上报名字不上报 schema，省 token，
        模型需要时先用 ToolSearch 加载（你所在的 Claude Code 也是这个机制）。
    """

    name: str
    description: str
    params_model: type[BaseModel]
    category: ToolCategory = "read"
    is_concurrency_safe: bool = False
    is_system_tool: bool = False
    should_defer: bool = False

    @property
    def is_read_only(self) -> bool:
        return self.category == "read"


    def get_schema(self) -> dict[str, Any]:
        # 【讲解】把 pydantic 参数模型自动转成 JSON Schema，随 API 请求发给
        # 模型——模型就是靠这份"参数说明书"知道该怎么填参数的。
        schema = self.params_model.model_json_schema()
        schema.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }

    # 【讲解】@abstractmethod 表示子类必须实现这个方法，否则实例化时报错。
    # `...` 是占位符（等于 pass）。每个工具的全部本领都写在自己的 execute 里。
    @abstractmethod
    async def execute(self, params: BaseModel) -> ToolResult: ...


# --- 流式事件 ---
# 【讲解】下面是"底层流事件"（StreamEvent），描述 LLM 响应流里的原始片段，
# 由 client.py 产生、agent.py 的 StreamCollector 消费。注意和 agent.py 里的
# AgentEvent 区分：StreamEvent 是"API 层的原材料"，AgentEvent 是"加工后给 UI
# 的成品"。命名规律：XxxDelta = 增量小片段，XxxComplete = 拼装完成的整块。


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCallStart:
    tool_name: str
    tool_id: str


@dataclass
class ToolCallDelta:
    text: str


@dataclass
class ToolCallComplete:
    tool_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass
class ThinkingDelta:
    text: str


@dataclass
class ThinkingComplete:
    thinking: str
    signature: str


@dataclass
class StreamEnd:
    stop_reason: str
    input_tokens: int = 0
    output_tokens: int = 0
    # API 返回的 prompt cache 用量。Anthropic 把缓存前缀 token 分为
    # "read"（cache 命中，按 10% 计费）和 "creation"（cache 写入）。
    # input_tokens 已排除这两部分，因此实际 prompt 大小 =
    # input + cache_read + cache_creation。OpenAI 系列只暴露
    # cache_read（通过 *_tokens_details.cached_tokens），没有 creation
    # 计数，所以 cache_creation 在那边始终为 0。
    cache_read: int = 0
    cache_creation: int = 0


StreamEvent = TextDelta | ThinkingDelta | ThinkingComplete | ToolCallStart | ToolCallDelta | ToolCallComplete | StreamEnd
