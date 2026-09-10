"""MCP contracts for path tracking process management."""

from __future__ import annotations

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .program import PathTrackingProcessManager, TrackingState, TrackingStatus


class TrackingStatusResult(BaseModel):
    """Structured lifecycle status returned by path tracking tools."""

    state: TrackingState = Field(description="Current path tracking process state.")
    pid: int | None = Field(default=None, description="Operating system process ID.")
    return_code: int | None = Field(
        default=None,
        description="Process return code after it exits.",
    )
    message: str | None = Field(
        default=None,
        description="Optional process status or failure information.",
    )
    reference_path_file: str | None = Field(
        default=None,
        description="Hybrid A* JSON path file currently used by MPC.",
    )


def register_path_tracking_tools(
    mcp: FastMCP,
    process_manager: PathTrackingProcessManager,
) -> None:
    """Register the three path tracking lifecycle Tools."""

    manager = process_manager

    @mcp.tool(
        name="start_path_tracking",
        title="Start Path Tracking",
        description=(
            "Start only the MPC path tracking process. This tool does not start "
            "localization and does not run Hybrid A* planning. Prerequisite: "
            "a successful Hybrid A* JSON path must be available. The path is "
            "made of x/y waypoints "
            "and forward/reverse direction in the map frame; it is not a "
            "time-parameterized trajectory. The MPC node internally converts "
            "the path into a direction-preserving B-Spline reference pose "
            "sequence sampled at the control period. If reference_path_file is "
            "provided, MPC loads that Hybrid A* JSON path. If it is omitted and "
            "the latest Hybrid A* path JSON exists, MPC uses that file "
            "automatically. If neither is available, the call fails without "
            "starting MPC. The MPC node waits for posture feedback on "
            "the /robot_posture topic."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def start_path_tracking(
        reference_path_file: Annotated[
            str | None,
            Field(
                description=(
                    "Optional Hybrid A* JSON path file containing x/y "
                    "waypoints and forward/reverse direction. Omit this to "
                    "use the latest generated path when it exists."
                )
            ),
        ] = None,
    ) -> TrackingStatusResult:
        """Start MPC path tracking."""

        return _to_result(await manager.start(reference_path_file))

    @mcp.tool(
        name="get_tracking_status",
        title="Get Tracking Status",
        description="Read the current path tracking process state.",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_tracking_status() -> TrackingStatusResult:
        """Read the MPC path tracking process status."""

        return _to_result(await manager.get_status())

    @mcp.tool(
        name="stop_path_tracking",
        title="Stop Path Tracking",
        description="Stop the active path tracking process.",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def stop_path_tracking() -> TrackingStatusResult:
        """Stop the MPC path tracking process."""

        return _to_result(await manager.stop())


def _to_result(status: TrackingStatus) -> TrackingStatusResult:
    return TrackingStatusResult(
        state=status.state,
        pid=status.pid,
        return_code=status.return_code,
        message=status.message,
        reference_path_file=status.reference_path_file,
    )
