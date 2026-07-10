"""过期临时 worktree 的后台清理逻辑。

清理仅针对符合临时命名模式、超过时间阈值且无本地/未推送变更的 worktree，
避免误删用户手动创建的工作区。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from zerocode.worktree.changes import has_unpushed_commits, has_worktree_changes
from zerocode.worktree.manager import WorktreeManager

log = logging.getLogger(__name__)

# 【讲解】"临时 worktree"是那些由 agent/团队/后台任务自动创建、命名带
# 特定前缀（agent-xxx、wf-xxx、bridge-xxx 等）的工作区。这个清理器只处理
# 匹配这些命名模式的目录——用户自己手动创建的 worktree（名字不匹配任何
# 正则）永远不会被自动删除，这是刻意的安全边界。真正删除前还要过四道
# 关卡：不是当前正在用的 session、超过时间阈值、没有未提交的改动、没有
# 未推送的提交——任何一条不满足就跳过，宁可漏清理也不能误删用户的工作。
EPHEMERAL_PATTERNS = [
    re.compile(r"^agent-a[0-9a-f]{7}$"),
    re.compile(r"^wf_[0-9a-f]{8}-[0-9a-f]{3}-\d+$"),
    re.compile(r"^wf-\d+$"),
    re.compile(r"^bridge-[A-Za-z0-9_]+(-[A-Za-z0-9_]+)*$"),
    re.compile(r"^job-[a-zA-Z0-9._-]{1,55}-[0-9a-f]{8}$"),
]


def _is_ephemeral(name: str) -> bool:
    return any(p.match(name) for p in EPHEMERAL_PATTERNS)


async def cleanup_stale_worktrees(manager: WorktreeManager, cutoff_hours: int) -> int:
    """扫描并删除超过阈值且安全可移除的临时 worktree。"""
    cutoff = datetime.now() - timedelta(hours=cutoff_hours)
    removed = 0
    worktree_dir = Path(manager.worktree_dir)

    if not worktree_dir.exists():
        return 0

    for entry in worktree_dir.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name

        if not _is_ephemeral(name):
            continue

        if manager.current_session and manager.current_session.worktree_name == name:
            continue

        try:
            mtime = datetime.fromtimestamp(entry.stat().st_mtime)
            if mtime > cutoff:
                continue
        except OSError:
            continue

        head_sha = WorktreeManager.read_worktree_head_sha(str(entry))
        if head_sha is None:
            continue

        if has_worktree_changes(str(entry), head_sha):
            continue

        if has_unpushed_commits(str(entry)):
            continue

        try:
            flat_name = name
            if flat_name in manager.active:
                await manager._remove_worktree(flat_name, manager.active[flat_name])
            else:
                result = manager._run_git(
                    ["worktree", "remove", "--force", str(entry)]
                )
                if result.returncode == 0:
                    await asyncio.sleep(0.1)
                    manager._run_git(["branch", "-D", f"worktree-{flat_name}"])
            removed += 1
            log.info("Cleaned up stale worktree: %s", name)
        except Exception as e:
            log.warning("Failed to clean up stale worktree %s: %s", name, e)

    return removed


async def start_stale_cleanup_task(
    manager: WorktreeManager,
    interval: int,
    cutoff_hours: int,
) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            count = await cleanup_stale_worktrees(manager, cutoff_hours)
            if count:
                log.info("Stale worktree cleanup removed %d worktrees", count)
        except Exception as e:
            log.warning("Stale worktree cleanup error: %s", e)

