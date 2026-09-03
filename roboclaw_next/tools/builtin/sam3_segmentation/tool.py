"""FastMCP contracts for the SAM3 perception service."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .models import Sam3PerceptionStatusResult
from .program import Sam3PerceptionManager


def register_sam3_segmentation_tools(
    mcp: FastMCP,
    process_manager: Sam3PerceptionManager,
) -> None:
    """Register SAM3 service lifecycle tools."""

    manager = process_manager

    @mcp.tool(
        name="start_sam3_perception",
        title="Start SAM3 Perception",
        description=(
            "Start RoboClaw's long-running SAM3 service process and wait until its "
            "model is loaded. This tool only manages the service lifecycle; it does "
            "not submit an inference request."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def start_sam3_perception() -> Sam3PerceptionStatusResult:
        return await manager.start()

    @mcp.tool(
        name="get_sam3_perception_status",
        title="Get SAM3 Perception Status",
        description=(
            "Read the SAM3 perception service process state. This does not start "
            "SAM3, load the model, or submit an inference request."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_sam3_perception_status() -> Sam3PerceptionStatusResult:
        return await manager.get_status()

    @mcp.tool(
        name="stop_sam3_perception",
        title="Stop SAM3 Perception",
        description=(
            "Stop RoboClaw's long-running SAM3 perception service if this MCP "
            "server started it. Repeated calls are safe."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def stop_sam3_perception() -> Sam3PerceptionStatusResult:
        return await manager.stop()
