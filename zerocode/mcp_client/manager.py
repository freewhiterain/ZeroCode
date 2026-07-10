from __future__ import annotations

import logging

from zerocode.config import MCPServerConfig
from zerocode.mcp_client.client import MCPClient
from zerocode.mcp_client.tool_wrapper import MCPToolWrapper
from zerocode.tools import ToolRegistry

logger = logging.getLogger(__name__)


# 【讲解】MCPManager 管理所有配置的 MCP 服务器连接。register_all_tools()
# 在启动时对每个配置的服务器：连接 → 拉取它提供的工具列表 → 用
# MCPToolWrapper（见 tool_wrapper.py）把每个 MCP 工具包成 ZeroCode 认识的
# Tool 对象，注册进主工具表——这样模型调用一个 MCP 工具，和调用内置的
# ReadFile 没有任何区别，上层完全无感知。单个服务器连接失败只记录错误、
# 不影响其他服务器正常注册（errors 列表汇总返回，供 /mcp 命令展示）。
class MCPManager:


    def __init__(self) -> None:
        self._configs: dict[str, MCPServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}


    def load_configs(self, configs: list[MCPServerConfig]) -> None:
        for cfg in configs:
            self._configs[cfg.name] = cfg


    async def register_all_tools(self, registry: ToolRegistry) -> list[str]:
        errors: list[str] = []
        for name, config in self._configs.items():
            try:
                client = MCPClient(config)
                await client.connect()
                self._clients[name] = client

                tools = await client.list_tools()
                for tool_def in tools:
                    wrapper = MCPToolWrapper(name, tool_def, client)
                    registry.register(wrapper)
                    logger.info("Registered MCP tool: %s", wrapper.name)

            except Exception as e:
                msg = f"MCP server '{name}': {e}"
                logger.warning(msg)
                errors.append(msg)

        return errors


    async def get_client(self, name: str) -> MCPClient | None:
        client = self._clients.get(name)
        if client is None:
            config = self._configs.get(name)
            if config is None:
                return None
            client = MCPClient(config)
            await client.connect()
            self._clients[name] = client
            return client

        if not client.is_alive:
            logger.info("Reconnecting MCP server '%s'", name)
            await client.close()
            client = MCPClient(self._configs[name])
            await client.connect()
            self._clients[name] = client

        return client


    async def shutdown(self) -> None:
        for name, client in self._clients.items():
            try:
                await client.close()
                logger.info("MCP server '%s' closed", name)
            except Exception:
                logger.debug("Error closing MCP server '%s'", name, exc_info=True)
        self._clients.clear()
