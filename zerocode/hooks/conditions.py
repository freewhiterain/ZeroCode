"""Hook 条件表达式解析与求值。

支持相等、不等、正则和通配符匹配，并允许通过 && 或 || 组合多个
条件，用于在 Hook 触发前根据上下文筛选是否执行。
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zerocode.hooks.models import HookContext


# 【讲解】条件表达式的迷你解析器，语法类似 `tool == "Bash"` 或
# `args.file_path =~ /\.py$/`。四种操作符：`==`/`!=` 精确匹配，`=~` 正则，
# `~=` shell 通配符。ConditionGroup 支持用 `&&`/`||` 组合多个条件，但故意
# 禁止在同一个表达式里混用两者（parse_condition 里会直接报错）——因为
# `A && B || C` 到底是 `(A&&B)||C` 还是 `A&&(B||C)` 容易产生歧义，与其
# 猜测用户意图不如强制拆成两条独立的钩子。
@dataclass
class Condition:
    field: str
    operator: str
    value: str


    def evaluate(self, ctx: HookContext) -> bool:
        field_value = ctx.get_field(self.field)
        if self.operator == "==":
            return field_value == self.value
        if self.operator == "!=":
            return field_value != self.value
        if self.operator == "=~":
            pattern = self.value
            if pattern.startswith("/") and pattern.endswith("/"):
                pattern = pattern[1:-1]
            try:
                return bool(re.search(pattern, field_value))
            except re.error:
                return False
        if self.operator == "~=":
            return fnmatch.fnmatch(field_value, self.value)
        return False


@dataclass
class ConditionGroup:
    conditions: list[Condition] = field(default_factory=list)
    logic: str = "and"


    def evaluate(self, ctx: HookContext) -> bool:
        if not self.conditions:
            return True
        if self.logic == "and":
            return all(c.evaluate(ctx) for c in self.conditions)
        return any(c.evaluate(ctx) for c in self.conditions)


class ConditionParseError(Exception):
    pass


_OPERATORS = ("==", "!=", "=~", "~=")


def _parse_single(expr: str) -> Condition:
    expr = expr.strip()
    for op in _OPERATORS:
        idx = expr.find(op)
        if idx == -1:
            continue
        field_part = expr[:idx].strip()
        value_part = expr[idx + len(op):].strip()
        if value_part.startswith('"') and value_part.endswith('"'):
            value_part = value_part[1:-1]
        return Condition(field=field_part, operator=op, value=value_part)
    raise ConditionParseError(f"No valid operator found in condition: '{expr}'")


# 解析单个条件表达式；当前实现刻意禁止混用 && 和 ||，避免优先级歧义。
def parse_condition(expr: str) -> ConditionGroup | None:
    if not expr or not expr.strip():
        return None

    expr = expr.strip()
    has_and = "&&" in expr
    has_or = "||" in expr

    if has_and and has_or:
        raise ConditionParseError(
            "Cannot mix '&&' and '||' in a single condition expression. "
            "Split into separate hooks instead."
        )

    if has_and:
        parts = expr.split("&&")
        logic = "and"
    elif has_or:
        parts = expr.split("||")
        logic = "or"
    else:
        parts = [expr]
        logic = "and"

    conditions = [_parse_single(p) for p in parts]
    return ConditionGroup(conditions=conditions, logic=logic)
