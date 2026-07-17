"""Python tree-sitter 解析层。

本模块只负责把单个文件变成符号、导入和原始调用事实；跨文件调用目标的
判定刻意留给 resolver.py，避免语法提取阶段凭同名关系编造调用边。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Iterable

from tree_sitter import Language, Parser, Query, QueryCursor
import tree_sitter_python

from zerocode.codegraph.models import CallFact, ImportFact, ParseIssue, ParseResult, Symbol


PYTHON_LANGUAGE = Language(tree_sitter_python.language())

# 【讲解】Query 像一组声明式的 AST 选择器。所有捕获先统一成少量语义标签，
# 后续代码不需要递归遍历整棵树来猜哪些节点是定义、调用或导入。
PYTHON_QUERY_SOURCE = r"""
(class_definition) @definition.class
(function_definition) @definition.function
(call) @reference.call
(import_statement) @import.statement
(import_from_statement) @import.statement
"""


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _capture_nodes(root: Any) -> dict[str, list[Any]]:
    query = Query(PYTHON_LANGUAGE, PYTHON_QUERY_SOURCE)
    captures = QueryCursor(query).captures(root)
    if isinstance(captures, dict):
        return {str(name): list(nodes) for name, nodes in captures.items()}

    # 兼容少数返回 ``[(node, capture_name), ...]`` 的 0.25 绑定构建。
    grouped: dict[str, list[Any]] = {}
    for item in captures:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        node, name = item
        grouped.setdefault(str(name), []).append(node)
    return grouped


def _signature(node: Any, source: bytes) -> str:
    body = node.child_by_field_name("body")
    end_byte = body.start_byte if body is not None else node.end_byte
    header_bytes = source[node.start_byte:end_byte].rstrip()
    # The last colon terminates the definition header.  Splitting on the first
    # colon breaks annotations such as ``def f(value: int)``.
    if header_bytes.endswith(b":"):
        header_bytes = header_bytes[:-1]
    header = header_bytes.decode("utf-8", errors="replace").strip()
    return " ".join(header.split())


def _docstring(node: Any, source: bytes) -> str:
    body = node.child_by_field_name("body")
    first = body.named_child(0) if body is not None and body.named_child_count else None
    if first is None or first.type != "expression_statement" or not first.named_child_count:
        return ""
    literal = first.named_child(0)
    if literal.type not in {"string", "concatenated_string"}:
        return ""
    try:
        value = ast.literal_eval(_node_text(literal, source))
    except (SyntaxError, ValueError):
        return ""
    return " ".join(value.split()) if isinstance(value, str) else ""


def _symbol_id(file_path: str, kind: str, qualified_name: str, start_line: int) -> str:
    return f"{file_path}::{kind}::{qualified_name}::{start_line}"


def _parse_import_node(node: Any, source: bytes, file_path: str) -> list[ImportFact]:
    try:
        statement = ast.parse(_node_text(node, source)).body[0]
    except (SyntaxError, IndexError):
        return []

    facts: list[ImportFact] = []
    line = node.start_point.row + 1
    if isinstance(statement, ast.Import):
        for alias in statement.names:
            facts.append(ImportFact(
                source_file=file_path,
                module=alias.name,
                imported_name=None,
                local_name=alias.asname or alias.name.split(".")[0],
                line=line,
            ))
    elif isinstance(statement, ast.ImportFrom):
        module = statement.module or ""
        for alias in statement.names:
            if alias.name == "*":
                continue
            facts.append(ImportFact(
                source_file=file_path,
                module=module,
                imported_name=alias.name,
                local_name=alias.asname or alias.name,
                line=line,
                level=statement.level,
            ))
    return facts


def _nearest_container(node: Any, definitions: Iterable[tuple[Any, Symbol]]) -> Symbol | None:
    candidates = [
        symbol for def_node, symbol in definitions
        if def_node.start_byte <= node.start_byte and node.end_byte <= def_node.end_byte
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda symbol: symbol.end_line - symbol.start_line)


def parse_python_file(file_path: str, source: bytes) -> ParseResult:
    """解析单个 Python 文件；任何失败都被隔离在返回值中。"""

    result = ParseResult(file_path=file_path)
    try:
        tree = Parser(PYTHON_LANGUAGE).parse(source)
        captures = _capture_nodes(tree.root_node)
    except Exception as exc:
        result.issues.append(ParseIssue(
            file_path=file_path,
            message=f"tree-sitter parse failed: {type(exc).__name__}: {exc}",
            severity="error",
        ))
        return result

    if tree.root_node.has_error:
        result.issues.append(ParseIssue(
            file_path=file_path,
            message="tree-sitter recovered from syntax errors; results may be incomplete",
            partial=True,
        ))

    line_count = max(1, source.count(b"\n") + 1)
    file_symbol = Symbol(
        id=f"file::{file_path}",
        kind="file",
        name=Path(file_path).name,
        qualified_name=file_path,
        file_path=file_path,
        start_line=1,
        end_line=line_count,
    )
    result.symbols.append(file_symbol)

    definition_nodes: list[tuple[Any, str]] = []
    definition_nodes.extend((node, "class") for node in captures.get("definition.class", []))
    definition_nodes.extend((node, "function") for node in captures.get("definition.function", []))
    definition_nodes.sort(key=lambda pair: (pair[0].start_byte, -pair[0].end_byte))

    built: list[tuple[Any, Symbol]] = []
    for node, captured_kind in definition_nodes:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            continue
        name = _node_text(name_node, source)
        parent = _nearest_container(node, built)
        kind = "method" if captured_kind == "function" and parent and parent.kind == "class" else captured_kind
        qualified_name = f"{parent.qualified_name}.{name}" if parent and parent.kind != "file" else name
        start_line = node.start_point.row + 1
        symbol = Symbol(
            id=_symbol_id(file_path, kind, qualified_name, start_line),
            kind=kind,  # type: ignore[arg-type]
            name=name,
            qualified_name=qualified_name,
            file_path=file_path,
            start_line=start_line,
            end_line=node.end_point.row + 1,
            parent_id=parent.id if parent else file_symbol.id,
            signature=_signature(node, source),
            docstring=_docstring(node, source),
        )
        result.symbols.append(symbol)
        built.append((node, symbol))

    for node in captures.get("reference.call", []):
        caller = _nearest_container(node, built)
        if caller is None or caller.kind not in {"function", "method"}:
            continue
        function = node.child_by_field_name("function")
        if function is None:
            continue
        receiver: str | None = None
        if function.type == "identifier":
            callee_name = _node_text(function, source)
        elif function.type == "attribute":
            name_node = function.child_by_field_name("attribute")
            object_node = function.child_by_field_name("object")
            if name_node is None:
                continue
            callee_name = _node_text(name_node, source)
            receiver = _node_text(object_node, source) if object_node is not None else None
        else:
            continue
        result.call_facts.append(CallFact(
            caller_id=caller.id,
            callee_name=callee_name,
            receiver=receiver,
            file_path=file_path,
            line=node.start_point.row + 1,
            column=node.start_point.column,
        ))

    seen_imports: set[tuple[str, str | None, str, int]] = set()
    for node in captures.get("import.statement", []):
        for fact in _parse_import_node(node, source, file_path):
            key = (fact.module, fact.imported_name, fact.local_name, fact.line)
            if key not in seen_imports:
                seen_imports.add(key)
                result.import_facts.append(fact)
    return result
