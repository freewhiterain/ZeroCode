"""基于 iTerm2 it2 CLI 启动外部 teammate 进程。

当用户显式使用 iTerm2 pane 后端时，本模块负责拆分 pane 并运行 teammate CLI。
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class ITermPaneInfo:
    session_id: str


class ITermSpawnError(Exception):
    pass


def _run_it2(*args: str) -> str:
    result = subprocess.run(
        ["it2", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise ITermSpawnError(f"it2 {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


# 【讲解】和 spawn_tmux.py 是同一个思路的 iTerm2 版本（复用它的
# build_cli_command 拼命令行），只是调用的外部程序换成了 iTerm2 官方提供
# 的 it2 命令行工具，用 it2 split-pane 开一个新窗格并执行命令。
def spawn_iterm2_teammate(
    team_name: str,
    teammate_name: str,
    worktree_path: str,
    prompt: str,
    agent_type: str = "",
    model: str = "",
    mailbox_dir: str = "",
) -> ITermPaneInfo:
    from zerocode.teams.spawn_tmux import build_cli_command

    cli_cmd = build_cli_command(
        team_name=team_name,
        teammate_name=teammate_name,
        worktree_path=worktree_path,
        prompt=prompt,
        agent_type=agent_type,
        model=model,
        mailbox_dir=mailbox_dir,
    )

    try:
        session_id = _run_it2("split-pane", "--command", f"/bin/zsh -c '{cli_cmd}'")
    except ITermSpawnError as e:
        raise ITermSpawnError(f"Failed to spawn iTerm2 pane for {teammate_name}: {e}") from e

    log.info("Spawned iTerm2 teammate %s in session %s", teammate_name, session_id)
    return ITermPaneInfo(session_id=session_id)
