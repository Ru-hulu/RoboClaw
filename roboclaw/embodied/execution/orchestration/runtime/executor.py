"""Runtime execution helpers for embodied procedures."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from roboclaw.agent.tools.registry import ToolRegistry
from roboclaw.embodied.builtins import get_builtin_calibration_driver
from roboclaw.embodied.localization import localize_text
from roboclaw.embodied.definition.components.robots.model import RobotManifest
from roboclaw.embodied.definition.systems.assemblies.model import AssemblyManifest
from roboclaw.embodied.definition.systems.deployments.model import DeploymentProfile
from roboclaw.embodied.execution.integration.adapters.loader import AdapterLoader
from roboclaw.embodied.execution.integration.carriers.model import ExecutionTarget
from roboclaw.embodied.execution.orchestration.procedures.model import ProcedureKind
from roboclaw.embodied.execution.orchestration.runtime.manager import RuntimeManager
from roboclaw.embodied.execution.orchestration.runtime.model import RuntimeSession, RuntimeStatus


@dataclass(frozen=True)
class ExecutionContext:
    """Resolved embodied execution state for one setup and runtime session."""

    setup_id: str
    assembly: AssemblyManifest
    deployment: DeploymentProfile
    target: ExecutionTarget
    robot: RobotManifest
    adapter_binding: Any
    profile: Any
    runtime: RuntimeSession
    preferred_language: str = "en"


@dataclass(frozen=True)
class ProcedureExecutionResult:
    """Normalized result returned to the controller."""

    procedure: ProcedureKind
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class ProcedureExecutor:
    """Execute a small control-surface subset of embodied procedures."""

    def __init__(self, tools: ToolRegistry, runtime_manager: RuntimeManager):
        self._loader = AdapterLoader(tools)
        self._runtime_manager = runtime_manager
        self._adapters: dict[str, Any] = {}

    def runtime_for(
        self,
        *,
        runtime_id: str,
        setup_id: str,
        assembly_id: str,
        deployment_id: str,
        target_id: str,
        adapter_id: str,
    ) -> RuntimeSession:
        try:
            return self._runtime_manager.get(runtime_id)
        except KeyError:
            return self._runtime_manager.create(
                session_id=runtime_id,
                assembly_id=assembly_id,
                deployment_id=deployment_id,
                target_id=target_id,
                adapter_id=adapter_id,
            )

    def _adapter(self, context: ExecutionContext) -> Any:
        adapter = self._adapters.get(context.runtime.id)
        if adapter is None:
            adapter = self._loader.load(
                binding=context.adapter_binding,
                assembly=context.assembly,
                deployment=context.deployment,
                target=context.target,
                robot=context.robot,
                profile=context.profile,
            )
            self._adapters[context.runtime.id] = adapter
        return adapter

    @staticmethod
    def _preferred_language(context: Any) -> str:
        return str(getattr(context, "preferred_language", "en") or "en")

    @staticmethod
    def _calibration_driver(context: ExecutionContext) -> Any | None:
        profile = getattr(context, "profile", None)
        return get_builtin_calibration_driver(getattr(profile, "calibration_driver_id", None))

    async def _best_effort_disconnect_before_calibration(self, context: ExecutionContext) -> None:
        adapter = self._adapters.get(context.runtime.id)
        if adapter is None:
            return
        disconnect = getattr(adapter, "disconnect", None)
        if disconnect is None:
            return
        try:
            await disconnect()
        except Exception:
            return
        context.runtime.status = RuntimeStatus.DISCONNECTED
        context.runtime.last_error = None

    async def execute_connect(
        self,
        context: ExecutionContext,
        *,
        on_progress: Any | None = None,
    ) -> ProcedureExecutionResult:
        preflight = self._ensure_calibration_ready(context)
        if preflight is not None and context.runtime.status != RuntimeStatus.READY:
            return preflight

        adapter = self._adapter(context)
        context.runtime.status = RuntimeStatus.CONNECTING

        probe = adapter.probe_env()
        deps = adapter.check_dependencies()
        if not deps.ok:
            missing = ", ".join(deps.missing_required) or "required ROS2 interfaces"
            context.runtime.status = RuntimeStatus.ERROR
            context.runtime.last_error = missing
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CONNECT,
                ok=False,
                message=f"Setup `{context.setup_id}` is not ready yet: missing {missing}.",
                details={"probe": probe.details, "missing_required": deps.missing_required},
            )

        connected = await adapter.connect(
            target_id=context.target.id,
            config=dict(context.deployment.connection),
        )
        if not connected.ok:
            context.runtime.status = RuntimeStatus.ERROR
            context.runtime.last_error = connected.message or connected.error_code
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CONNECT,
                ok=False,
                message=connected.message or f"Failed to connect setup `{context.setup_id}`.",
                details={"error_code": connected.error_code, **connected.details},
            )

        ready = await adapter.ready()
        if not ready.ready:
            context.runtime.status = RuntimeStatus.ERROR
            context.runtime.last_error = ready.message
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CONNECT,
                ok=False,
                message=ready.message or f"Setup `{context.setup_id}` is not ready for commands yet.",
                details={"blocked_operations": [item.value for item in ready.blocked_operations], **ready.details},
            )

        context.runtime.status = RuntimeStatus.READY
        context.runtime.last_error = None
        details = {"probe": probe.details, "target_id": context.target.id}
        if context.target.id == "sim":
            viewer_port = (context.deployment.connection or {}).get("viewer_port", 9878)
            details["viewer_url"] = f"http://0.0.0.0:{viewer_port}"
            details["viewer_message"] = "Simulation viewer available. Open the URL in a browser to see the robot."
        return ProcedureExecutionResult(
            procedure=ProcedureKind.CONNECT,
            ok=True,
            message=f"Connected setup `{context.setup_id}` on target `{context.target.id}`.",
            details=details,
        )

    async def execute_move(
        self,
        context: ExecutionContext,
        *,
        primitive_name: str,
        primitive_args: dict[str, Any] | None = None,
        on_progress: Any | None = None,
    ) -> ProcedureExecutionResult:
        if context.runtime.status != RuntimeStatus.READY:
            connected = await self.execute_connect(context, on_progress=on_progress)
            if not connected.ok:
                return connected

        adapter = self._adapter(context)
        context.runtime.status = RuntimeStatus.BUSY
        pre_state = await adapter.get_state()
        primitive = await adapter.execute_primitive(primitive_name, primitive_args or {})
        if not primitive.accepted:
            context.runtime.status = RuntimeStatus.ERROR
            context.runtime.last_error = primitive.message or primitive.error_code
            return ProcedureExecutionResult(
                procedure=ProcedureKind.MOVE,
                ok=False,
                message=primitive.message or f"Primitive `{primitive_name}` was rejected.",
                details={"error_code": primitive.error_code, **primitive.output},
            )

        post_state = await adapter.get_state()
        joint_deltas = self._joint_deltas(pre_state.values, post_state.values)
        context.runtime.status = RuntimeStatus.READY
        context.runtime.last_error = None
        completion = "completed" if primitive.completed is not False else "accepted"
        state_message = self._state_confirmation(primitive_name, pre_state.values, post_state.values)
        message = f"Primitive `{primitive_name}` {completion} on setup `{context.setup_id}`."
        if state_message:
            message = f"{message} {state_message}"
        return ProcedureExecutionResult(
            procedure=ProcedureKind.MOVE,
            ok=True,
            message=message,
            details={
                **primitive.output,
                "state_before": pre_state.values,
                "state_after": post_state.values,
                "state_changed": bool(joint_deltas),
                "joints_moved": [joint for joint, _ in joint_deltas],
            },
        )

    async def execute_debug(self, context: ExecutionContext) -> ProcedureExecutionResult:
        adapter = self._adapter(context)
        probe = adapter.probe_env()
        state = await adapter.get_state()
        snapshot = await adapter.debug_snapshot()
        context.runtime.status = RuntimeStatus.READY if snapshot.captured else RuntimeStatus.ERROR
        if not snapshot.captured:
            context.runtime.last_error = snapshot.message or snapshot.summary
        return ProcedureExecutionResult(
            procedure=ProcedureKind.DEBUG,
            ok=snapshot.captured,
            message=snapshot.summary,
            details={"probe": probe.details, "state": state.values, "artifacts": snapshot.artifacts},
        )

    async def execute_reset(self, context: ExecutionContext) -> ProcedureExecutionResult:
        adapter = self._adapter(context)
        stop_result = await adapter.stop(scope="all")
        reset_result = await adapter.reset(mode="home")
        if not reset_result.ok:
            context.runtime.status = RuntimeStatus.ERROR
            context.runtime.last_error = reset_result.message or reset_result.error_code
            return ProcedureExecutionResult(
                procedure=ProcedureKind.RESET,
                ok=False,
                message=reset_result.message or f"Failed to reset setup `{context.setup_id}`.",
                details={
                    "stop_message": stop_result.message,
                    "error_code": reset_result.error_code,
                    **reset_result.details,
                },
            )

        context.runtime.status = RuntimeStatus.READY
        context.runtime.last_error = None
        return ProcedureExecutionResult(
            procedure=ProcedureKind.RESET,
            ok=True,
            message=reset_result.message or f"Reset setup `{context.setup_id}` to home.",
            details={"stop_message": stop_result.message, **reset_result.details},
        )

    async def execute_calibrate(
        self,
        context: ExecutionContext,
        *,
        on_progress: Any | None = None,
    ) -> ProcedureExecutionResult:
        driver = self._calibration_driver(context)
        if driver is None:
            return self.describe_calibration(context)
        await self._best_effort_disconnect_before_calibration(context)
        return await driver.begin(context, on_progress=on_progress)

    def calibration_phase(self, context: ExecutionContext) -> str | None:
        driver = self._calibration_driver(context)
        if driver is None:
            return None
        return driver.phase(context)

    async def advance_calibration(
        self,
        context: ExecutionContext,
        *,
        user_input: str | None = None,
        on_progress: Any | None = None,
    ) -> ProcedureExecutionResult:
        driver = self._calibration_driver(context)
        if driver is None:
            return ProcedureExecutionResult(
                procedure=ProcedureKind.CALIBRATE,
                ok=False,
                message=localize_text(
                    self._preferred_language(context),
                    en="There is no pending calibration interaction for this setup. Tell me to calibrate first.",
                    zh="这个 setup 当前没有待继续的标定流程。请先告诉我开始标定。",
                ),
            )
        return await driver.advance(context, user_input=user_input, on_progress=on_progress)

    def describe_calibration(self, context: ExecutionContext) -> ProcedureExecutionResult:
        driver = self._calibration_driver(context)
        if driver is not None:
            return driver.describe(context)
        calibration_path = self._calibration_path(context)
        expected_path = str(calibration_path) if calibration_path is not None else None
        return ProcedureExecutionResult(
            procedure=ProcedureKind.CALIBRATE,
            ok=False,
            message=localize_text(
                self._preferred_language(context),
                en=(
                    f"Setup `{context.setup_id}` needs calibration before execution."
                    + (f" Expected canonical path: `{expected_path}`." if expected_path else "")
                    + " Tell me to calibrate after the hardware is ready so RoboClaw can walk you through it."
                ),
                zh=(
                    f"setup `{context.setup_id}` 在执行前需要先完成标定。"
                    + (f" 标准标定文件路径应为：`{expected_path}`。" if expected_path else "")
                    + " 等硬件准备好后，直接告诉我开始标定，我就会带你走完整个流程。"
                ),
            ),
        )

    def _calibration_path(self, context: ExecutionContext) -> Path | None:
        profile = context.profile
        if profile is None or not getattr(profile, "requires_calibration", False):
            return None
        if getattr(context.target, "id", None) == "sim":
            return None
        return profile.canonical_calibration_path()

    def _ensure_calibration_ready(self, context: ExecutionContext) -> ProcedureExecutionResult | None:
        calibration_path = self._calibration_path(context)
        if calibration_path is None or calibration_path.exists():
            return None

        context.runtime.status = RuntimeStatus.ERROR
        context.runtime.last_error = f"Missing calibration file: {calibration_path}"
        return ProcedureExecutionResult(
            procedure=ProcedureKind.CALIBRATE,
            ok=False,
            message=localize_text(
                self._preferred_language(context),
                en=(
                    f"Setup `{context.setup_id}` needs calibration before `connect` or motion."
                    f" Expected canonical path: `{calibration_path}`."
                    " Tell me to calibrate to start the registered calibration guide."
                ),
                zh=(
                    f"setup `{context.setup_id}` 在 `connect` 或运动前需要先标定。"
                    f" 标准标定文件路径应为：`{calibration_path}`。"
                    " 直接告诉我开始标定，我就会启动当前本体注册的标定引导。"
                ),
            ),
            details={"calibration_path": str(calibration_path)},
        )

    @staticmethod
    def _state_confirmation(
        primitive_name: str,
        pre_state: dict[str, Any],
        post_state: dict[str, Any],
    ) -> str:
        parts: list[str] = []
        gripper_before = ProcedureExecutor._gripper_percent(pre_state)
        gripper_after = ProcedureExecutor._gripper_percent(post_state)
        if primitive_name in {"gripper_open", "gripper_close"} and gripper_after is not None:
            if primitive_name == "gripper_open":
                label = "open" if gripper_after >= 60 else "partially open"
            elif primitive_name == "gripper_close":
                label = "closed" if gripper_after <= 40 else "partially open"
            elif gripper_after >= 80:
                label = "open"
            elif gripper_after <= 20:
                label = "closed"
            else:
                label = "partially open"
            if gripper_before is not None:
                parts.append(
                    f"Current gripper state: {label} "
                    f"({gripper_after:.1f}% open, was {gripper_before:.1f}%)."
                )
            else:
                parts.append(f"Current gripper state: {label} ({gripper_after:.1f}% open).")
        joint_deltas = ProcedureExecutor._joint_deltas(pre_state, post_state)
        if joint_deltas:
            moved = ", ".join(f"{joint} ({delta:+.2f})" for joint, delta in joint_deltas)
            parts.append(f"Observed joint movement: {moved}.")
        return " ".join(parts)

    @staticmethod
    def _joint_deltas(pre_state: dict[str, Any], post_state: dict[str, Any]) -> list[tuple[str, float]]:
        before = ProcedureExecutor._joint_positions(pre_state)
        after = ProcedureExecutor._joint_positions(post_state)
        return [
            (joint, delta)
            for joint in sorted(before.keys() & after.keys())
            if (
                isinstance(before[joint], (int, float))
                and isinstance(after[joint], (int, float))
                and not isinstance(before[joint], bool)
                and not isinstance(after[joint], bool)
                and abs(delta := float(after[joint]) - float(before[joint])) > 0.01
            )
        ]

    @staticmethod
    def _joint_positions(values: dict[str, Any]) -> dict[str, Any]:
        raw = values.get("joint_positions")
        if isinstance(raw, dict):
            return raw
        return {
            key: value
            for key, value in values.items()
            if key not in {"raw", "connected", "gripper_percent"} and isinstance(value, (int, float)) and not isinstance(value, bool)
        }

    @staticmethod
    def _gripper_percent(values: dict[str, Any]) -> float | None:
        raw = values.get("gripper_percent")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
