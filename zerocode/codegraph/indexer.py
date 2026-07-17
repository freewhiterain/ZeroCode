"""代码图谱的全量构建和惰性增量刷新。"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from zerocode.codegraph.models import FileState, IndexStats, ParseIssue, ParseResult
from zerocode.codegraph.parser import parse_python_file
from zerocode.codegraph.resolver import resolve_edges
from zerocode.codegraph.store import NetworkXGraphStore
from zerocode.tools.base import SKIP_DIRS


INDEX_RELATIVE_PATH = Path(".zerocode") / "codegraph" / "graph.json"
EXTRA_SKIP_DIRS = {".zerocode", ".codegraph", ".gitnexus", "graphify-out"}


@dataclass(frozen=True)
class IndexUpdate:
    stats: IndexStats
    added: int = 0
    modified: int = 0
    removed: int = 0
    reparsed: int = 0


def resolve_project_root(start: str | Path) -> Path:
    candidate = Path(start).resolve()
    if candidate.is_file():
        candidate = candidate.parent
    try:
        proc = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    return candidate


def _safe_source_path(root: Path, relative_path: str) -> Path | None:
    candidate = root / Path(relative_path)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def _is_skipped(relative: Path) -> bool:
    skipped = SKIP_DIRS | EXTRA_SKIP_DIRS
    return any(part in skipped for part in relative.parts)


def scan_python_files(root: Path) -> list[str]:
    """返回已跟踪文件和未跟踪但未忽略的 Python 文件。"""

    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.py"],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if proc.returncode == 0:
            files = []
            for raw in proc.stdout.split(b"\0"):
                if not raw:
                    continue
                rel = raw.decode("utf-8", errors="surrogateescape").replace("\\", "/")
                rel_path = Path(rel)
                if not _is_skipped(rel_path) and _safe_source_path(root, rel) is not None:
                    files.append(rel)
            return sorted(set(files))
    except (OSError, subprocess.SubprocessError):
        pass

    files = []
    for path in root.rglob("*.py"):
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if not _is_skipped(rel) and _safe_source_path(root, rel.as_posix()) is not None:
            files.append(rel.as_posix())
    return sorted(set(files))


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class GraphIndexer:
    def __init__(self, root: str | Path) -> None:
        self.root = resolve_project_root(root)
        self.index_path = self.root / INDEX_RELATIVE_PATH

    def exists(self) -> bool:
        return self.index_path.is_file()

    def load(self) -> NetworkXGraphStore:
        return NetworkXGraphStore.load(self.index_path, self.root)

    def _parse(self, relative_path: str) -> tuple[ParseResult, FileState] | None:
        source_path = _safe_source_path(self.root, relative_path)
        if source_path is None:
            return None
        try:
            stat = source_path.stat()
            content = source_path.read_bytes()
        except OSError:
            return None
        return parse_python_file(relative_path, content), FileState(
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            content_hash=_hash(content),
        )

    def build_full(
        self,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> IndexUpdate:
        files = scan_python_files(self.root)
        store = NetworkXGraphStore(self.root)
        for index, relative_path in enumerate(files, 1):
            on_progress and on_progress(index, len(files), relative_path)
            parsed = self._parse(relative_path)
            if parsed is None:
                store.issues.append(ParseIssue(relative_path, "file could not be read", "error"))
                continue
            result, state = parsed
            store.replace_file(result, state)
        store.replace_edges(resolve_edges(store.all_symbols(), store.call_facts, store.import_facts))
        store.save_atomic(self.index_path)
        return IndexUpdate(stats=store.stats(), added=len(store.file_states), reparsed=len(store.file_states))

    def refresh(self) -> IndexUpdate:
        store = self.load()
        current_files = scan_python_files(self.root)
        current_set = set(current_files)
        removed = sorted(set(store.file_states) - current_set)
        for file_path in removed:
            store.remove_file(file_path)

        added = modified = reparsed = 0
        graph_changed = bool(removed)
        metadata_changed = False
        for relative_path in current_files:
            source_path = _safe_source_path(self.root, relative_path)
            if source_path is None:
                continue
            try:
                stat = source_path.stat()
            except OSError:
                continue
            previous = store.file_states.get(relative_path)
            if previous and previous.size == stat.st_size and previous.mtime_ns == stat.st_mtime_ns:
                continue
            try:
                content = source_path.read_bytes()
            except OSError:
                continue
            digest = _hash(content)
            state = FileState(stat.st_size, stat.st_mtime_ns, digest)
            if previous and previous.content_hash == digest:
                store.file_states[relative_path] = state
                metadata_changed = True
                continue
            result = parse_python_file(relative_path, content)
            store.replace_file(result, state)
            reparsed += 1
            graph_changed = True
            if previous is None:
                added += 1
            else:
                modified += 1

        # 【讲解】未变化文件不用重新 parse，但所有保存下来的 CallFact 会重新
        # 解析一次目标，因而被修改文件的跨文件入边不会随着旧节点删除而丢失。
        if graph_changed:
            store.replace_edges(resolve_edges(store.all_symbols(), store.call_facts, store.import_facts))
        if graph_changed or metadata_changed:
            store.save_atomic(self.index_path)
        return IndexUpdate(
            stats=store.stats(),
            added=added,
            modified=modified,
            removed=len(removed),
            reparsed=reparsed,
        )

    def status(self) -> IndexStats | None:
        return self.load().stats() if self.exists() else None
