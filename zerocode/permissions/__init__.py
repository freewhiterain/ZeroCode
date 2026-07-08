"""权限子系统的公共导出入口。

集中暴露权限模式、规则引擎、危险命令检测、路径沙箱和最终检查器，
供 Agent 在工具调用前完成统一权限判定。
"""

from zerocode.permissions.checker import Decision, PermissionChecker
from zerocode.permissions.dangerous import DangerousCommandDetector
from zerocode.permissions.modes import DecisionEffect, PermissionMode, mode_decide
from zerocode.permissions.rules import Rule, RuleEngine, extract_content, parse_rule
from zerocode.permissions.sandbox import PathSandbox


__all__ = [
    "Decision",
    "DecisionEffect",
    "DangerousCommandDetector",
    "PathSandbox",
    "PermissionChecker",
    "PermissionMode",
    "Rule",
    "RuleEngine",
    "extract_content",
    "mode_decide",
    "parse_rule",
]

