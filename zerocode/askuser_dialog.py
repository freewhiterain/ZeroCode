"""AskUser 工具的内联交互组件。

负责在聊天区域中渲染单选/多选/自定义输入问题，并把用户选择转换为
工具调用可消费的答案字典。
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static


# 【讲解】UI 层这几个 InlineXxxWidget（本文件 + permission_dialog.py +
# plan_dialog.py + session_dialog.py）都是同一套 Textual 组件模式：
#   - 继承 Vertical（垂直布局容器）、can_focus=True 让它能接收键盘事件
#   - compose() 返回要渲染的子组件（这里只有一个 Static 文本块）
#   - 状态（光标位置、已选项等）存成普通实例属性，任何变化后手动调用
#     _refresh() 重新生成文本并塞回 Static——不是 Textual 的响应式属性
#     （reactive），而是"手动重渲染"，更简单直接
#   - BINDINGS 声明键位 → action_xxx 方法，Textual 自动把按键路由过去
#   - 交互结束时 post_message(self.Responded(...)) 把结果往上抛给父组件
#     （app.py 监听这个消息，再把答案喂回 asyncio.Future——呼应
#     tools/ask_user.py 里 execute() 的 await future）
# 这个文件是最复杂的一个：要支持多问题之间 Tab 切换、单选/多选、外加一个
# "Other" 自定义输入项，本质是纯文本手动排版 + 键盘状态机。
class InlineAskUserWidget(Vertical, can_focus=True):
    """内联的 AskUser 组件，支持多问题之间的 Tab 切换导航。

    与 Go 版 TUI 保持一致：带 ☐/☑ 勾选标记的导航栏、光标导航、
    多选（MultiSelect）切换、"Other" 自定义输入，以及复核/提交视图。
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Up", priority=True),
        Binding("down", "cursor_down", "Down", priority=True),
        Binding("enter", "select", "Select", priority=True),
        Binding("tab", "next_q", "Next", priority=True),
        Binding("shift+tab", "prev_q", "Prev", priority=True),
        Binding("space", "toggle", "Toggle", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    class Responded(Message):
        def __init__(self, answers: dict[str, str] | None) -> None:
            super().__init__()
            self.answers = answers


    def __init__(self, questions: list[dict], **kwargs) -> None:
        super().__init__(id="askuser-inline", **kwargs)
        self._questions = questions
        self._q_idx = 0
        n = len(questions)
        self._cursors = [0] * n
        self._selected: list[dict[int, bool]] = [{} for _ in range(n)]
        self._others = [""] * n
        self._answered: dict[int, str] = {}
        self._on_submit = False
        self._submit_idx = 0


    def compose(self) -> ComposeResult:
        yield Static(self._build_content(), id="askuser-content")

    def on_mount(self) -> None:
        self.focus()

    def _option_count(self, q_idx: int) -> int:
        return len(self._questions[q_idx].get("options", [])) + 1  # +1 是为 Other 选项预留的

    def _build_content(self) -> str:
        if self._on_submit:
            return self._render_submit()
        return self._render_question()

    def _render_question(self) -> str:
        lines = []
        multi = len(self._questions) > 1

        if multi:
            nav = self._render_nav_bar()
            lines.append(nav)
            lines.append("")

        q = self._questions[self._q_idx]
        header = q.get("question", q.get("message", f"Question {self._q_idx + 1}"))
        lines.append(f" [bold color(99)]{header}[/]\n")

        options = q.get("options", [])
        is_multi = q.get("multiSelect", False)
        cursor = self._cursors[self._q_idx]

        for i, opt in enumerate(options):
            label = opt.get("label", str(opt)) if isinstance(opt, dict) else str(opt)
            desc = opt.get("description", "") if isinstance(opt, dict) else ""

            prefix = " ❯ " if i == cursor else "   "
            bold = "[bold]" if i == cursor else ""
            end_bold = "[/]" if i == cursor else ""

            if is_multi:
                check = "● " if self._selected[self._q_idx].get(i) else "○ "
            else:
                check = ""

            desc_part = f" — [dim]{desc}[/]" if desc else ""
            lines.append(f"{prefix}{check}{bold}{label}{end_bold}{desc_part}")

        # "Other" 选项
        other_idx = len(options)
        prefix = " ❯ " if cursor == other_idx else "   "
        bold = "[bold]" if cursor == other_idx else ""
        end_bold = "[/]" if cursor == other_idx else ""
        lines.append(f"{prefix}{bold}Other{end_bold}")

        if cursor == other_idx:
            text = self._others[self._q_idx]
            display = text if text else "[dim]Type your answer here...[/]"
            lines.append(f"      {display}█")

        if is_multi:
            lines.append("\n      [dim]space to toggle, enter to confirm[/]")
        else:
            lines.append("\n      [dim]enter to confirm[/]")

        return "\n".join(lines)

    def _render_nav_bar(self) -> str:
        parts = []
        for i, q in enumerate(self._questions):
            header = q.get("header", f"Q{i+1}")
            check = "☑" if i in self._answered else "☐"
            if i == self._q_idx and not self._on_submit:
                parts.append(f"[bold reverse] {header} {check} [/]")
            else:
                parts.append(f" {header} {check} ")
        submit_part = "[bold reverse] ✓ Submit [/]" if self._on_submit else " ✓ Submit "
        parts.append(submit_part)
        left = "[bold]←[/]" if self._q_idx > 0 else "[dim]←[/]"
        right = "[bold]→[/]"
        return f" {left} {'|'.join(parts)} {right}"

    def _render_submit(self) -> str:
        lines = ["\n [bold color(99)]Review your answers:[/]\n"]
        for i, q in enumerate(self._questions):
            header = q.get("header", q.get("question", f"Q{i+1}"))
            ans = self._answered.get(i, "")
            if ans:
                lines.append(f"   {header}: {ans}")
            else:
                lines.append(f"   {header}: [dim](not answered)[/]")
        lines.append("")
        for j, label in enumerate(["Submit answers", "Cancel"]):
            if j == self._submit_idx:
                lines.append(f" [bold cyan]❯[/] [bold]{label}[/]")
            else:
                lines.append(f"   [dim]{label}[/]")
        return "\n".join(lines)

    def _refresh(self) -> None:
        self.query_one("#askuser-content", Static).update(self._build_content())

    def _save_current_answer(self) -> None:
        """把当前问题的光标/多选/自定义输入状态写入答案缓存。"""
        q = self._questions[self._q_idx]
        options = q.get("options", [])
        cursor = self._cursors[self._q_idx]
        is_multi = q.get("multiSelect", False)

        if cursor == len(options):  # "Other"（自定义输入）
            self._answered[self._q_idx] = self._others[self._q_idx] or "Other"
        elif is_multi:
            selected = [
                (opt.get("label", str(opt)) if isinstance(opt, dict) else str(opt))
                for i, opt in enumerate(options)
                if self._selected[self._q_idx].get(i)
            ]
            if not selected:
                opt = options[cursor]
                selected = [opt.get("label", str(opt)) if isinstance(opt, dict) else str(opt)]
            self._answered[self._q_idx] = ", ".join(selected)
        else:
            opt = options[cursor]
            self._answered[self._q_idx] = opt.get("label", str(opt)) if isinstance(opt, dict) else str(opt)

    def action_cursor_up(self) -> None:
        if self._on_submit:
            if self._submit_idx > 0:
                self._submit_idx -= 1
                self._refresh()
        else:
            if self._cursors[self._q_idx] > 0:
                self._cursors[self._q_idx] -= 1
                self._refresh()

    def action_cursor_down(self) -> None:
        if self._on_submit:
            if self._submit_idx < 1:
                self._submit_idx += 1
                self._refresh()
        else:
            max_c = self._option_count(self._q_idx) - 1
            if self._cursors[self._q_idx] < max_c:
                self._cursors[self._q_idx] += 1
                self._refresh()

    def action_next_q(self) -> None:
        if self._on_submit or len(self._questions) <= 1:
            return
        if self._q_idx < len(self._questions) - 1:
            self._q_idx += 1
        else:
            self._on_submit = True
            self._submit_idx = 0
        self._refresh()

    def action_prev_q(self) -> None:
        if self._on_submit:
            self._on_submit = False
            self._q_idx = len(self._questions) - 1
            self._refresh()
        elif self._q_idx > 0:
            self._q_idx -= 1
            self._refresh()


    def action_toggle(self) -> None:
        if self._on_submit:
            return
        q = self._questions[self._q_idx]
        if not q.get("multiSelect", False):
            return
        cursor = self._cursors[self._q_idx]
        options = q.get("options", [])
        if cursor < len(options):
            self._selected[self._q_idx][cursor] = not self._selected[self._q_idx].get(cursor, False)
            self._refresh()

    def action_select(self) -> None:
        if self._on_submit:
            if self._submit_idx == 0:
                answers = {}
                for i, q in enumerate(self._questions):
                    key = q.get("question", q.get("message", f"q{i}"))
                    answers[key] = self._answered.get(i, "")
                self.post_message(self.Responded(answers))
            else:
                self.post_message(self.Responded(None))
        else:
            self._save_current_answer()
            if len(self._questions) == 1:
                answers = {}
                q = self._questions[0]
                key = q.get("question", q.get("message", "q0"))
                answers[key] = self._answered.get(0, "")
                self.post_message(self.Responded(answers))
            elif self._q_idx < len(self._questions) - 1:
                self._q_idx += 1
                self._refresh()
            else:
                self._on_submit = True
                self._submit_idx = 0
                self._refresh()


    def action_cancel(self) -> None:
        self.post_message(self.Responded(None))

    def on_key(self, event) -> None:
        if self._on_submit:
            return
        cursor = self._cursors[self._q_idx]
        options = self._questions[self._q_idx].get("options", [])
        if cursor != len(options):  # 当前光标不在 "Other" 上
            return
        key = event.key
        if key == "backspace":
            if self._others[self._q_idx]:
                self._others[self._q_idx] = self._others[self._q_idx][:-1]
                self._refresh()
            event.stop()
        elif len(key) == 1 and key.isprintable():
            self._others[self._q_idx] += key
            self._refresh()
            event.stop()
