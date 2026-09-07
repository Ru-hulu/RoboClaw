"""Shared result schema for the Hybrid A* process and MCP Tool."""

from __future__ import annotations

from typing import Literal

from typing_extensions import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HybridAStarWaypoint(BaseModel):
    """One path waypoint in map coordinates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float = Field(
        strict=True,
        allow_inf_nan=False,
        description="Waypoint x coordinate in meters.",
    )
    y: float = Field(
        strict=True,
        allow_inf_nan=False,
        description="Waypoint y coordinate in meters.",
    )
    direction: Literal["forward", "reverse"] = Field(
        description="Motion direction through this path point.",
    )


class HybridAStarPlan(BaseModel):
    """Validated result returned by one Hybrid A* planning invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    success: bool = Field(
        strict=True,
        description="Whether a collision-free path was found.",
    )
    frame_id: str = Field(
        strict=True,
        description="Coordinate frame used by every waypoint.",
    )
    waypoints: tuple[HybridAStarWaypoint, ...] = Field(
        description="Ordered path from the requested start pose to the goal pose."
    )
    waypoint_count: int = Field(
        strict=True,
        ge=0,
        description="Number of waypoints in the returned path.",
    )
    map_path: str = Field(
        strict=True,
        description="Fixed PNG map used for this plan.",
    )
    path_file: str | None = Field(
        default=None,
        description=(
            "JSON file containing the latest persisted plan for downstream "
            "controllers."
        ),
    )
    planning_time_ms: float = Field(
        strict=True,
        ge=0,
        allow_inf_nan=False,
        description="Time spent inside the planner in milliseconds.",
    )
    message: str = Field(
        strict=True,
        description="Planning outcome or failure reason.",
    )

    @model_validator(mode="after")
    def validate_waypoints(self) -> Self:
        if self.waypoint_count != len(self.waypoints):
            raise ValueError("waypoint_count does not match the waypoint array.")
        if self.success and not self.waypoints:
            raise ValueError("A successful plan must contain at least one waypoint.")
        return self


class HybridAStarPlanSummary(BaseModel):
    """`HybridAStarPlan` 面向模型的投影，不含 waypoint 数组。

    而模型真正需要知道的只是（规划成功、多少个点、存在哪里）。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    success: bool = Field(
        strict=True,
        description="Whether a collision-free path was found.",
    )
    frame_id: str = Field(
        strict=True,
        description="Coordinate frame of the planned path.",
    )
    waypoint_count: int = Field(
        strict=True,
        ge=0,
        description="Number of waypoints in the planned path.",
    )
    map_path: str = Field(
        strict=True,
        description="Fixed PNG map used for this plan.",
    )
    path_file: str | None = Field(
        default=None,
        description=(
            "JSON file holding the planned path. Pass this to "
            "start_path_tracking; the path itself is not returned here."
        ),
    )
    planning_time_ms: float = Field(
        strict=True,
        ge=0,
        allow_inf_nan=False,
        description="Time spent inside the planner in milliseconds.",
    )
    message: str = Field(
        strict=True,
        description="Planning outcome or failure reason.",
    )

    @classmethod
    def from_plan(cls, plan: HybridAStarPlan) -> Self:
        """从完整规划结果投影出面向模型的摘要。"""

        return cls(
            success=plan.success,
            frame_id=plan.frame_id,
            waypoint_count=plan.waypoint_count,
            map_path=plan.map_path,
            path_file=plan.path_file,
            planning_time_ms=plan.planning_time_ms,
            message=plan.message,
        )
