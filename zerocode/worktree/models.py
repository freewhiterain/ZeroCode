"""worktree 子系统的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


# 【讲解】两个概念容易混淆：Worktree 是"这个隔离工作区本身的静态信息"
# （路径、分支名，长期存在于 WorktreeManager.active 字典里）；
# WorktreeSession 是"当前进程有没有'进入'某个 worktree"的会话状态
# （记录进入前的原始目录，方便退出时恢复），会被持久化到磁盘文件
# （worktree/session.py），这样即使程序重启，也能知道"上次退出前是不是
# 还停留在某个 worktree 里"。
@dataclass
class Worktree:
    """一个已创建 Git worktree 的静态信息。"""
    name: str
    path: str
    branch: str
    based_on: str
    head_commit: str
    created: datetime = field(default_factory=datetime.now)


@dataclass
class WorktreeSession:
    """当前进程进入 worktree 前后的会话状态。"""
    original_cwd: str
    worktree_path: str
    worktree_name: str
    original_branch: str
    original_head_commit: str
    session_id: str = ""
    hook_based: bool = False

