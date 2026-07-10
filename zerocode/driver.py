"""Textual 终端驱动适配。

该模块提供禁用 alternate screen 的驱动，让 TUI 渲染结果保留在主终端
scrollback 中，便于用户回看历史输出。
"""

from __future__ import annotations

import os
import sys

if sys.platform == "win32":
    from textual.drivers.windows_driver import WindowsDriver as _BaseDriver
else:
    from textual.drivers.linux_driver import LinuxDriver as _BaseDriver


# 【讲解】背景知识：终端程序（vim、htop 这类）通常会切换到"备用屏"
# （alternate screen buffer）——退出后终端画面恢复原样，仿佛程序从没运行
# 过。Textual 默认也这么干。但 ZeroCode 想要的效果和 Claude Code 一样：
# 退出后聊天记录还留在终端里能往上翻。这个类通过拦截并删除控制转义序列
# `\x1b[?1049h`（进入备用屏）和 `\x1b[?1049l`（退出备用屏），骗过终端
# "一直待在主屏幕"，配合 start_application_mode 里先打印一堆换行把旧内容
# 推进 scrollback，实现"TUI 内容仍会被保留在终端历史里"的效果。
class NoAltScreenDriver(_BaseDriver):
    """跳过备用屏（alternate screen）的 driver，让输出保留在主终端的
    滚动回看（scrollback）区域中——与 Claude Code 的渲染行为保持一致。
    自动根据平台选择 LinuxDriver 或 WindowsDriver 作为基类。

    原理：去掉 alt screen 切换码，并在进入应用模式时输出足够多的空行，
    将已有终端内容推入 scrollback，Textual 在"新页面"上渲染。"""

    def start_application_mode(self):
        try:
            rows = os.get_terminal_size().lines
        except OSError:
            rows = 24
        # 在 Textual 接管终端之前，用换行把已有内容推入 scrollback
        sys.stdout.write("\n" * rows)
        sys.stdout.flush()
        super().start_application_mode()

    def write(self, data: str) -> None:
        if "\x1b[?1049h" in data:
            data = data.replace("\x1b[?1049h", "")
        if "\x1b[?1049l" in data:
            data = data.replace("\x1b[?1049l", "")
        if data:
            super().write(data)
