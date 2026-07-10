"""工具调用权限判定的分层检查器。

PermissionChecker 按固定顺序合并 Plan 模式例外、安全命令识别、
危险命令拦截、路径沙箱、用户规则和权限模式，最终产出允许、
拒绝或询问用户的决策。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from zerocode.permissions.dangerous import DangerousCommandDetector, is_safe_command
from zerocode.permissions.modes import DecisionEffect, PermissionMode, mode_decide
from zerocode.permissions.rules import RuleEngine, extract_content
from zerocode.permissions.sandbox import PathSandbox
from zerocode.tools.base import Tool

_PLAN_MODE_ALLOWED_TOOLS = frozenset({"Agent", "ToolSearch", "AskUserQuestion", "ExitPlanMode"})


@dataclass
class Decision:
    effect: DecisionEffect
    reason: str


# 【讲解】★ 权限系统的总入口 ★——每次工具调用前，agent.py 都会调用它的
# check() 方法。整个类只做一件事：把上面几个独立的小模块（危险命令检测、
# 路径沙箱、规则引擎、模式矩阵）按"从最强硬到最兜底"的顺序串成一条判定
# 链，一旦某一层给出明确结论（allow/deny）就立刻返回，不再往下走——这是
# 典型的"责任链模式"（Chain of Responsibility）。具体顺序看下面 check()
# 方法里的 Layer 0~5 注释，数字越小优先级越高。
class PermissionChecker:


    def __init__(
        self,
        detector: DangerousCommandDetector,
        sandbox: PathSandbox,
        rule_engine: RuleEngine,
        mode: PermissionMode = PermissionMode.DEFAULT,
    ) -> None:
        self.detector = detector
        self.sandbox = sandbox
        self.rule_engine = rule_engine
        self.mode = mode
        self.plan_file_path: str = ""


    # 核心权限入口：按从“强约束/显式规则”到“模式兜底”的顺序短路返回。
    def check(self, tool: Tool, arguments: dict[str, Any]) -> Decision:
        content = extract_content(tool.name, arguments)

        # Layer 0: Plan 模式例外放行
        if self.mode == PermissionMode.PLAN:
            if tool.name in _PLAN_MODE_ALLOWED_TOOLS:
                return Decision(effect="allow", reason="Plan mode: allowed tool")
            if tool.name in ("WriteFile", "EditFile") and content:
                if self._is_plan_file(content):
                    return Decision(effect="allow", reason="Plan mode: plan file write")

        # Layer 1: 安全的只读命令（自动放行）
        if tool.category == "command" and is_safe_command(content or ""):
            return Decision(effect="allow", reason="Safe read-only command")

        # Layer 1b: 危险命令黑名单（仅 Bash）
        if tool.category == "command":
            hit, reason = self.detector.detect(content)
            if hit:
                return Decision(effect="deny", reason=f"危险命令拦截: {reason}")

        # Layer 2: 路径沙箱（仅文件类工具）
        if tool.category in ("read", "write") and content:
            ok, reason = self.sandbox.check(content)
            if not ok:
                return Decision(effect="deny", reason=f"路径沙箱拦截: {reason}")

        # Layer 3: 规则引擎匹配
        rule_result = self.rule_engine.evaluate(tool.name, content)
        if rule_result == "allow":
            return Decision(effect="allow", reason="权限规则放行")
        if rule_result == "deny":
            return Decision(effect="deny", reason="权限规则拒绝")

        # Layer 4: 权限模式兜底判定
        effect = mode_decide(self.mode, tool.category)
        if effect == "allow":
            return Decision(effect="allow", reason=f"权限模式 {self.mode.value} 放行")
        if effect == "deny":
            return Decision(effect="deny", reason=f"权限模式 {self.mode.value} 拒绝")

        # Layer 5: 触发人工确认（HITL）
        return Decision(effect="ask", reason="需要用户确认")


    def _is_plan_file(self, target_path: str) -> bool:
        if not self.plan_file_path or not target_path:
            return ".zerocode/plans/" in target_path
        try:
            abs_target = os.path.abspath(target_path)
            abs_plan = os.path.abspath(self.plan_file_path)
            if abs_target == abs_plan:
                return True
        except Exception:
            pass
        if os.path.basename(target_path) == os.path.basename(self.plan_file_path):
            return True
        return ".zerocode/plans/" in target_path
