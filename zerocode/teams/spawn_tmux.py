"""基于 tmux pane 启动外部 teammate 进程。

本模块封装 tmux 命令调用、ZeroCode CLI 启动命令构造，以及 pane 的发送和清理。
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class TmuxPaneInfo:
    pane_id: str
    session: str


class TmuxSpawnError(Exception):
    pass


def _run_tmux(*args: str) -> str:
    result = subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise TmuxSpawnError(f"tmux {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


# 【讲解】这里"启动一个队友"的本质，是拼出一条完整的 shell 命令行
# （`ZeroCode -p '任务内容'`，带上环境变量声明团队名/队友名），再用
# tmux send-keys 把这条命令"打字"进新开的 pane 里、模拟按下回车执行——
# 相当于你自己在终端里手动开一个新窗口敲命令，只是全自动完成。
# spawn_tmux_teammate 里那串 try/except 嵌套是"三级降级"：优先在已有的
# tmux 窗口里拆分 pane，失败就新开一个窗口，再失败就干脆新建一整个
# tmux session——保证不管当前 tmux 状态如何都尽量把队友开起来。
def build_cli_command(
    team_name: str,
    teammate_name: str,
    worktree_path: str,
    prompt: str,
    agent_type: str = "",
    model: str = "",
    mailbox_dir: str = "",
) -> str:
    parts = ["ZeroCode", "-p"]
    parts.extend(["--work-dir", worktree_path])
    if agent_type:
        parts.extend(["--agent-type", agent_type])
    if model:
        parts.extend(["--model", model])
    env_parts = [
        f"ZeroCode_TEAM_NAME={team_name}",
        f"ZeroCode_TEAMMATE_NAME={teammate_name}",
    ]
    if mailbox_dir:
        env_parts.append(f"ZeroCode_MAILBOX_DIR={mailbox_dir}")
    env_prefix = " ".join(env_parts)
    cmd = " ".join(parts)
    full_prompt = prompt.replace("'", "'\\''")
    return f"{env_prefix} {cmd} '{full_prompt}'"


def spawn_tmux_teammate(
    team_name: str,
    teammate_name: str,
    worktree_path: str,
    prompt: str,
    agent_type: str = "",
    model: str = "",
    mailbox_dir: str = "",
) -> TmuxPaneInfo:
    window_name = f"{team_name}-{teammate_name}"

    try:
        pane_id = _run_tmux(
            "split-window",
            "-h",
            "-P",
            "-F", "#{pane_id}",
            "-t", f"{team_name}",
        )
    except TmuxSpawnError:
        try:
            _run_tmux("new-window", "-t", f"{team_name}", "-n", window_name, "-P", "-F", "#{pane_id}")
            pane_id = _run_tmux(
                "split-window",
                "-h",
                "-P",
                "-F", "#{pane_id}",
                "-t", f"{team_name}:{window_name}",
            )
        except TmuxSpawnError:
            _run_tmux("new-session", "-d", "-s", team_name, "-n", window_name)
            pane_id = _run_tmux(
                "list-panes",
                "-t", f"{team_name}:{window_name}",
                "-F", "#{pane_id}",
            ).split("\n")[0]

    cli_cmd = build_cli_command(
        team_name=team_name,
        teammate_name=teammate_name,
        worktree_path=worktree_path,
        prompt=prompt,
        agent_type=agent_type,
        model=model,
        mailbox_dir=mailbox_dir,
    )
    _run_tmux("send-keys", "-t", pane_id, cli_cmd, "Enter")

    log.info("Spawned tmux teammate %s in pane %s", teammate_name, pane_id)
    return TmuxPaneInfo(pane_id=pane_id, session=team_name)


def send_keys_to_pane(pane_id: str, keys: str = "") -> None:
    try:
        _run_tmux("send-keys", "-t", pane_id, keys, "Enter")
    except TmuxSpawnError:
        log.warning("Failed to send keys to tmux pane %s", pane_id)


def kill_pane(pane_id: str) -> None:
    try:
        _run_tmux("kill-pane", "-t", pane_id)
    except TmuxSpawnError:
        pass
