"""文件路径沙箱检查。

PathSandbox 将相对路径锚定到项目根目录，并在解析符号链接后确认
访问目标位于允许根目录内，防止文件工具越权读写项目外路径。
"""

from __future__ import annotations

import tempfile
from pathlib import Path


# 【讲解】"沙箱"防的是模型被诱导（或自己出 bug）去读写项目目录之外的
# 文件，比如 `../../etc/passwd` 这种路径穿越。做法是把路径 resolve()
# 成绝对真实路径（会展开 `..` 和符号链接），再检查它是否落在允许的根
# 目录列表（项目根 + 系统临时目录）之内。resolve(strict=True) 要求路径
# 必须存在；对于还不存在的新文件（比如 WriteFile 要创建的路径），下面
# 那段 while 循环会往上找到第一个"确实存在"的祖先目录，先解析它，再把
# 剩余的相对部分拼回去——这样即使目标文件本身不存在也能正确判断范围。
class PathSandbox:


    def __init__(
        self,
        project_root: str,
        extra_allowed: list[str] | None = None,
    ) -> None:
        root = Path(project_root).resolve()
        self._allowed_roots: list[Path] = [root, Path(tempfile.gettempdir()).resolve()]
        if extra_allowed:
            for p in extra_allowed:
                self._allowed_roots.append(Path(p).resolve())


    @property
    def project_root(self) -> Path:
        return self._allowed_roots[0]


    def check(self, path: str) -> tuple[bool, str]:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.project_root / p
        abs_path = p.absolute()

        try:
            real_path = abs_path.resolve(strict=True)
        except OSError:
            ancestor = abs_path
            while not ancestor.exists():
                parent = ancestor.parent
                if parent == ancestor:
                    return False, f"无法解析路径: {path}"
                ancestor = parent
            try:
                resolved_ancestor = ancestor.resolve(strict=True)
            except OSError:
                return False, f"无法解析路径: {path}"
            real_path = resolved_ancestor / abs_path.relative_to(ancestor)

        for root in self._allowed_roots:
            try:
                real_path.relative_to(root)
                return True, ""
            except ValueError:
                continue

        return False, f"路径 {path} 超出沙箱范围"
