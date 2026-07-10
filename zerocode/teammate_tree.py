"""团队成员进度树渲染组件。

将 team lead 与各 teammate 的运行状态、工具次数和 token 统计显示在 TUI 中。
"""

from __future__ import annotations

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text

from zerocode.teams.progress import TeammateProgress


# 【讲解】和前面几个 InlineXxxWidget 不同，这个用的是 Textual 的
# `reactive()` 属性——teammates/leader_tokens 一旦被外部代码赋新值，
# Textual 会自动检测到变化并重新调用 render()，不需要像其他弹窗那样手动
# `_refresh()`。适合这种"数据由外部（团队进度轮询）持续推送更新，UI 只是
# 被动展示"的场景。render() 返回的是 rich.Text 对象（拼接不同颜色/样式的
# 片段），这是 Textual 底层依赖的 Rich 库的富文本构建方式，和别处用
# `[bold]...[/]` 标记字符串是两种不同的富文本写法（这里选 Text 对象是因为
# 要动态拼接可变数量的行，用对象 API 比字符串拼接更不容易出错）。
class TeammateTree(Widget):
    """Renders a tree of teammate progress below the spinner."""

    DEFAULT_CSS = """
    TeammateTree {
        height: auto;
        margin: 0 1;
    }
    """

    teammates: reactive[list[TeammateProgress]] = reactive(list, layout=True)
    leader_tokens: reactive[int] = reactive(0)

    def render(self) -> Text:
        if not self.teammates:
            return Text("")

        lines = Text()
        # Leader line
        lines.append("  ┌─ ", style="dim")
        lines.append("team-lead", style="cyan")
        lines.append(": thinking…", style="dim")
        if self.leader_tokens > 0:
            lines.append(
                f" · {TeammateProgress.format_tokens(self.leader_tokens)} tokens",
                style="dim",
            )
        lines.append("\n")

        for i, p in enumerate(self.teammates):
            is_last = i == len(self.teammates) - 1
            connector = "  └─ " if is_last else "  ├─ "

            lines.append(connector, style="dim")
            lines.append(f"@{p.name}", style="cyan")
            lines.append(": ")

            if p.status == "completed":
                lines.append("completed", style="green")
            elif p.status == "failed":
                lines.append("failed", style="red")
            elif p.status == "idle":
                lines.append("idle", style="dim")
            else:
                lines.append(f"{p.activity_summary}…", style="dim")

            lines.append(
                f" · {p.tool_use_count} tools"
                f" · {TeammateProgress.format_tokens(p.token_count)} tokens",
                style="dim",
            )
            if not is_last:
                lines.append("\n")

        return lines
