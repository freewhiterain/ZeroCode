"""团队 teammate 后端检测逻辑。

默认使用 in-process 后端以支持实时进度；当显式请求 pane 模式时，可检测 tmux
或 iTerm2 作为外部进程承载方式。
"""

from __future__ import annotations

import os
import shutil

from zerocode.teams.models import BackendType


class BackendDetectionError(Exception):
    pass


def _in_tmux_session() -> bool:
    return bool(os.environ.get("TMUX"))


def _in_iterm2() -> bool:
    return os.environ.get("TERM_PROGRAM") == "iTerm.app"


def _it2_available() -> bool:
    return shutil.which("it2") is not None


def _tmux_installed() -> bool:
    return shutil.which("tmux") is not None


# 【讲解】注意 detect_backend() 目前是个"恒返回 IN_PROCESS"的简化版本——
# 真正的探测逻辑在下面的 detect_pane_backend()（按环境变量判断是否已经
# 身处 tmux/iTerm2 会话，或者系统装没装 tmux），但当前代码路径里没有
# 谁调用它，说明 pane 后端的自动探测暂时被搁置了，一律走进程内模式。
def detect_backend(
    teammate_mode: str = "",
    is_interactive: bool = True,
) -> BackendType:
    """Default to in-process for real-time progress tracking."""
    return BackendType.IN_PROCESS


def detect_pane_backend(
    teammate_mode: str = "",
    is_interactive: bool = True,
) -> BackendType:
    """Detect pane backend when user explicitly requests tmux."""
    if teammate_mode == "in-process" or not is_interactive:
        return BackendType.IN_PROCESS

    if _in_tmux_session():
        return BackendType.TMUX

    if _in_iterm2() and _it2_available():
        return BackendType.ITERM2

    if _tmux_installed():
        return BackendType.TMUX

    raise BackendDetectionError(
        "No suitable terminal backend found for Agent Team.\n"
        "Install one of the following:\n"
        "  - tmux: brew install tmux\n"
        "  - iTerm2 + it2 CLI: https://iterm2.com/utilities/it2check\n"
        "Or set 'teammate_mode: \"in-process\"' in config.yaml to use in-process backend."
    )
