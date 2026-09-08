"""FastMCP contract for target object position query."""

from __future__ import annotations

import asyncio
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .models import TargetObjectPositionResult
from .program import TargetObjectPositionResolver


def register_target_object_position_tool(
    mcp: FastMCP,
    resolver: TargetObjectPositionResolver | None = None,
) -> None:
    """Register the target object position business Tool."""

    position_resolver = resolver or TargetObjectPositionResolver()

    @mcp.tool(
        name="get_target_object_position",
        title="Get Target Object Position",
        description=(
            "Query the running SAM3 perception service for a target described by "
            "a natural-language prompt. The tool submits one SAM3 LCM RPC request "
            "and estimates the target centroid from the best SAM3 mask and the "
            "captured depth frame using fixed Gazebo RealSense intrinsics. Before "
            "calling this tool, start the Gazebo RealSense camera listener and "
            "start_sam3_perception."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def get_target_object_position(
        prompt: Annotated[
            str,
            Field(
                min_length=1,
                max_length=256,
                description="Natural-language description of the target object.",
            ),
        ],
    ) -> TargetObjectPositionResult:
        return await asyncio.to_thread(position_resolver.get_position, prompt)
