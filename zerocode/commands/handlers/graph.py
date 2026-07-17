"""Implement the local `/graph` code-index management command."""

from __future__ import annotations

import asyncio
import os

from zerocode.codegraph.indexer import GraphIndexer, IndexUpdate
from zerocode.codegraph.store import IndexCorruptError
from zerocode.commands.registry import Command, CommandContext, CommandType


def _indexer(ctx: CommandContext) -> GraphIndexer:
    root = ctx.agent.work_dir if ctx.agent else os.getcwd()
    return GraphIndexer(root)


def _stats_message(prefix: str, update: IndexUpdate) -> str:
    stats = update.stats
    return (
        f"{prefix}\n"
        f"文件: {stats.files}，符号: {stats.symbols}，边: {stats.edges}，问题: {stats.issues}\n"
        f"索引时间: {stats.indexed_at}"
    )


async def handle_graph(ctx: CommandContext) -> None:
    subcommand = (ctx.args.strip().split(maxsplit=1) or ["status"])[0].lower()
    indexer = _indexer(ctx)

    if subcommand in {"init", "rebuild"}:
        action = "初始化" if subcommand == "init" else "重建"
        ctx.ui.add_system_message(f"正在{action}代码图索引，请稍候……")
        try:
            update = await asyncio.to_thread(indexer.build_full)
        except Exception as exc:
            ctx.ui.add_system_message(f"代码图{action}失败，旧索引已保留：{type(exc).__name__}: {exc}")
            return
        ctx.ui.add_system_message(_stats_message(f"代码图{action}完成。", update))
        return

    if subcommand == "refresh":
        if not indexer.exists():
            ctx.ui.add_system_message("代码图尚未初始化。请先运行 /graph init")
            return
        try:
            update = await asyncio.to_thread(indexer.refresh)
        except IndexCorruptError as exc:
            ctx.ui.add_system_message(f"代码图索引损坏：{exc}\n请运行 /graph rebuild")
            return
        ctx.ui.add_system_message(
            _stats_message(
                f"代码图已刷新（新增 {update.added}，修改 {update.modified}，删除 {update.removed}）。",
                update,
            )
        )
        return

    if subcommand == "status":
        if not indexer.exists():
            ctx.ui.add_system_message("代码图尚未初始化。请运行 /graph init")
            return
        try:
            stats = await asyncio.to_thread(indexer.status)
        except IndexCorruptError as exc:
            ctx.ui.add_system_message(f"代码图索引损坏：{exc}\n请运行 /graph rebuild")
            return
        ctx.ui.add_system_message(
            "代码图状态\n"
            f"文件: {stats.files}，符号: {stats.symbols}，边: {stats.edges}，问题: {stats.issues}\n"
            f"索引时间: {stats.indexed_at}"
        )
        return

    ctx.ui.add_system_message("用法：/graph [init|status|refresh|rebuild]")


GRAPH_COMMAND = Command(
    name="graph",
    description="初始化、刷新或查看 Python 代码图索引",
    usage="/graph [init|status|refresh|rebuild]",
    type=CommandType.LOCAL,
    handler=handle_graph,
)
