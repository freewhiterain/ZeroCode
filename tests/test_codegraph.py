from __future__ import annotations

import os
from pathlib import Path

import pytest

from zerocode.codegraph.formatter import format_query
from zerocode.codegraph.indexer import GraphIndexer
from zerocode.codegraph.parser import parse_python_file
from zerocode.codegraph.resolver import resolve_edges
from zerocode.codegraph.store import NetworkXGraphStore
from zerocode.tools.code_explore import CodeExplore, CodeExploreParams


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_parser_extracts_nested_symbols_signature_calls_and_imports() -> None:
    source = b"""from lib import helper as run_helper

class Service:
    def run(self, value: int) -> int:
        \"\"\"Run one value.\"\"\"
        return self.finish(run_helper(value))

    def finish(self, value):
        return value
"""
    result = parse_python_file("service.py", source)

    symbols = {(symbol.kind, symbol.qualified_name): symbol for symbol in result.symbols}
    assert ("class", "Service") in symbols
    assert ("method", "Service.run") in symbols
    assert symbols[("method", "Service.run")].signature == "def run(self, value: int) -> int"
    assert symbols[("method", "Service.run")].docstring == "Run one value."
    assert {(fact.receiver, fact.callee_name) for fact in result.call_facts} == {
        ("self", "finish"),
        (None, "run_helper"),
    }
    assert result.import_facts[0].local_name == "run_helper"


def test_resolver_skips_ambiguous_global_calls() -> None:
    caller = parse_python_file("caller.py", b"def use():\n    target()\n")
    first = parse_python_file("a.py", b"def target():\n    pass\n")
    second = parse_python_file("b.py", b"def target():\n    pass\n")
    symbols = caller.symbols + first.symbols + second.symbols

    edges = resolve_edges(symbols, caller.call_facts, [])

    assert not [edge for edge in edges if edge.kind == "calls"]


def test_full_build_query_and_incremental_refresh(tmp_path: Path) -> None:
    _write(tmp_path / "lib.py", "def helper(value):\n    return value + 1\n")
    _write(
        tmp_path / "app.py",
        "from lib import helper\n\ndef run(value):\n    return helper(value)\n",
    )
    indexer = GraphIndexer(tmp_path)

    built = indexer.build_full()
    store = indexer.load()
    helper = store.find_symbols("helper")[0]
    assert built.stats.files == 2
    assert [symbol.name for symbol, _ in store.callers_of(helper.id)] == ["run"]
    rendered = format_query(store, tmp_path, ["helper"], 1)
    assert "return value + 1" in rendered
    assert "caller `run`" in rendered

    old_app_hash = store.file_states["app.py"].content_hash
    _write(tmp_path / "lib.py", "def helper(value):\n    return value + 2\n")
    refreshed = indexer.refresh()
    updated = indexer.load()
    assert refreshed.modified == 1
    assert updated.file_states["app.py"].content_hash == old_app_hash
    helper = updated.find_symbols("helper")[0]
    assert [symbol.name for symbol, _ in updated.callers_of(helper.id)] == ["run"]


@pytest.mark.asyncio
async def test_tool_requires_init_then_returns_current_source(tmp_path: Path) -> None:
    _write(tmp_path / "sample.py", "def answer():\n    return 42\n")
    tool = CodeExplore(tmp_path)
    params = CodeExploreParams(symbols=["answer"], max_depth=0)

    missing = await tool.execute(params)
    assert not missing.is_error
    assert "/graph init" in missing.output

    tool.indexer.build_full()
    result = await tool.execute(params)
    assert not result.is_error
    assert "def answer" in result.output
    assert "return 42" in result.output


def test_default_registry_includes_code_explore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    from zerocode.tools import create_default_registry

    registry = create_default_registry()
    tool = registry.get("CodeExplore")
    assert tool is not None
    assert tool.is_concurrency_safe is False
