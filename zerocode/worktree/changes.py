from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""}


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    import os
    env = {**os.environ, **GIT_ENV}
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


@dataclass
class Changes:
    """worktree 相对创建时 HEAD 的变更计数。"""
    uncommitted: int = 0
    new_commits: int = 0


# 【讲解】"这个 worktree 里有没有值得保留的工作"，用两个 git 命令合起来
# 判断：`git status --porcelain`（每行一个改动文件，数行数就知道有多少
# 未提交改动）+ `git rev-list <创建时的commit>..HEAD --count`（数创建
# 之后新增了多少个提交）。任何一个大于 0 都算"有变更"，触发 exit_worktree.py
# / auto_cleanup 里的保护逻辑。异常情况下（git 命令本身失败）保守地当作
# "有变更"处理（uncommitted/new_commits 设为 1），宁可误判为"有改动"多问
# 一句，也不要真把用户的工作误删。
def count_worktree_changes(wt_path: str, head_commit: str) -> Changes:
    changes = Changes()
    try:
        status = _run_git(["status", "--porcelain"], cwd=wt_path)
        if status.returncode == 0:
            changes.uncommitted = len(
                [line for line in status.stdout.splitlines() if line.strip()]
            )
    except (subprocess.SubprocessError, OSError):
        changes.uncommitted = 1

    try:
        rev_list = _run_git(
            ["rev-list", "--count", f"{head_commit}..HEAD"], cwd=wt_path
        )
        if rev_list.returncode == 0:
            changes.new_commits = int(rev_list.stdout.strip())
    except (subprocess.SubprocessError, OSError, ValueError):
        changes.new_commits = 1

    return changes


def has_worktree_changes(wt_path: str, head_commit: str) -> bool:
    c = count_worktree_changes(wt_path, head_commit)
    return c.uncommitted > 0 or c.new_commits > 0


@dataclass
class CleanupResult:
    """自动清理 worktree 后返回给调用方的结果。"""
    kept: bool
    path: str = ""
    branch: str = ""


def has_unpushed_commits(wt_path: str) -> bool:
    try:
        result = _run_git(
            ["rev-list", "--max-count=1", "HEAD", "--not", "--remotes"],
            cwd=wt_path,
        )
        return bool(result.stdout.strip()) if result.returncode == 0 else True
    except (subprocess.SubprocessError, OSError):
        return True
