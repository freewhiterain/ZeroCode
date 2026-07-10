"""Agent 调用链路追踪。

维护每个 agent 节点的父子关系、trace 标识、状态和 token 统计，便于汇总
一次任务中主 agent 与子 agent 的执行情况。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class TraceNode:
    agent_id: str
    parent_id: str | None
    trace_id: str
    agent_type: str
    input_tokens: int = 0
    output_tokens: int = 0
    tool_call_count: int = 0
    start_time: float = field(default_factory=time.monotonic)
    end_time: float | None = None
    status: str = "running"


# 【讲解】"trace"（调用链追踪）解决的问题：主 agent 派生了好几个子
# agent，子 agent 又可能再派生孙 agent，这棵树的执行情况（谁在跑、跑了多
# 久、花了多少 token）需要能汇总展示出来（就是 /trace 命令看到的树状图）。
# 每个 agent 实例对应一个 TraceNode，靠 parent_id 串成树，trace_id 是"整
# 棵树"共享的同一个标识（根节点的 agent_id）。get_tree() 按 trace_id 一次
# 拉出整棵树的所有节点，get_total_tokens() 汇总整棵树的用量。
class TraceManager:
    def __init__(self) -> None:
        self._nodes: dict[str, TraceNode] = {}


    def create(
        self,
        agent_type: str,
        parent_id: str | None = None,
        trace_id: str | None = None,
    ) -> TraceNode:
        agent_id = uuid.uuid4().hex[:12]
        if trace_id is None:
            trace_id = uuid.uuid4().hex[:12]

        node = TraceNode(
            agent_id=agent_id,
            parent_id=parent_id,
            trace_id=trace_id,
            agent_type=agent_type,
        )
        self._nodes[agent_id] = node
        return node

    def update(self, agent_id: str, **kwargs: int | str) -> None:
        node = self._nodes.get(agent_id)
        if node is None:
            return
        for key, value in kwargs.items():
            if hasattr(node, key):
                setattr(node, key, value)


    def complete(self, agent_id: str, status: str = "completed") -> None:
        node = self._nodes.get(agent_id)
        if node is None:
            return
        node.end_time = time.monotonic()
        node.status = status


    def get(self, agent_id: str) -> TraceNode | None:
        return self._nodes.get(agent_id)

    def get_tree(self, trace_id: str) -> list[TraceNode]:
        return [n for n in self._nodes.values() if n.trace_id == trace_id]


    def remove(self, agent_id: str) -> None:
        self._nodes.pop(agent_id, None)

    def complete_all_running(self, parent_id: str) -> None:
        for node in self._nodes.values():
            if node.parent_id == parent_id and node.status == "running":
                node.status = "completed"
                node.end_time = time.monotonic()

    def get_total_tokens(self, trace_id: str) -> tuple[int, int]:
        total_in = 0
        total_out = 0
        for node in self._nodes.values():
            if node.trace_id == trace_id:
                total_in += node.input_tokens
                total_out += node.output_tokens
        return total_in, total_out
