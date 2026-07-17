"""Turn graph query results into compact, source-grounded context for the LLM."""

from __future__ import annotations

import tokenize
from collections import deque
from pathlib import Path

from zerocode.codegraph.models import GraphEdge, Symbol
from zerocode.codegraph.store import NetworkXGraphStore


MAX_OUTPUT_CHARS = 8_000
MAX_NODES = 30
MAX_NEIGHBORS = 8


def _read_lines(root: Path, relative_path: str) -> list[str]:
    path = (root / relative_path).resolve()
    path.relative_to(root.resolve())
    with tokenize.open(path) as stream:
        return stream.read().splitlines()


def _source_block(root: Path, symbol: Symbol) -> str:
    try:
        lines = _read_lines(root, symbol.file_path)
    except (OSError, UnicodeError, ValueError, SyntaxError) as exc:
        return f"[source unavailable: {type(exc).__name__}]"
    start = max(1, symbol.start_line)
    end = min(len(lines), symbol.end_line)
    width = len(str(end))
    return "\n".join(
        f"{line_no:>{width}} | {lines[line_no - 1]}"
        for line_no in range(start, end + 1)
    )


def _relation_line(direction: str, symbol: Symbol, edge: GraphEdge) -> str:
    sites = ", ".join(
        f"{site.get('file_path', symbol.file_path)}:{site.get('line', '?')}"
        for site in edge.call_sites[:3]
    )
    suffix = f"; call sites: {sites}" if sites else ""
    return (
        f"- {direction} `{symbol.qualified_name}` "
        f"({symbol.file_path}:{symbol.start_line}; {edge.resolution or edge.confidence}{suffix})"
    )


def _relations(
    store: NetworkXGraphStore,
    seeds: list[Symbol],
    max_depth: int,
) -> list[str]:
    if max_depth <= 0:
        return []
    lines: list[str] = []
    queue = deque((symbol, 0) for symbol in seeds)
    visited = {symbol.id for symbol in seeds}
    while queue and len(visited) < MAX_NODES:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        neighbors = [
            ("caller", symbol, edge) for symbol, edge in store.callers_of(current.id)
        ] + [
            ("callee", symbol, edge) for symbol, edge in store.callees_of(current.id)
        ]
        for direction, symbol, edge in neighbors[:MAX_NEIGHBORS]:
            lines.append(_relation_line(direction, symbol, edge))
            if symbol.id not in visited and len(visited) < MAX_NODES:
                visited.add(symbol.id)
                queue.append((symbol, depth + 1))
        if len(neighbors) > MAX_NEIGHBORS:
            lines.append(f"- … {len(neighbors) - MAX_NEIGHBORS} more neighbors omitted")
    return lines


def format_query(
    store: NetworkXGraphStore,
    root: Path,
    names: list[str],
    max_depth: int,
) -> str:
    sections: list[str] = []
    seeds: list[Symbol] = []
    missing: list[str] = []
    for name in names:
        matches = store.find_symbols(name)
        if not matches:
            missing.append(name)
            continue
        seeds.extend(matches)
        sections.append(f"## Symbol: `{name}` ({len(matches)} exact match(es))")
        for symbol in matches:
            sections.append(
                f"### {symbol.kind} `{symbol.qualified_name}`\n"
                f"Location: `{symbol.file_path}:{symbol.start_line}-{symbol.end_line}`\n"
                f"Signature: `{symbol.signature}`\n\n"
                f"```python\n{_source_block(root, symbol)}\n```"
            )

    if missing:
        sections.append(
            "## Not found\n"
            + "\n".join(f"- `{name}` — try `Grep` for fuzzy/text search" for name in missing)
        )

    relation_lines = _relations(store, seeds, max_depth)
    if relation_lines:
        sections.append("## Call relations\n" + "\n".join(relation_lines))

    issue_files = {seed.file_path for seed in seeds}
    issues = [issue for issue in store.issues if issue.file_path in issue_files]
    if issues:
        sections.append(
            "## Index warnings\n"
            + "\n".join(f"- `{issue.file_path}`: {issue.message}" for issue in issues)
        )

    output = "\n\n".join(sections) or "No symbols requested."
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[: MAX_OUTPUT_CHARS - 100].rstrip() + (
            "\n\n[CodeExplore output truncated; narrow the symbols or reduce max_depth.]"
        )
    return output
