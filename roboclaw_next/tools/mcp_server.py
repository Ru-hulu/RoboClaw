"""MCP server that registers and exposes RoboClaw tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .builtin.hybrid_astar_planner.tool import register_hybrid_astar_planner_tool
from .builtin.mock_localization.program import MockLocalizationProcessManager
from .builtin.mock_localization.tool import register_mock_localization_tools
from .builtin.openarm_reach.tool import register_openarm_reach_tools
from .builtin.path_tracking.program import PathTrackingProcessManager
from .builtin.path_tracking.tool import register_path_tracking_tools


mcp = FastMCP("RoboClaw Tool Server", json_response=True)

localization_manager = MockLocalizationProcessManager()
tracking_manager = PathTrackingProcessManager(localization_manager)

register_mock_localization_tools(mcp, localization_manager)
register_path_tracking_tools(mcp, tracking_manager)
register_hybrid_astar_planner_tool(mcp)
register_openarm_reach_tools(mcp)


if __name__ == "__main__":
    mcp.run(transport="stdio")
