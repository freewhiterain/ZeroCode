"""worktree 名称校验与路径片段转换。

限制名称只包含安全字符和有限长度，并把层级式名称压平为可用于目录/分支名的 slug。
"""

from __future__ import annotations

import re

MAX_SLUG_LENGTH = 64
_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


# 【讲解】"slug"是把人类起的名字转成"安全能当文件夹名/分支名用"的字符串
# 的通用叫法（很多网站的 URL 路径段也叫 slug）。validate_slug 只允许字母
# 数字点横线下划线，拒绝 `.` `..` 这种可能引发路径穿越的片段——这是权限
# 沙箱之外的又一道"防止工具参数被滥用"的校验。flatten_slug 把层级名字
# （比如团队队友用的 "team-xxx/成员名"）里的 `/` 换成 `+`，因为分支名和
# 目录名虽然理论上可以带斜杠，但拍平成一层更不容易出岔子。
def validate_slug(name: str) -> str | None:
    if not name:
        return "name cannot be empty"
    if len(name) > MAX_SLUG_LENGTH:
        return f"name too long (max {MAX_SLUG_LENGTH} characters)"


    segments = name.split("/")
    for seg in segments:
        if not seg:
            return "name contains empty segment"
        if seg in (".", ".."):
            return "name must not contain '.' or '..' as a segment"
        if not _SEGMENT_RE.match(seg):
            return f"invalid segment: {seg!r} (allowed: letters, digits, '.', '-', '_')"


    return None


def flatten_slug(name: str) -> str:
    return name.replace("/", "+")
