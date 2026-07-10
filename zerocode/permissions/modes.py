"""权限模式与默认决策矩阵。

不同模式对读、写、命令三类工具给出默认 allow/deny/ask 策略，
供规则未命中时作为兜底权限判定。
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from zerocode.tools.base import ToolCategory


DecisionEffect = Literal["allow", "deny", "ask"]


# 【讲解】六种权限模式，对应你在 ZeroCode 里能选的"胆子大小"：
#   DEFAULT      — 读随便看，写/跑命令都要问一句（最保守的默认档）
#   ACCEPT_EDITS — 写文件不问了，跑命令还是要问（适合"我信任它改代码"）
#   PLAN         — 计划模式：只能读和写计划文件，不能真的动项目（见 checker.py Layer 0）
#   BYPASS       — 全部放行，不问（胆子最大，适合完全信任的自动化场景）
#   CUSTOM       — 全部都问（比 DEFAULT 更保守，连读都要确认）
#   DONT_ASK     — 全部放行，同 BYPASS，但语义上是"非交互场景下别问了"
# `class PermissionMode(str, Enum)`：继承 str 意味着这个枚举值本身也是
# 字符串（PermissionMode.DEFAULT == "default" 成立），方便和配置文件里的
# 字符串直接比较、直接序列化。
class PermissionMode(str, Enum):
    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    PLAN = "plan"
    BYPASS = "bypassPermissions"
    CUSTOM = "custom"
    DONT_ASK = "dontAsk"


# 【讲解】这就是"默认决策矩阵"本体：模式 × 工具类别 → allow/deny/ask。
# 是权限判定链条的最后一道兜底（checker.py 的 Layer 4）——前面的沙箱、
# 规则引擎都没给出明确结论时，就查这张表。
_MODE_MATRIX: dict[PermissionMode, dict[ToolCategory, DecisionEffect]] = {
    PermissionMode.DEFAULT: {"read": "allow", "write": "ask", "command": "ask"},
    PermissionMode.ACCEPT_EDITS: {"read": "allow", "write": "allow", "command": "ask"},
    PermissionMode.PLAN: {"read": "allow", "write": "ask", "command": "ask"},
    PermissionMode.BYPASS: {"read": "allow", "write": "allow", "command": "allow"},
    PermissionMode.CUSTOM: {"read": "ask", "write": "ask", "command": "ask"},
    PermissionMode.DONT_ASK: {"read": "allow", "write": "allow", "command": "allow"},
}


def mode_decide(mode: PermissionMode, category: ToolCategory) -> DecisionEffect:
    return _MODE_MATRIX[mode][category]
