"""ZeroCode 命令行入口。

负责解析启动参数、加载配置与 hooks，并根据运行模式进入交互式 TUI
或一次性非交互执行流程。此模块只做应用装配，不承载具体 agent 推理逻辑。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from zerocode.config import ConfigError, load_config
from zerocode.hooks import HookConfigError, HookEngine, load_hooks
from zerocode.permissions import PermissionMode

log = logging.getLogger(__name__)


def main() -> None:
    # 【讲解】程序入口（pyproject.toml 里 `zerocode = "zerocode.__main__:main"`
    # 把它注册成了命令）。流程：建日志目录 → 解析命令行参数 → 加载配置 →
    # 加载 hooks → 二选一：带 -p 参数走一次性非交互模式，否则启动 Textual TUI。
    # 先确保 .zerocode/ 目录存在，否则下面写 debug.log 会因目录不存在而崩溃
    Path(".zerocode").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        filename=".zerocode/debug.log",
        filemode="w",
    )

    parser = argparse.ArgumentParser(prog="ZeroCode", description="ZeroCode AI coding assistant")
    parser.add_argument(
        "--mode",
        choices=[m.value for m in PermissionMode],
        default=None,
        help="Permission mode (overrides config.yaml)",
    )
    parser.add_argument(
        "-p",
        metavar="PROMPT",
        default=None,
        help="Run non-interactively: execute the prompt and print the result to stdout",
    )
    args = parser.parse_args()

    try:
        config = load_config()
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    mode_str = args.mode if args.mode else config.permission_mode
    permission_mode = PermissionMode(mode_str)

    try:
        hooks = load_hooks(config.raw_hooks)
    except HookConfigError as e:
        print(f"Hook config error: {e}", file=sys.stderr)
        sys.exit(1)

    hook_engine = HookEngine(hooks) if hooks else None

    if args.p is not None:
        asyncio.run(_run_prompt(config, permission_mode, hook_engine, args.p))
        return

    # 【讲解】把 import 放在函数体内（而不是文件顶部）是刻意的：app.py 及其
    # 依赖的 Textual 很重，-p 非交互模式根本用不到它们，延迟导入能加快启动。
    from zerocode.app import ZeroCodeApp
    from zerocode.driver import NoAltScreenDriver

    app = ZeroCodeApp(
        providers=config.providers,
        permission_mode=permission_mode,
        mcp_servers=config.mcp_servers,
        hook_engine=hook_engine,
        enable_fork=config.enable_fork,
        enable_verification_agent=config.enable_verification_agent,
        worktree_config=config.worktree,
        teammate_mode=config.teammate_mode,
        enable_coordinator_mode=config.enable_coordinator_mode,
        driver_class=NoAltScreenDriver,
    )
    app.run()


async def _run_prompt(config, permission_mode, hook_engine, prompt: str) -> None:
    """执行 -p 非交互模式下的一次性 prompt。

    这里手动装配与 TUI 模式等价的 client、权限检查器、工具注册表、
    子 agent/团队管理器和会话对象，然后把最终文本输出到 stdout。
    """
    from zerocode.agent import Agent
    from zerocode.client import create_client, resolve_context_window
    from zerocode.conversation import ConversationManager
    from zerocode.memory.instructions import load_instructions
    from zerocode.permissions import (
        DangerousCommandDetector,
        PathSandbox,
        PermissionChecker,
        RuleEngine,
    )
    from zerocode.tools import create_default_registry
    from zerocode.agents.loader import AgentLoader
    from zerocode.agents.task_manager import TaskManager
    from zerocode.agents.trace import TraceManager
    from zerocode.tools.agent_tool import AgentTool
    from zerocode.tools.impl.tool_search import ToolSearchTool
    from zerocode.teams.manager import TeamManager
    from zerocode.teams.models import BackendType
    from zerocode.tools.team_create import TeamCreateTool
    from zerocode.tools.team_delete import TeamDeleteTool
    from zerocode.worktree import WorktreeManager
    from zerocode.config import WorktreeConfig

    provider = config.providers[0]
    client = create_client(provider)
    # 第 2 层：尽力从 provider 自动拉取模型的 context window（缓存在 provider 上）。
    # 不会抛异常或阻塞启动；失败则退化到映射表。
    await resolve_context_window(provider)
    work_dir = os.getcwd()
    home = Path.home()

    checker = PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=PathSandbox(work_dir),
        rule_engine=RuleEngine(
            user_rules_path=home / ".zerocode" / "permissions.yaml",
            project_rules_path=Path(work_dir) / ".zerocode" / "permissions.yaml",
            local_rules_path=Path(work_dir) / ".zerocode" / "permissions.local.yaml",
        ),
        mode=permission_mode,
    )

    instructions = load_instructions(work_dir)
    registry = create_default_registry()
    registry.register(ToolSearchTool(registry, protocol=provider.protocol))

    agent = Agent(
        client=client,
        registry=registry,
        protocol=provider.protocol,
        work_dir=work_dir,
        permission_checker=checker,
        context_window=provider.get_context_window(),
        instructions_content=instructions,
        hook_engine=hook_engine,
    )

    wt_cfg = config.worktree or WorktreeConfig()
    wt_manager = WorktreeManager(
        repo_root=work_dir,
        symlink_directories=wt_cfg.symlink_directories,
    )
    trace_manager = TraceManager()
    task_manager = TaskManager()
    agent_loader = AgentLoader(work_dir, enable_verification=config.enable_verification_agent)
    agent_loader.load_all()
    team_manager = TeamManager(worktree_manager=wt_manager, trace_manager=trace_manager)

    agent_tool = AgentTool(
        agent_loader=agent_loader,
        task_manager=task_manager,
        trace_manager=trace_manager,
        parent_agent=agent,
        enable_fork=config.enable_fork,
        provider_config=provider,
        worktree_manager=wt_manager,
        team_manager=team_manager,
    )
    registry.register(agent_tool)
    registry.register(TeamCreateTool(
        team_manager=team_manager,
        parent_agent=agent,
        teammate_mode="in-process",
        is_interactive=False,
        enable_coordinator_mode=config.enable_coordinator_mode,
    ))
    registry.register(TeamDeleteTool(team_manager=team_manager, parent_agent=agent))

    def drain_notifications() -> list[str]:
        notes: list[str] = []
        for t in task_manager.poll_completed():
            notes.append(
                f"<task-notification>\n<task_id>{t.id}</task_id>\n"
                f"<status>{t.status}</status>\n<result>{t.result}</result>\n"
                f"</task-notification>"
            )
        notes.extend(team_manager.drain_lead_mailbox())
        return notes

    def drain_mailbox_only() -> list[str]:
        return team_manager.drain_lead_mailbox()

    agent.notification_fn = drain_mailbox_only

    conv = ConversationManager()
    last_result = await agent.run_to_completion(prompt, conv)
    print(last_result, flush=True)

    if not team_manager._teams:
        return

    # 【讲解】-p 模式下如果创建了团队，这里轮询等待 teammate 完成任务。
    # 原来这段用 print(..., file=sys.stderr) 输出调试信息（每 2 秒打一行），
    # 属于开发调试时留下的痕迹；改成 log.debug 写入 .zerocode/debug.log，
    # 不再直接污染用户看到的 stderr 输出，需要排查时翻日志文件即可。
    for i in range(90):
        await asyncio.sleep(2)
        running = {k: not t.done() for k, t in task_manager._async_tasks.items()}
        completed_ids = [t.id for t in task_manager._tasks.values() if t.status != "running"]
        log.debug(
            "[poll %d] running=%s completed=%s teams=%s queue_size=%d",
            i, running, completed_ids, list(team_manager._teams.keys()),
            task_manager._notify_queue.qsize(),
        )
        notes = drain_notifications()
        if not notes:
            has_running = any(v for v in running.values())
            if not has_running:
                log.debug("[poll %d] no running tasks, breaking", i)
                break
            continue
        for note in notes:
            conv.add_system_reminder(note)
        last_result = await agent.run_to_completion(
            "Teammate notifications received. Process them and continue.", conv
        )
        print(last_result, flush=True)


if __name__ == "__main__":
    main()

