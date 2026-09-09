"""MCP contracts for OpenArm forward and inverse kinematics."""

from __future__ import annotations

from typing import Annotated, Literal

from typing_extensions import Self

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from .program import get_ee_pose, plan_to_xyz


class EePoseResult(BaseModel):
    """Current end-effector pose in the arm_origin frame."""

    arm: Literal["right", "left"] = Field(description="Which OpenArm chain was queried.")
    frame: str = Field(description="Pose frame. Always arm_origin.")
    pose: list[float] = Field(
        description="EE pose [px, py, pz, qw, qx, qy, qz] in metres and unit quaternion.",
    )
    joints: list[float] = Field(
        description=(
            "The 7 arm joints this pose was computed from, read from "
            "/joint_states at call time."
        ),
    )


class TrajectoryPointResult(BaseModel):
    """One sample along the planned joint trajectory."""

    t: float = Field(description="Time from the start of the plan, in seconds.")
    q: list[float] = Field(description="Joint command at this sample.")
    ee_pose: list[float] = Field(description="EE pose[7] in the arm_origin frame.")


class ReachPlanResult(BaseModel):
    """Joint trajectory produced by one atomic OpenArm reach."""

    ok: bool = Field(description="True when the final position error is within tolerance.")
    failure_reason: str = Field(description="converged or max_steps.")
    frame: str = Field(description="Pose frame. Always arm_origin.")
    arm: Literal["right", "left"] = Field(description="Which OpenArm chain was planned.")
    dt: float = Field(description="Outer-loop sample period in seconds.")
    final_error_m: float = Field(description="Final Euclidean position error in metres.")
    target_pose: list[float] = Field(description="Assembled target pose[7] in arm_origin.")
    message: str = Field(description="Short summary for the model, including millimetre error.")
    points: list[TrajectoryPointResult] = Field(
        description="Trajectory samples, starting at the current configuration.",
    )


class ReachPlanSummary(BaseModel):
    """`ReachPlanResult` 面向模型的投影，不含 points 轨迹数组。

    模型驱动不了电机，逐点关节角对它没有用处；它真正需要判断的只是
    （够不够得着、差多少、生成了几个点）。
    """

    ok: bool = Field(description="True when the final position error is within tolerance.")
    failure_reason: str = Field(description="converged or max_steps.")
    frame: str = Field(description="Pose frame. Always arm_origin.")
    arm: Literal["right", "left"] = Field(description="Which OpenArm chain was planned.")
    dt: float = Field(description="Outer-loop sample period in seconds.")
    final_error_m: float = Field(description="Final Euclidean position error in metres.")
    target_pose: list[float] = Field(description="Assembled target pose[7] in arm_origin.")
    message: str = Field(description="Short summary for the model, including millimetre error.")
    point_count: int = Field(
        description=(
            "Number of trajectory samples the plan produced. The trajectory "
            "itself is not returned."
        ),
    )

    @classmethod
    def from_plan(cls, plan: ReachPlanResult) -> Self:
        """从完整规划结果投影出面向模型的摘要。"""

        return cls(
            ok=plan.ok,
            failure_reason=plan.failure_reason,
            frame=plan.frame,
            arm=plan.arm,
            dt=plan.dt,
            final_error_m=plan.final_error_m,
            target_pose=plan.target_pose,
            message=plan.message,
            point_count=len(plan.points),
        )


def register_openarm_reach_tools(mcp: FastMCP) -> None:
    """Register OpenArm pose and reach Tools."""

    @mcp.tool(
        name="get_openarm_ee_pose",
        title="Get OpenArm EE Pose",
        description=(
            "Read the OpenArm end-effector pose. The tool reads the arm's real "
            "joint angles from a continuously updated /joint_states cache; do "
            "not supply them. Poses are in the arm_origin frame, in metres. "
            "Fails if the robot is not publishing fresh joint states."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_openarm_ee_pose(
        arm: Annotated[
            Literal["right", "left"],
            Field(description="Which arm to read."),
        ],
    ) -> EePoseResult:
        """Return the current EE pose in the arm_origin frame."""

        return EePoseResult.model_validate(await get_ee_pose(arm))

    @mcp.tool(
        name="plan_openarm_reach",
        title="Plan OpenArm Reach",
        description=(
            "Plan a joint trajectory that moves one OpenArm chain to an xyz "
            "target in the arm_origin frame. The plan starts from the arm's real "
            "joint angles in a continuously updated /joint_states cache; do not "
            "supply them. Orientation is kept from the current end-effector pose. "
            "This is an IK calculation only; it does not command motors. Provide "
            "x, y, z in metres. The joint trajectory itself will not be returned. Use ok and "
            "final_error_m to judge whether the target is reachable, and "
            "point_count to confirm a trajectory was produced."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def plan_openarm_reach(
        arm: Annotated[
            Literal["right", "left"],
            Field(description="Which arm to plan."),
        ],
        x: Annotated[float, Field(description="Target x in the arm_origin frame, metres.")],
        y: Annotated[float, Field(description="Target y in the arm_origin frame, metres.")],
        z: Annotated[float, Field(description="Target z in the arm_origin frame, metres.")],
    ) -> ReachPlanSummary:
        """Plan a reach and return a summary of the joint trajectory.

        轨迹本身不进模型上下文：81 个采样点实测约 6700 token，而模型驱动不了
        电机，拿到逐点关节角也用不上。
        """

        # TODO(openarm): 决定完整轨迹的去向。目前 plan 投影完就丢弃，因为仓库里
        # 还没有任何 executor 消费它 —— 全仓搜索 ReachPlan 只有 planner 自己。
        # 可选方案：
        #   1. 落盘。照 hybrid A* 的做法写 runtime_data/openarm/latest_reach_plan.json，
        #      并在 ReachPlanSummary 里加一个 plan_file 字段指给下游。
        #   2. 直接交给执行器。经 LCM/ROS 送出去，不落盘，规划与执行同一次调用完成。
        plan = ReachPlanResult.model_validate(await plan_to_xyz(arm, x, y, z))
        return ReachPlanSummary.from_plan(plan)
