from __future__ import annotations

from pathlib import Path

MAX_INCLUDE_DEPTH = 5
INCLUDE_PREFIX = "@include "


# 【讲解】"instructions" 就是 ZeroCode.md（你在这个项目里看到的 ZEROCODE.md）
# 这类项目指令文件的加载器。process_includes 支持一个简单的 `@include 路径`
# 语法：递归展开被包含的文件内容（有深度上限防止 include 死循环，也会
# 拒绝越出项目根目录的路径，防止读到不该读的文件）。load_instructions 按
# 项目根、项目 .zerocode 目录、用户主目录三处依次查找 ZeroCode.md 并拼接。
def process_includes(
    content: str,
    base_dir: Path,
    project_root: Path,
    depth: int = 0,
) -> str:
    if depth >= MAX_INCLUDE_DEPTH:
        return content

    resolved_root = project_root.resolve()
    lines = content.split("\n")
    result: list[str] = []


    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(INCLUDE_PREFIX):
            result.append(line)
            continue

        rel_path = stripped[len(INCLUDE_PREFIX) :].strip()
        abs_path = (base_dir / rel_path).resolve()

        try:
            abs_path.relative_to(resolved_root)
        except ValueError:
            result.append("<!-- @include blocked: path outside project -->")
            continue

        if not abs_path.exists() or not abs_path.is_file():
            result.append("<!-- @include skipped: file not found -->")
            continue

        included = abs_path.read_text(encoding="utf-8")
        processed = process_includes(included, abs_path.parent, project_root, depth + 1)
        result.append(processed)

    return "\n".join(result)


def load_instructions(project_root: str) -> str:
    root = Path(project_root)
    home = Path.home()

    paths = [
        root / "ZeroCode.md",
        # 注：这里的目录段统一成小写 .zerocode（与其他子系统一致）；
        # "ZeroCode.md" 文件名本身的大小写是另一个独立问题，不在本次改动范围内。
        root / ".zerocode" / "ZeroCode.md",
        home / ".zerocode" / "ZeroCode.md",
    ]

    sections: list[str] = []
    for path in paths:
        if path.exists() and path.is_file():
            content = path.read_text(encoding="utf-8")
            processed = process_includes(content, path.parent, root)
            sections.append(processed)

    return "\n---\n".join(sections)

