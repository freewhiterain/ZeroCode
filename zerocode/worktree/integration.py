"""worktree 与 agent 上下文集成辅助函数。

用于生成隔离 worktree 名称，并构造提示文本提醒子 agent 将父目录路径映射到
当前 worktree。
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zerocode.worktree.manager import WorktreeManager


# 【讲解】小而关键的一段：子 agent 被派到隔离 worktree 里干活时，如果它
# fork 了父 agent 的对话历史（见 agents/fork.py），那段历史里提到的文件
# 路径全都是"父目录"下的路径——但子 agent 实际工作在完全不同的一个
# worktree 目录里。build_worktree_notice() 生成的这段提示就是显式告诉
# 子 agent"路径要换算，读文件前记得重新读"，防止它凭记忆用错误的路径
# 操作，或者误以为父目录里的文件内容在这里也一样。
WORKTREE_NOTICE_TEMPLATE = """\
[WORKTREE CONTEXT]
You have inherited the parent agent's conversation context.
You are currently working in an isolated Git Worktree: {wt_path}
The parent agent's working directory is: {parent_cwd}

IMPORTANT:
- File paths mentioned in the parent conversation refer to the PARENT directory.
- You must translate them to your local worktree path before reading or editing.
- Always re-read files before editing — your copy may differ from the parent's version.
[/WORKTREE CONTEXT]
"""


def generate_worktree_name() -> str:
    return f"agent-{secrets.token_hex(4)}"


def build_worktree_notice(parent_cwd: str, wt_path: str) -> str:
    return WORKTREE_NOTICE_TEMPLATE.format(
        parent_cwd=parent_cwd,
        wt_path=wt_path,
    )

