"""MCP Server — tool dispatcher and standalone MCP server.

McpToolDispatcher: In-process MCP tool dispatch for LLM tool calls.
Validates tool name, dispatches to McpAdapter handler, formats result.

create_mcp_server / run_stdio: Standalone MCP server for external clients
using the ``mcp`` SDK with stdio transport.
"""

import json
import logging

logger = logging.getLogger(__name__)


class McpToolDispatcher:
    """In-process MCP-compatible tool dispatcher.

    Routes LLM-generated tool calls through structured dispatch with
    the same tool definitions as the standalone MCP server.
    Used by AgentLoop for hybrid MCP compliance.
    """

    def __init__(self, adapter):
        """
        Args:
            adapter: McpAdapter instance.
        """
        self._adapter = adapter
        self._handlers = {
            "get_runtime_state": lambda **kw: adapter.get_runtime_state(),
            "get_zone": lambda **kw: adapter.get_zone(**kw),
            "get_scheduler_status": lambda **kw: adapter.get_scheduler_status(),
            "get_history": lambda **kw: adapter.get_history(**kw),
            "get_analytics_summary": lambda **kw: adapter.get_analytics_summary(),
            "propose_setpoint": lambda **kw: adapter.propose_setpoint(**kw),
            "get_zone_trend": lambda **kw: adapter.get_zone_trend(**kw),
            "get_building_summary": lambda **kw: adapter.get_building_summary(),
        }

    def call_tool(self, name, arguments=None):
        """Execute a named tool with given arguments.

        Args:
            name: Tool name string (must be one of the 8 registered tools).
            arguments: dict of keyword arguments for the tool.

        Returns:
            dict: Tool result or error dict.
        """
        handler = self._handlers.get(name)
        if handler is None:
            return {"error": "unknown_tool", "name": name}

        if arguments is None:
            arguments = {}

        if not isinstance(arguments, dict):
            return {"error": "invalid_arguments", "message": "arguments must be a JSON object", "tool": name}

        # Ensure arguments are proper types
        clean_args = {}
        for k, v in arguments.items():
            if isinstance(v, str):
                # Try to parse numeric strings
                try:
                    if "." in v:
                        clean_args[k] = float(v)
                    else:
                        clean_args[k] = int(v)
                except ValueError:
                    clean_args[k] = v
            else:
                clean_args[k] = v

        try:
            return handler(**clean_args)
        except TypeError as e:
            return {"error": "invalid_arguments", "message": str(e), "tool": name}
        except Exception as e:
            return {"error": "tool_error", "message": str(e), "tool": name}

    def list_tools(self):
        """Return tool manifest (same as adapter.list_tools)."""
        return self._adapter.list_tools()


def create_mcp_server(adapter):
    """Create a FastMCP server wrapping McpAdapter for external clients.

    Requires the ``mcp`` package (pip install mcp).

    Args:
        adapter: McpAdapter instance.

    Returns:
        FastMCP server instance with 8 tools registered.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        logger.warning(
            "mcp package not installed. Standalone MCP server unavailable. "
            "Install with: pip install mcp"
        )
        return None

    mcp = FastMCP("EcoAgent HVAC Supervisor")

    @mcp.tool()
    def get_runtime_state() -> dict:
        """Current controller state for all zones."""
        return adapter.get_runtime_state()

    @mcp.tool()
    def get_zone(zone_name: str) -> dict:
        """Current state for a specific zone."""
        return adapter.get_zone(zone_name)

    @mcp.tool()
    def get_scheduler_status() -> dict:
        """Scheduler lifecycle status and simulation clock."""
        return adapter.get_scheduler_status()

    @mcp.tool()
    def get_history(offset: int = 0, count: int = 10) -> list:
        """Historical snapshots by offset and count."""
        return adapter.get_history(offset, count)

    @mcp.tool()
    def get_analytics_summary() -> dict:
        """Comfort, safety, oscillation, and energy metrics."""
        return adapter.get_analytics_summary()

    @mcp.tool()
    def propose_setpoint(zone_name: str, heating: float, cooling: float,
                         source: str = "mcp_agent") -> dict:
        """Submit advisory setpoint proposal for a zone."""
        return adapter.propose_setpoint(zone_name, heating, cooling, source)

    @mcp.tool()
    def get_zone_trend(zone_name: str, window: int = 8) -> dict:
        """Temperature and setpoint trend for a zone over recent history."""
        return adapter.get_zone_trend(zone_name, window)

    @mcp.tool()
    def get_building_summary() -> dict:
        """Merged scheduler, zone states, and analytics in one call."""
        return adapter.get_building_summary()

    return mcp


def run_stdio(server):
    """Run MCP server with stdio transport. Blocks until EOF or SIGINT.

    Args:
        server: FastMCP instance from create_mcp_server().
    """
    if server is None:
        logger.error("Cannot run stdio: server is None (mcp package not installed?).")
        return
    server.run(transport="stdio")


if __name__ == "__main__":
    # Standalone entry point for external MCP clients.
    # Requires a running simulation or mock data source.
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent.parent / "src"))

    print("EcoAgent MCP Server (standalone mode)", file=sys.stderr)
    print("This requires a running simulation to provide live data.", file=sys.stderr)
    print("For testing, use test_phase4.py instead.", file=sys.stderr)
