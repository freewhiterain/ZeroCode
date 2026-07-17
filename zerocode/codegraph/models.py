"""代码图谱内部数据模型。

解析器、解析器后处理、存储层和格式化层都通过这里的 dataclass 交换数据，
避免每个模块各自约定一套容易漂移的字典结构。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


SymbolKind = Literal["file", "class", "function", "method"]
Confidence = Literal["extracted", "inferred"]


@dataclass(frozen=True)
class Symbol:
    id: str
    kind: SymbolKind
    name: str
    qualified_name: str
    file_path: str
    start_line: int
    end_line: int
    parent_id: str | None = None
    signature: str = ""
    docstring: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Symbol":
        return cls(**data)


@dataclass(frozen=True)
class CallFact:
    caller_id: str
    callee_name: str
    receiver: str | None
    file_path: str
    line: int
    column: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CallFact":
        return cls(**data)


@dataclass(frozen=True)
class ImportFact:
    source_file: str
    module: str
    imported_name: str | None
    local_name: str
    line: int
    level: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImportFact":
        return cls(**data)


@dataclass(frozen=True)
class ParseIssue:
    file_path: str
    message: str
    severity: Literal["warning", "error"] = "warning"
    partial: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParseIssue":
        return cls(**data)


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    kind: Literal["contains", "calls", "imports"]
    confidence: Confidence = "extracted"
    resolution: str = ""
    call_sites: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["call_sites"] = list(self.call_sites)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphEdge":
        copy = dict(data)
        copy["call_sites"] = tuple(copy.get("call_sites", []))
        return cls(**copy)


@dataclass
class ParseResult:
    file_path: str
    symbols: list[Symbol] = field(default_factory=list)
    call_facts: list[CallFact] = field(default_factory=list)
    import_facts: list[ImportFact] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)


@dataclass(frozen=True)
class FileState:
    size: int
    mtime_ns: int
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileState":
        return cls(**data)


@dataclass(frozen=True)
class IndexStats:
    files: int
    symbols: int
    edges: int
    issues: int
    indexed_at: str
    generation_id: str
