"""In-process OpenArm FK/IK used by the MCP tools.

Joint angles come from a process-wide listener that continuously caches the
robot's `/joint_states` topic. They are never a tool parameter: the model cannot
observe them, so anything it typed would be a guess. This layer reads the real
state, calls the pure kinematics, and converts the planner's tuples into
JSON-friendly dictionaries.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from robot_runtime.openarm_control import read_arm_joint_state
from robot_runtime.openarm_ik import ORIGIN_FRAME, ReachPlan, fk, plan_reach


async def read_joints(arm: str) -> list[float]:
    """Read the latest fresh 7-joint snapshot, off the event loop."""

    state = await asyncio.to_thread(read_arm_joint_state, arm)
    return list(state.positions)


async def get_ee_pose(arm: str) -> dict[str, object]:
    """Read the EE pose[7] in the arm_origin frame from the current joints."""

    return build_ee_pose(arm, await read_joints(arm))


async def plan_to_xyz(
    arm: str,
    x: float,
    y: float,
    z: float,
) -> dict[str, object]:
    """Plan a reach from the current joints to an arm_origin xyz target."""

    return plan_from_joints(arm, await read_joints(arm), x, y, z)


def build_ee_pose(arm: str, joints: Sequence[float]) -> dict[str, object]:
    """FK payload for a given joint vector. Pure; ROS is the caller's problem."""

    values = [float(value) for value in joints]
    return {
        "arm": arm,
        "frame": ORIGIN_FRAME,
        "pose": list(fk(arm, values)),
        "joints": values,
    }


def plan_from_joints(
    arm: str,
    joints: Sequence[float],
    x: float,
    y: float,
    z: float,
) -> dict[str, object]:
    """Plan from an explicit start, keeping the current EE orientation.

    Pure, so tests can pin a start configuration. The MCP tools never expose
    this start to the model.
    """

    return serialize_plan(plan_reach(arm, joints, (x, y, z)))


def serialize_plan(plan: ReachPlan) -> dict[str, object]:
    """Convert a ReachPlan into a structured tool payload."""

    step_count = max(0, len(plan.points) - 1)
    error_mm = plan.final_error_m * 1000.0
    if plan.ok:
        message = (
            f"Reached the target in the {plan.frame} frame with "
            f"{error_mm:.1f} mm error after {step_count} IK steps."
        )
    else:
        message = (
            f"Stopped after {step_count} IK steps in the {plan.frame} frame; "
            f"final position error is {error_mm:.1f} mm."
        )
    return {
        "ok": plan.ok,
        "failure_reason": plan.failure_reason,
        "frame": plan.frame,
        "arm": plan.arm,
        "dt": plan.dt,
        "final_error_m": plan.final_error_m,
        "target_pose": list(plan.target_pose),
        "message": message,
        "points": [
            {
                "t": point.t,
                "q": list(point.q),
                "ee_pose": list(point.ee_pose),
            }
            for point in plan.points
        ],
    }
