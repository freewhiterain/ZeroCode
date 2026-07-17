"""保守的 Python 符号解析层。

解析优先使用类作用域、同文件和显式导入证据；只有全项目唯一时才使用
全局名字回退。无法唯一确定的调用保留为事实但不进入正式调用图。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath

from zerocode.codegraph.models import CallFact, GraphEdge, ImportFact, Symbol


CALLABLE_KINDS = {"class", "function", "method"}


def _module_candidates(fact: ImportFact) -> list[str]:
    module_path = fact.module.replace(".", "/")
    if fact.level:
        parent = PurePosixPath(fact.source_file).parent
        for _ in range(max(0, fact.level - 1)):
            parent = parent.parent
        module_path = str(parent / module_path) if module_path else str(parent)
    module_path = module_path.strip("/.")
    if not module_path:
        return []
    return [f"{module_path}.py", f"{module_path}/__init__.py"]


def _resolve_module_file(fact: ImportFact, files: set[str]) -> str | None:
    candidates = _module_candidates(fact)
    direct = [candidate for candidate in candidates if candidate in files]
    if len(direct) == 1:
        return direct[0]
    suffixes = tuple("/" + candidate for candidate in candidates)
    matches = [path for path in files if path.endswith(suffixes)] if suffixes else []
    return matches[0] if len(matches) == 1 else None


def resolve_edges(
    symbols: list[Symbol],
    call_facts: list[CallFact],
    import_facts: list[ImportFact],
) -> list[GraphEdge]:
    by_id = {symbol.id: symbol for symbol in symbols}
    by_name: dict[str, list[Symbol]] = defaultdict(list)
    by_file: dict[str, list[Symbol]] = defaultdict(list)
    children: dict[str, list[Symbol]] = defaultdict(list)
    file_nodes: dict[str, Symbol] = {}
    for symbol in symbols:
        by_name[symbol.name].append(symbol)
        by_file[symbol.file_path].append(symbol)
        if symbol.parent_id:
            children[symbol.parent_id].append(symbol)
        if symbol.kind == "file":
            file_nodes[symbol.file_path] = symbol

    imports_by_file: dict[str, list[ImportFact]] = defaultdict(list)
    for fact in import_facts:
        imports_by_file[fact.source_file].append(fact)

    edges: list[GraphEdge] = []
    for symbol in symbols:
        if symbol.parent_id and symbol.parent_id in by_id:
            edges.append(GraphEdge(symbol.parent_id, symbol.id, "contains"))

    files = set(file_nodes)
    for fact in import_facts:
        target_file = _resolve_module_file(fact, files)
        source_node = file_nodes.get(fact.source_file)
        target_node = file_nodes.get(target_file or "")
        if source_node and target_node and source_node.id != target_node.id:
            edges.append(GraphEdge(source_node.id, target_node.id, "imports", resolution="module-path"))

    # 将相同 caller→callee 的多个调用点合并到一条 DiGraph 边中，避免行号覆盖。
    resolved_calls: dict[tuple[str, str], GraphEdge] = {}
    for fact in call_facts:
        caller = by_id.get(fact.caller_id)
        if caller is None:
            continue
        target: Symbol | None = None
        confidence = "extracted"
        resolution = ""

        if fact.receiver in {"self", "cls"}:
            owner = by_id.get(caller.parent_id or "")
            if owner and owner.kind == "class":
                candidates = [s for s in children.get(owner.id, []) if s.name == fact.callee_name]
                if len(candidates) == 1:
                    target, resolution = candidates[0], "class-scope"

        if target is None and fact.receiver is None:
            local = [s for s in by_file[caller.file_path] if s.name == fact.callee_name and s.kind in CALLABLE_KINDS]
            if len(local) == 1:
                target, resolution = local[0], "same-file"

        if target is None:
            for imported in imports_by_file[caller.file_path]:
                imported_matches = False
                target_name = fact.callee_name
                if fact.receiver is None and imported.imported_name and imported.local_name == fact.callee_name:
                    imported_matches = True
                    target_name = imported.imported_name
                elif fact.receiver and imported.imported_name is None and imported.local_name == fact.receiver.split(".")[0]:
                    imported_matches = True
                if not imported_matches:
                    continue
                target_file = _resolve_module_file(imported, files)
                candidates = [s for s in by_file.get(target_file or "", []) if s.name == target_name and s.kind in CALLABLE_KINDS]
                if len(candidates) == 1:
                    target, resolution = candidates[0], "explicit-import"
                    break

        if target is None and fact.receiver is None:
            global_candidates = [s for s in by_name[fact.callee_name] if s.kind in CALLABLE_KINDS]
            if len(global_candidates) == 1:
                target = global_candidates[0]
                confidence = "inferred"
                resolution = "global-unique"

        if target is None:
            continue
        site = {"file_path": fact.file_path, "line": fact.line, "column": fact.column}
        key = (caller.id, target.id)
        existing = resolved_calls.get(key)
        if existing is None:
            resolved_calls[key] = GraphEdge(
                caller.id,
                target.id,
                "calls",
                confidence=confidence,  # type: ignore[arg-type]
                resolution=resolution,
                call_sites=(site,),
            )
        else:
            resolved_calls[key] = GraphEdge(
                existing.source,
                existing.target,
                existing.kind,
                confidence=existing.confidence,
                resolution=existing.resolution,
                call_sites=existing.call_sites + (site,),
            )

    edges.extend(resolved_calls.values())
    return edges
