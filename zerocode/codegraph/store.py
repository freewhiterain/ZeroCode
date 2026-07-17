"""代码图谱存储抽象与 NetworkX/JSON 实现。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import networkx as nx

from zerocode.codegraph.models import (
    CallFact,
    FileState,
    GraphEdge,
    ImportFact,
    IndexStats,
    ParseIssue,
    ParseResult,
    Symbol,
)


SCHEMA_VERSION = 1


class IndexCorruptError(RuntimeError):
    """索引无法安全加载。"""


class GraphStore(ABC):
    @abstractmethod
    def replace_file(self, result: ParseResult, state: FileState) -> None: ...

    @abstractmethod
    def remove_file(self, file_path: str) -> None: ...

    @abstractmethod
    def replace_edges(self, edges: list[GraphEdge]) -> None: ...

    @abstractmethod
    def find_symbols(self, name: str) -> list[Symbol]: ...

    @abstractmethod
    def callers_of(self, symbol_id: str) -> list[tuple[Symbol, GraphEdge]]: ...

    @abstractmethod
    def callees_of(self, symbol_id: str) -> list[tuple[Symbol, GraphEdge]]: ...

    @abstractmethod
    def save_atomic(self, path: Path) -> None: ...


class NetworkXGraphStore(GraphStore):
    """把 NetworkX 限制在存储层内部，便于以后替换为 SQLite。"""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.graph = nx.DiGraph()
        self.symbols: dict[str, Symbol] = {}
        self.call_facts: list[CallFact] = []
        self.import_facts: list[ImportFact] = []
        self.issues: list[ParseIssue] = []
        self.file_states: dict[str, FileState] = {}
        self.indexed_at = ""
        self.generation_id = ""
        self._lock = threading.RLock()

    def replace_file(self, result: ParseResult, state: FileState) -> None:
        with self._lock:
            self.remove_file(result.file_path)
            for symbol in result.symbols:
                self.symbols[symbol.id] = symbol
                self.graph.add_node(symbol.id)
            self.call_facts.extend(result.call_facts)
            self.import_facts.extend(result.import_facts)
            self.issues.extend(result.issues)
            self.file_states[result.file_path] = state

    def remove_file(self, file_path: str) -> None:
        with self._lock:
            node_ids = [sid for sid, symbol in self.symbols.items() if symbol.file_path == file_path]
            self.graph.remove_nodes_from(node_ids)
            for sid in node_ids:
                self.symbols.pop(sid, None)
            self.call_facts = [fact for fact in self.call_facts if fact.file_path != file_path]
            self.import_facts = [fact for fact in self.import_facts if fact.source_file != file_path]
            self.issues = [issue for issue in self.issues if issue.file_path != file_path]
            self.file_states.pop(file_path, None)

    def replace_edges(self, edges: list[GraphEdge]) -> None:
        with self._lock:
            self.graph.remove_edges_from(list(self.graph.edges()))
            for edge in edges:
                if edge.source in self.symbols and edge.target in self.symbols:
                    self.graph.add_edge(edge.source, edge.target, edge=edge)

    def all_symbols(self) -> list[Symbol]:
        return list(self.symbols.values())

    def all_edges(self) -> list[GraphEdge]:
        return [data["edge"] for _, _, data in self.graph.edges(data=True) if "edge" in data]

    def find_symbols(self, name: str) -> list[Symbol]:
        exact = [
            symbol for symbol in self.symbols.values()
            if symbol.kind != "file" and (symbol.name == name or symbol.qualified_name == name)
        ]
        return sorted(exact, key=lambda symbol: (symbol.file_path, symbol.start_line, symbol.kind))

    def get_symbol(self, symbol_id: str) -> Symbol | None:
        return self.symbols.get(symbol_id)

    def callers_of(self, symbol_id: str) -> list[tuple[Symbol, GraphEdge]]:
        result: list[tuple[Symbol, GraphEdge]] = []
        if symbol_id not in self.graph:
            return result
        for source, _, data in self.graph.in_edges(symbol_id, data=True):
            edge = data.get("edge")
            symbol = self.symbols.get(source)
            if symbol and edge and edge.kind == "calls":
                result.append((symbol, edge))
        return sorted(result, key=lambda pair: (pair[0].file_path, pair[0].start_line))

    def callees_of(self, symbol_id: str) -> list[tuple[Symbol, GraphEdge]]:
        result: list[tuple[Symbol, GraphEdge]] = []
        if symbol_id not in self.graph:
            return result
        for _, target, data in self.graph.out_edges(symbol_id, data=True):
            edge = data.get("edge")
            symbol = self.symbols.get(target)
            if symbol and edge and edge.kind == "calls":
                result.append((symbol, edge))
        return sorted(result, key=lambda pair: (pair[0].file_path, pair[0].start_line))

    def stats(self) -> IndexStats:
        return IndexStats(
            files=len(self.file_states),
            symbols=sum(symbol.kind != "file" for symbol in self.symbols.values()),
            edges=self.graph.number_of_edges(),
            issues=len(self.issues),
            indexed_at=self.indexed_at,
            generation_id=self.generation_id,
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "generation_id": self.generation_id,
            "indexed_at": self.indexed_at,
            "root": str(self.root),
            "file_states": {path: state.to_dict() for path, state in sorted(self.file_states.items())},
            "symbols": [symbol.to_dict() for symbol in sorted(self.symbols.values(), key=lambda s: s.id)],
            "edges": [edge.to_dict() for edge in sorted(self.all_edges(), key=lambda e: (e.kind, e.source, e.target))],
            "call_facts": [fact.to_dict() for fact in self.call_facts],
            "import_facts": [fact.to_dict() for fact in self.import_facts],
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def save_atomic(self, path: Path) -> None:
        """在同目录写临时文件后原子替换，失败时保留上一代索引。"""

        with self._lock:
            self.indexed_at = datetime.now(timezone.utc).isoformat()
            self.generation_id = str(uuid.uuid4())
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix="graph-", suffix=".tmp", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                    json.dump(self._payload(), stream, ensure_ascii=False, separators=(",", ":"))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_name, path)
            except Exception:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
                raise

    @classmethod
    def load(cls, path: Path, root: Path) -> "NetworkXGraphStore":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IndexCorruptError(f"Cannot load code graph index: {exc}") from exc
        if data.get("schema_version") != SCHEMA_VERSION:
            raise IndexCorruptError(
                f"Unsupported code graph schema: {data.get('schema_version')!r}; rebuild required"
            )
        if not data.get("generation_id"):
            raise IndexCorruptError("Code graph index has no generation_id; rebuild required")

        store = cls(root)
        try:
            store.symbols = {symbol.id: symbol for symbol in map(Symbol.from_dict, data.get("symbols", []))}
            store.call_facts = [CallFact.from_dict(item) for item in data.get("call_facts", [])]
            store.import_facts = [ImportFact.from_dict(item) for item in data.get("import_facts", [])]
            store.issues = [ParseIssue.from_dict(item) for item in data.get("issues", [])]
            store.file_states = {
                file_path: FileState.from_dict(item)
                for file_path, item in data.get("file_states", {}).items()
            }
            store.indexed_at = str(data.get("indexed_at", ""))
            store.generation_id = str(data["generation_id"])
            store.graph.add_nodes_from(store.symbols)
            store.replace_edges([GraphEdge.from_dict(item) for item in data.get("edges", [])])
        except (KeyError, TypeError, ValueError) as exc:
            raise IndexCorruptError(f"Invalid code graph index data: {exc}") from exc
        return store
