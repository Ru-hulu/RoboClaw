"""Outer loop that turns repeated IK steps into a joint-space trajectory."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from robot_runtime.openarm_ik.constraints import IKConstraints, singularity_ratio
from robot_runtime.openarm_ik.kinematics import fk, jacobian
from robot_runtime.openarm_ik.model import ORIGIN_FRAME, arm
from robot_runtime.openarm_ik.solver import IKStepConfig, resolve_constraints, step


# 判定"这一轮实质上没有推进"的位移阈值。低于它就不算改善。
_PROGRESS_EPSILON_M = 1e-4
# 判定关节停在限位上的角度容差。solver 的 apply_joint_limits 会把越界值裁到
# 限位本身，所以贴住限位时差值接近 0。
_JOINT_LIMIT_EPSILON_RAD = 1e-6
# 卡住后依次尝试的"向 home 靠拢"比例。实测中肘部只要离开完全伸直 1 度，
# 奇异制动就解除，所以第一档取得很小。
DEFAULT_ESCAPE_BLENDS: tuple[float, ...] = (0.02, 0.1, 0.3, 1.0)
# 逃逸段自身的关节步长上限，避免用一个点跨完整段。
_ESCAPE_STEP_RAD = math.radians(5.0)

CONVERGED = "converged"
MAX_STEPS = "max_steps"
OUT_OF_REACH = "out_of_reach"
SINGULARITY_LOCKED = "singularity_locked"
JOINT_LIMIT_BLOCKED = "joint_limit_blocked"
NO_PROGRESS = "no_progress"


@dataclass(frozen=True)
class TrajectoryPoint:
    """One recorded sample of the outer IK loop."""

    t: float
    q: tuple[float, ...]
    ee_pose: tuple[float, ...]


@dataclass(frozen=True)
class ReachPlan:
    """Cartesian reach result in the arm_origin frame."""

    arm: str
    frame: str
    dt: float
    points: tuple[TrajectoryPoint, ...]
    target_pose: tuple[float, ...]
    initial_error_m: float
    final_error_m: float
    ok: bool
    failure_reason: str
    escape_blend: float


def plan_reach(
    side: str,
    joints: Sequence[float],
    target: Sequence[float],
    *,
    max_steps: int = 80,
    pos_tol: float = 0.006,
    dt: float = 0.05,
    config: IKConstraints | IKStepConfig | None = None,
    escape_blends: Sequence[float] = DEFAULT_ESCAPE_BLENDS,
) -> ReachPlan:
    """Move from the current joints toward an xyz or pose[7] target.

    The returned trajectory starts at the current configuration. Each later
    point is one ``step()``. Orientation defaults to the current EE quaternion
    when ``target`` is only xyz.

    A first attempt that stalls without converging is retried from seeds blended
    toward ``home``; the escape motion is prepended so the result stays
    executable. When every attempt fails, the one that got closest is returned,
    because its stopping reason describes the arm better than the reason of a
    start posture the solver has since escaped.
    """

    if max_steps <= 0:
        raise ValueError("max_steps must be positive")
    if pos_tol <= 0.0:
        raise ValueError("pos_tol must be positive")
    if dt <= 0.0:
        raise ValueError("dt must be positive")

    settings = resolve_constraints(config)
    kinematics = arm(side)
    start_q = tuple(float(value) for value in joints)
    start_pose = fk(side, start_q)
    target_pose = _assemble_target(start_pose, target)
    initial_error = _position_error(start_pose, target_pose)
    origin = [TrajectoryPoint(t=0.0, q=start_q, ee_pose=start_pose)]

    # 连杆长度之和是硬上界，超过它不必浪费 80 步。
    if math.dist(target_pose[:3], kinematics.base_from_origin) > kinematics.max_reach:
        return _plan(side, dt, origin, target_pose, initial_error, 0.0, OUT_OF_REACH)

    points = _solve(side, start_q, target_pose, max_steps, pos_tol, config)
    reason = _classify(side, points, target_pose, pos_tol, settings)
    if reason in (CONVERGED, MAX_STEPS):
        return _plan(side, dt, points, target_pose, initial_error, 0.0, reason)

    # 卡住了。原地重试没有意义，因为 step() 是确定性的；换一个不在奇异点上的种子。
    best_points, best_blend, best_reason = points, 0.0, reason
    for blend in escape_blends:
        seed = _blend_toward(start_q, kinematics.home, blend)
        if seed == start_q:
            continue
        retry = _ramp(side, start_q, seed) + _solve(
            side, seed, target_pose, max_steps, pos_tol, config
        )[1:]
        retry_reason = _classify(side, retry, target_pose, pos_tol, settings)
        if retry_reason == CONVERGED:
            return _plan(side, dt, retry, target_pose, initial_error, blend, retry_reason)
        if _position_error(retry[-1].ee_pose, target_pose) < _position_error(
            best_points[-1].ee_pose, target_pose
        ):
            best_points, best_blend, best_reason = retry, blend, retry_reason

    return _plan(side, dt, best_points, target_pose, initial_error, best_blend, best_reason)


def _solve(
    side: str,
    start_q: tuple[float, ...],
    target_pose: tuple[float, ...],
    max_steps: int,
    pos_tol: float,
    config: IKConstraints | IKStepConfig | None,
) -> list[TrajectoryPoint]:
    """Run the outer loop until it converges or runs out of steps."""

    current_q = start_q
    current_pose = fk(side, current_q)
    points = [TrajectoryPoint(t=0.0, q=current_q, ee_pose=current_pose)]
    if _position_error(current_pose, target_pose) <= pos_tol:
        return points

    for _ in range(max_steps):
        current_q = step(side, current_q, target_pose, config=config)
        current_pose = fk(side, current_q)
        points.append(TrajectoryPoint(t=0.0, q=current_q, ee_pose=current_pose))
        if _position_error(current_pose, target_pose) <= pos_tol:
            break
    return points


def _classify(
    side: str,
    points: list[TrajectoryPoint],
    target_pose: tuple[float, ...],
    pos_tol: float,
    settings: IKConstraints,
) -> str:
    """Say why the run stopped.

    Gives more information why the plan has failed. Order matters, as a locked
    Jacobian explains a joint sitting on its stop rather than the other way round.
    """

    # 进了容差就是成功，走了几步无关。
    final_error = _position_error(points[-1].ee_pose, target_pose)
    if final_error <= pos_tol:
        return CONVERGED

    # 雅可比退化时 _enforce_singularity_plane 把每一步都缩放到零，误差可以一动没动。
    # 放在最前面判：它能解释后面每一种"停住了"，反过来不成立。
    final_q = points[-1].q
    if settings.enable_singularity_limit:
        ratio = singularity_ratio(jacobian(side, final_q), settings)
        if ratio < settings.singularity_ratio_stop:
            return SINGULARITY_LOCKED

    # 只看最近 5 步，不看首尾之差：先推进一大段再卡死的情况，首尾差看着很健康，
    # 但那时候再给多少步都没用。还在缩小误差才说明只是预算不够。
    earlier = points[max(0, len(points) - 6)]
    if _position_error(earlier.ee_pose, target_pose) - final_error > _PROGRESS_EPSILON_M:
        return MAX_STEPS

    # apply_joint_limits 会把越界值裁到限位本身，所以顶住的关节和限位精确相等。
    if any(
        abs(value - hinge.lower) <= _JOINT_LIMIT_EPSILON_RAD
        or abs(value - hinge.upper) <= _JOINT_LIMIT_EPSILON_RAD
        for hinge, value in zip(arm(side).hinges, final_q)
    ):
        return JOINT_LIMIT_BLOCKED

    # 关节还有余地，也没撞奇异，纯粹是收敛不下去：局部极小，或者被保持不变的
    # 末端朝向和目标位置本身冲突。换种子重试过仍是这个结果，才轮到这里。
    return NO_PROGRESS


def _blend_toward(
    start_q: tuple[float, ...],
    home: tuple[float, ...],
    blend: float,
) -> tuple[float, ...]:
    """Move the arm joints a fraction of the way to home.
    Avoid singulairty at starting point."""

    count = len(home)
    blended = tuple(
        value + blend * (rest - value) for value, rest in zip(start_q[:count], home)
    )
    return blended + tuple(start_q[count:])


def _ramp(
    side: str,
    start_q: tuple[float, ...],
    seed: tuple[float, ...],
) -> list[TrajectoryPoint]:
    """Joint-space samples from the caller's configuration to the escape seed."""

    largest = max(abs(b - a) for a, b in zip(start_q, seed))
    segments = max(1, math.ceil(largest / _ESCAPE_STEP_RAD))
    samples = []
    for index in range(segments + 1):
        fraction = index / segments
        q = tuple(a + fraction * (b - a) for a, b in zip(start_q, seed))
        samples.append(TrajectoryPoint(t=0.0, q=q, ee_pose=fk(side, q)))
    return samples


def _assemble_target(
    current_pose: tuple[float, ...],
    target: Sequence[float],
) -> tuple[float, ...]:
    values = tuple(float(value) for value in target)
    if len(values) == 3:
        return values + current_pose[3:]
    if len(values) == 7:
        return values
    raise ValueError("target must be xyz (3) or pose[7]")


def _position_error(pose: tuple[float, ...], target: tuple[float, ...]) -> float:
    return math.sqrt(sum((pose[index] - target[index]) ** 2 for index in range(3)))


def _plan(
    side: str,
    dt: float,
    points: list[TrajectoryPoint],
    target_pose: tuple[float, ...],
    initial_error: float,
    escape_blend: float,
    reason: str,
) -> ReachPlan:
    return ReachPlan(
        arm=side,
        frame=ORIGIN_FRAME,
        dt=dt,
        points=tuple(
            TrajectoryPoint(t=index * dt, q=point.q, ee_pose=point.ee_pose)
            for index, point in enumerate(points)
        ),
        target_pose=target_pose,
        initial_error_m=initial_error,
        final_error_m=_position_error(points[-1].ee_pose, target_pose),
        ok=reason == CONVERGED,
        failure_reason=reason,
        escape_blend=escape_blend,
    )
