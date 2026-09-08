"""MCP contract for direct Hybrid A* path planning."""

from __future__ import annotations

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .models import HybridAStarPlanSummary
from .program import HybridAStarPlannerRunner


def register_hybrid_astar_planner_tool(
    mcp: FastMCP,
    runner: HybridAStarPlannerRunner | None = None,
) -> None:
    """Register the direct Hybrid A* planning Tool."""

    planner = runner or HybridAStarPlannerRunner()

    @mcp.tool(
        name="plan_hybrid_astar_path",
        title="Plan Hybrid Astar Path",
        description=(
            "Plan a collision-free Hybrid A* path on RoboClaw's fixed PNG map. "
            "Input positions use the map frame in meters, and input yaw values "
            "use radians. If the user's request does not explicitly provide a "
            "start pose, first call get_mock_localization to read the robot's "
            "current x, y, and yaw, then use that pose as the planner start. "
            "Mock localization must be running for get_mock_localization. "
            "The path itself will not be returned. It is written to the JSON "
            "file named by path_file, which start_path_tracking reads directly. "
            "Use waypoint_count to confirm a path was produced, and pass "
            "path_file to start_path_tracking."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def plan_hybrid_astar_path(
        start_x: Annotated[
            float,
            Field(description="Start x coordinate in map-frame meters."),
        ],
        start_y: Annotated[
            float,
            Field(description="Start y coordinate in map-frame meters."),
        ],
        start_yaw: Annotated[
            float,
            Field(description="Start yaw in radians."),
        ],
        goal_x: Annotated[
            float,
            Field(description="Goal x coordinate in map-frame meters."),
        ],
        goal_y: Annotated[
            float,
            Field(description="Goal y coordinate in map-frame meters."),
        ],
        goal_yaw: Annotated[
            float,
            Field(description="Goal yaw in radians."),
        ],
    ) -> HybridAStarPlanSummary:
        """Run one standalone Hybrid A* planning request.

        The complete path is written to a JSON file for MPC. This Tool returns
        only a compact summary so waypoint arrays do not enter the LLM context.
        """

        plan = await planner.plan(
            start_x,
            start_y,
            start_yaw,
            goal_x,
            goal_y,
            goal_yaw,
        )
        return HybridAStarPlanSummary.from_plan(plan)
