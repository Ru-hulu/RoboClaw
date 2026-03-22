import importlib
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from roboclaw.embodied.builtins import register_builtin_embodiment
from roboclaw.embodied.builtins.model import BuiltinEmbodiment
from roboclaw.embodied import RGB_CAMERA, SO101_ROBOT, build_default_catalog
from roboclaw.embodied.definition.foundation.schema import (
    CarrierKind,
    CommandMode,
    CompletionSemantics,
    RobotType,
    TransportKind,
    ValueUnit,
)
from roboclaw.embodied.definition.components.robots.model import (
    PrimitiveSpec,
    RobotManifest,
)
from roboclaw.embodied.execution.integration.adapters.ros2.profiles import Ros2EmbodimentProfile
from roboclaw.embodied.definition.systems.assemblies import (
    AssemblyBlueprint,
    FrameTransform,
    RobotAttachment,
    ToolAttachment,
    Transform3D,
    compose_assemblies,
)
from roboclaw.embodied.definition.systems.assemblies.model import SensorAttachment
from roboclaw.embodied.execution.integration.adapters import (
    AdapterBinding,
    AdapterCompatibilitySpec,
    AdapterHealthMode,
    AdapterLifecycleContract,
    AdapterOperation,
    AdapterOperationResult,
    AdapterStateSnapshot,
    CompatibilityCheckItem,
    CompatibilityCheckResult,
    CompatibilityComponent,
    DebugSnapshotResult,
    DegradedModeSpec,
    DependencyCheckItem,
    DependencyCheckResult,
    DependencyKind,
    DependencySpec,
    EnvironmentProbeResult,
    ErrorCategory,
    ErrorCodeSpec,
    HealthReport,
    OperationTimeout,
    PrimitiveExecutionResult,
    ReadinessReport,
    SensorCaptureResult,
    TimeoutPolicy,
    VersionConstraint,
)
from roboclaw.embodied.execution.integration.control_surfaces import (
    ARM_HAND_CONTROL_SURFACE_PROFILE,
    DEFAULT_CONTROL_SURFACE_PROFILES,
    DRONE_CONTROL_SURFACE_PROFILE,
    HUMANOID_WHOLE_BODY_CONTROL_SURFACE_PROFILE,
    MOBILE_BASE_FLEET_CONTROL_SURFACE_PROFILE,
    SIMULATOR_CONTROL_SURFACE_PROFILE,
    EmbodimentDomain,
    ControlSurfaceKind,
    ControlSurfaceProfile,
)
from roboclaw.embodied.execution.integration.carriers.real import build_real_ros2_target
from roboclaw.embodied.execution.integration.transports.ros2 import build_standard_ros2_contract
from roboclaw.embodied.execution.observability import (
    RawEvidenceHandle,
    TelemetryEvent,
    TelemetryKind,
    TelemetryPhase,
    TelemetrySeverity,
)
from roboclaw.embodied.execution.orchestration.procedures import (
    AdapterProcedureAction,
    CancellationMode,
    DEFAULT_PROCEDURES,
    OrchestratorProcedureAction,
    ProcedureActionTarget,
)
from roboclaw.embodied.execution.orchestration.runtime import RuntimeManager, RuntimeStatus
from roboclaw.embodied.workspace import (
    WorkspaceAssetKind,
    WorkspaceInspectOptions,
    WorkspaceIssueLevel,
    WorkspaceLintProfile,
    WorkspaceMigrationPolicy,
    WorkspaceProvenance,
    WorkspaceValidationStage,
    inspect_workspace_assets,
)
import roboclaw.embodied.builtins.registry as builtins_registry


def _workspace_blueprint() -> AssemblyBlueprint:
    return AssemblyBlueprint(
        id="workspace_so101",
        name="Workspace SO101",
        description="Workspace-generated embodied assembly.",
        robots=(
            RobotAttachment(
                attachment_id="primary",
                robot_id="so101",
            ),
        ),
        sensors=(
            SensorAttachment(
                attachment_id="wrist_camera",
                sensor_id="rgb_camera",
                mount="wrist",
                mount_frame="tool0",
                mount_transform=Transform3D(),
            ),
        ),
        execution_targets=(
            build_real_ros2_target(
                target_id="real",
                description="Real target",
                ros2=build_standard_ros2_contract("workspace_so101", "real"),
            ),
        ),
        default_execution_target_id="real",
        frame_transforms=(
            FrameTransform(
                parent_frame="world",
                child_frame="base_link",
                transform=Transform3D(),
            ),
            FrameTransform(
                parent_frame="base_link",
                child_frame="tool0",
                transform=Transform3D(),
            ),
        ),
        tools=(
            ToolAttachment(
                attachment_id="primary_tool",
                robot_attachment_id="primary",
                tool_id="parallel_gripper",
                mount_frame="tool0",
                tcp_frame="tcp",
                kind="end_effector",
            ),
        ),
    )


def test_embodied_catalog_contains_reusable_definitions_only() -> None:
    catalog = build_default_catalog()

    assert catalog.robots.get("so101").robot_type == RobotType.ARM
    assert catalog.sensors.get("rgb_camera").default_topic_name == "image_raw"
    assert catalog.assemblies.list() == ()
    assert len(catalog.control_surface_profiles.list()) == len(DEFAULT_CONTROL_SURFACE_PROFILES)
    assert catalog.adapters.for_assembly("workspace_so101") == ()
    assert catalog.deployments.for_assembly("workspace_so101") == ()
    assert RGB_CAMERA.supports_intrinsics is True


def test_default_catalog_discovers_builtin_registrations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        builtins_registry,
        "_BUILTINS_BY_ID",
        dict(builtins_registry._BUILTINS_BY_ID),
    )
    monkeypatch.setattr(
        builtins_registry,
        "_BUILTINS_BY_ROBOT_ID",
        dict(builtins_registry._BUILTINS_BY_ROBOT_ID),
    )
    register_builtin_embodiment(
        BuiltinEmbodiment(
            id="demo_arm",
            robot=RobotManifest(
                id="demo_arm",
                name="Demo Arm",
                description="Fake built-in robot for registry discovery tests.",
                robot_type=RobotType.ARM,
                capability_families=SO101_ROBOT.capability_families,
                primitives=(
                    PrimitiveSpec(
                        name="demo_ping",
                        kind=SO101_ROBOT.primitives[0].kind,
                        capability_family=SO101_ROBOT.primitives[0].capability_family,
                        command_mode=SO101_ROBOT.primitives[0].command_mode,
                        description="Demo primitive.",
                    ),
                ),
                observation_schema=SO101_ROBOT.observation_schema,
                health_schema=SO101_ROBOT.health_schema,
            ),
            ros2_profile=Ros2EmbodimentProfile(
                id="demo_arm_ros2_standard",
                robot_id="demo_arm",
            ),
            onboarding_aliases=("demo arm",),
        )
    )

    catalog = build_default_catalog()

    assert catalog.robots.get("demo_arm").name == "Demo Arm"


def test_pyproject_no_longer_packages_vendored_scservo_sdk() -> None:
    root = Path(__file__).resolve().parents[1]
    with open(root / "pyproject.toml", "rb") as fh:
        data = tomllib.load(fh)

    wheel = data["tool"]["hatch"]["build"]["targets"]["wheel"]
    include = data["tool"]["hatch"]["build"]["include"]
    sdist = data["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]

    assert "scservo_sdk" not in wheel["packages"]
    assert not any("scservo_sdk" in item for item in include)
    assert not any("scservo_sdk" in item for item in sdist)
    assert not (root / "scservo_sdk").exists()


def test_control_surface_profile_contract_is_machine_checkable() -> None:
    catalog = build_default_catalog()

    domains = {profile.domain for profile in catalog.control_surface_profiles.list()}
    assert EmbodimentDomain.ARM_HAND in domains
    assert EmbodimentDomain.HUMANOID_WHOLE_BODY in domains
    assert EmbodimentDomain.MOBILE_BASE_FLEET in domains
    assert EmbodimentDomain.DRONE in domains
    assert EmbodimentDomain.SIMULATOR in domains

    arm_profile = catalog.control_surface_profiles.get(ARM_HAND_CONTROL_SURFACE_PROFILE.id)
    assert arm_profile.kind == ControlSurfaceKind.ROS2_CONTROL
    assert arm_profile.control_surfaces[0].id == "joint_trajectory"
    assert arm_profile.supports_robot_type(RobotType.ARM)

    drone_profile = catalog.control_surface_profiles.get(DRONE_CONTROL_SURFACE_PROFILE.id)
    assert drone_profile.supports_robot_type(RobotType.DRONE)

    adapter = AdapterBinding(
        id="workspace_ros2_adapter_with_control_surface_profile",
        assembly_id="workspace_so101",
        transport=TransportKind.ROS2,
        implementation="workspace.adapters.ros2:Adapter",
        supported_targets=("real",),
        control_surface_profile_id=ARM_HAND_CONTROL_SURFACE_PROFILE.id,
        compatibility=AdapterCompatibilitySpec(
            adapter_api_version="1.0",
            constraints=(
                VersionConstraint(
                    component=CompatibilityComponent.TRANSPORT,
                    target="ros2",
                    requirement=">=1.0,<2.0",
                ),
                VersionConstraint(
                    component=CompatibilityComponent.CONTROL_SURFACE_PROFILE,
                    target=ARM_HAND_CONTROL_SURFACE_PROFILE.id,
                    requirement=">=1.0,<2.0",
                ),
            ),
        ),
    )
    assert adapter.control_surface_profile_id == ARM_HAND_CONTROL_SURFACE_PROFILE.id
    assert not hasattr(catalog, "bridges")
    assert not hasattr(adapter, "bridge_id")
    assert not hasattr(CompatibilityComponent, "BRIDGE")
    assert len(catalog.control_surface_profiles.for_domain(EmbodimentDomain.HUMANOID_WHOLE_BODY)) == 1
    assert len(catalog.control_surface_profiles.for_domain(EmbodimentDomain.MOBILE_BASE_FLEET)) == 1
    assert len(catalog.control_surface_profiles.for_domain(EmbodimentDomain.SIMULATOR)) == 1
    assert isinstance(HUMANOID_WHOLE_BODY_CONTROL_SURFACE_PROFILE, ControlSurfaceProfile)
    assert isinstance(MOBILE_BASE_FLEET_CONTROL_SURFACE_PROFILE, ControlSurfaceProfile)
    assert isinstance(SIMULATOR_CONTROL_SURFACE_PROFILE, ControlSurfaceProfile)


def test_old_bridge_public_surface_is_gone() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("roboclaw.embodied.execution.integration.bridges")


def test_workspace_blueprint_can_be_composed_into_a_variant() -> None:
    base = _workspace_blueprint()
    overhead_variant = base.remap_sensor(
        "wrist_camera",
        to_mount="overhead",
    )
    composed = compose_assemblies(base, overhead_variant).build()

    assert composed.sensors == (
        SensorAttachment(
            attachment_id="wrist_camera",
            sensor_id="rgb_camera",
            mount="overhead",
            mount_frame="tool0",
            mount_transform=Transform3D(),
            config=None,
            optional=False,
        ),
    )
    assert composed.execution_target("real").carrier == CarrierKind.REAL
    assert composed.frame_transforms[0].child_frame == "base_link"
    assert composed.tools[0].attachment_id == "primary_tool"


def test_runtime_manager_tracks_active_session() -> None:
    manager = RuntimeManager()
    session = manager.create(
        session_id="demo",
        assembly_id="workspace_so101",
        target_id="real",
        deployment_id="workspace_local",
        adapter_id="workspace_ros2_adapter",
    )

    manager.mark_status("demo", RuntimeStatus.READY)

    assert session.assembly_id == "workspace_so101"
    assert session.adapter_id == "workspace_ros2_adapter"
    assert session.status == RuntimeStatus.READY
    assert SO101_ROBOT.suggested_sensor_ids == ("rgb_camera",)


def test_so101_action_and_observation_contracts_are_machine_checkable() -> None:
    move_joint = SO101_ROBOT.primitive("move_joint")
    assert move_joint is not None
    assert move_joint.command_mode == CommandMode.POSITION
    assert move_joint.parameters[0].unit == ValueUnit.RADIAN
    assert move_joint.action_schema is not None
    assert move_joint.action_schema.command_mode == CommandMode.POSITION
    assert move_joint.action_schema.parameter_order == ("positions",)
    assert move_joint.completion is not None
    assert move_joint.completion.semantics == CompletionSemantics.GOAL_REACHED

    scan = SO101_ROBOT.primitive("scan_panorama")
    assert scan is not None
    assert scan.command_mode == CommandMode.MISSION

    assert SO101_ROBOT.observation_schema.id == "so101_observation_v1"
    assert len(SO101_ROBOT.observation_schema.fields) > 0
    assert SO101_ROBOT.health_schema.id == "so101_health_v1"
    assert len(SO101_ROBOT.health_schema.fields) > 0


def test_assembly_topology_contract_is_machine_checkable() -> None:
    assembly = _workspace_blueprint().build()

    assert assembly.default_execution_target_id == "real"
    assert assembly.execution_target().id == "real"
    assert assembly.tools[0].robot_attachment_id == "primary"
    assert assembly.frame_transforms[1].parent_frame == "base_link"


def test_adapter_lifecycle_contract_is_machine_checkable() -> None:
    lifecycle = AdapterLifecycleContract(
        dependencies=(
            DependencySpec(
                id="ros2_control_surface",
                kind=DependencyKind.ROS2_NODE,
                description="ROS2 control surface node must be available.",
            ),
        ),
        timeout_policy=TimeoutPolicy(
            default_timeout_s=10.0,
            operations=(
                OperationTimeout(
                    operation=AdapterOperation.CONNECT,
                    timeout_s=30.0,
                    retries=2,
                    backoff_s=1.0,
                ),
            ),
        ),
        error_codes=(
            ErrorCodeSpec(
                code="DEP_MISSING",
                category=ErrorCategory.DEPENDENCY,
                description="Dependency check failed.",
                recoverable=False,
                related_operation=AdapterOperation.DEPENDENCY_CHECK,
            ),
        ),
    )
    binding = AdapterBinding(
        id="workspace_ros2_adapter",
        assembly_id="workspace_so101",
        transport=TransportKind.ROS2,
        implementation="workspace.adapters.ros2:Adapter",
        supported_targets=("real",),
        lifecycle=lifecycle,
        degraded_modes=(
            DegradedModeSpec(
                mode=AdapterHealthMode.DEGRADED,
                description="Transport degraded; only stop/recover paths are available.",
                allowed_operations=(
                    AdapterOperation.READY,
                    AdapterOperation.STOP,
                    AdapterOperation.RECOVER,
                ),
                entered_on_error_codes=("DEP_MISSING",),
            ),
        ),
        compatibility=AdapterCompatibilitySpec(
            adapter_api_version="1.0",
            constraints=(
                VersionConstraint(
                    component=CompatibilityComponent.TRANSPORT,
                    target="ros2",
                    requirement=">=1.0,<2.0",
                ),
                VersionConstraint(
                    component=CompatibilityComponent.CONTROL_SURFACE_PROFILE,
                    target=ARM_HAND_CONTROL_SURFACE_PROFILE.id,
                    requirement=">=1.0,<2.0",
                    required=False,
                ),
            ),
        ),
    )

    assert binding.lifecycle.supports(AdapterOperation.CONNECT)
    assert binding.lifecycle.supports(AdapterOperation.READY)
    assert binding.lifecycle.timeout_policy.timeout_for(AdapterOperation.CONNECT).timeout_s == 30.0
    assert binding.lifecycle.error_codes[0].category == ErrorCategory.DEPENDENCY
    assert binding.degraded_modes[0].mode == AdapterHealthMode.DEGRADED
    assert binding.degraded_modes[0].entered_on_error_codes == ("DEP_MISSING",)
    assert binding.compatibility.for_component(CompatibilityComponent.TRANSPORT)[0].target == "ros2"


def test_adapter_result_models_are_machine_checkable() -> None:
    probe = EnvironmentProbeResult(
        adapter_id="workspace_ros2_adapter",
        assembly_id="workspace_so101",
        transport=TransportKind.ROS2,
        available_targets=("real", "sim_gazebo"),
        detected_dependencies=("ros2_control_surface", "camera_node"),
        notes=("probe complete",),
        details={"latency_ms": 4},
    )
    assert probe.transport == TransportKind.ROS2
    assert probe.available_targets == ("real", "sim_gazebo")

    dep_item = DependencyCheckItem(
        dependency_id="ros2_control_surface",
        kind=DependencyKind.ROS2_NODE,
        required=True,
        available=True,
        message="control surface reachable",
    )
    dep_result = DependencyCheckResult(
        adapter_id="workspace_ros2_adapter",
        ok=True,
        items=(dep_item,),
        checked_dependencies=("ros2_control_surface",),
    )
    assert dep_result.ok is True
    assert dep_result.items[0].kind == DependencyKind.ROS2_NODE

    connect_result = AdapterOperationResult(
        operation=AdapterOperation.CONNECT,
        ok=True,
        target_id="real",
        message="connected",
        details={"session": "demo"},
    )
    assert connect_result.operation == AdapterOperation.CONNECT
    assert connect_result.target_id == "real"

    readiness = ReadinessReport(
        ready=True,
        target_id="real",
        details={"controller_state": "active"},
    )
    assert readiness.ready is True

    health = HealthReport(
        mode=AdapterHealthMode.DEGRADED,
        healthy=False,
        error_codes=("TRANSPORT_UNAVAILABLE",),
        blocked_operations=(AdapterOperation.CONNECT,),
        message="running in degraded mode",
    )
    assert health.mode == AdapterHealthMode.DEGRADED
    assert health.healthy is False

    compatibility = CompatibilityCheckResult(
        adapter_api_version="1.0",
        compatible=True,
        checks=(
            CompatibilityCheckItem(
                component=CompatibilityComponent.TRANSPORT,
                target="ros2",
                requirement=">=1.0,<2.0",
                satisfied=True,
            ),
        ),
    )
    assert compatibility.compatible is True
    assert compatibility.checks[0].component == CompatibilityComponent.TRANSPORT

    state = AdapterStateSnapshot(
        source="adapter",
        target_id="real",
        values={"joint_positions": {"j1": 0.1}},
        updated_fields=("joint_positions",),
    )
    assert state.values["joint_positions"]["j1"] == 0.1

    primitive = PrimitiveExecutionResult(
        primitive_name="move_joint",
        accepted=True,
        completed=True,
        status="succeeded",
        output={"duration_s": 1.2},
    )
    assert primitive.completed is True
    assert primitive.status == "succeeded"

    capture = SensorCaptureResult(
        sensor_id="wrist_camera",
        mode="latest",
        captured=True,
        media_type="image/jpeg",
        payload_ref="file:///tmp/frame.jpg",
        metadata={"width": 640, "height": 480},
    )
    assert capture.captured is True
    assert capture.media_type == "image/jpeg"

    debug = DebugSnapshotResult(
        captured=True,
        summary="adapter debug snapshot",
        artifacts=("file:///tmp/debug.json",),
        payload={"fault_code": "none"},
    )
    assert debug.captured is True
    assert debug.artifacts[0] == "file:///tmp/debug.json"


def test_procedure_contract_is_machine_checkable() -> None:
    connect = next(procedure for procedure in DEFAULT_PROCEDURES if procedure.id == "connect_default")

    assert connect.required_capabilities
    assert connect.step_edges
    assert connect.entry_step_ids == ("probe_env",)
    assert connect.terminal_step_ids == ("verify_state",)

    connect_step = next(step for step in connect.steps if step.id == "connect")
    assert connect_step.timeout_s == 30.0
    assert connect_step.retry_policy.max_retries == 2
    assert connect.cancellation_policy.mode == CancellationMode.SAFE_POINT
    select_target_step = next(step for step in connect.steps if step.id == "select_target")
    assert select_target_step.action.target == ProcedureActionTarget.ORCHESTRATOR
    assert select_target_step.action.name == OrchestratorProcedureAction.RESOLVE_TARGET.value

    assert connect_step.cancellation is not None
    assert connect_step.cancellation.mode == CancellationMode.IMMEDIATE
    assert connect_step.action.target == ProcedureActionTarget.ADAPTER
    assert connect_step.action.name == AdapterProcedureAction.CONNECT.value
    assert connect_step.cancellation.cancel_action is not None
    assert connect_step.cancellation.cancel_action.target == ProcedureActionTarget.ADAPTER
    assert connect_step.cancellation.cancel_action.name == AdapterProcedureAction.DISCONNECT.value
    assert connect.operator_interventions[0].step_id == "connect"

    reset = next(procedure for procedure in DEFAULT_PROCEDURES if procedure.id == "reset_default")
    assert reset.cancellation_policy.mode == CancellationMode.NON_CANCELLABLE


def test_telemetry_contract_is_machine_checkable() -> None:
    event = TelemetryEvent(
        timestamp=datetime.now(timezone.utc),
        correlation_id="corr-123",
        source_component="runtime.session_manager",
        kind=TelemetryKind.ACTION,
        severity=TelemetrySeverity.INFO,
        message="Executed move primitive.",
        payload={"primitive": "move_joint", "status": "success"},
        raw_evidence=(
            RawEvidenceHandle(
                id="bag-1",
                uri="file:///tmp/trace/demo.bag",
                media_type="application/x-rosbag2",
            ),
        ),
        phase=TelemetryPhase.COMPLETE,
        tags=("move", "primitive"),
        replay_handle="replay://demo/corr-123",
    )

    assert event.correlation_id == "corr-123"
    assert event.source_component == "runtime.session_manager"
    assert event.kind == TelemetryKind.ACTION
    assert event.severity == TelemetrySeverity.INFO
    assert event.raw_evidence[0].id == "bag-1"


def test_workspace_asset_contract_detects_duplicate_ids(tmp_path: Path) -> None:
    robots_dir = tmp_path / "embodied" / "robots"
    robots_dir.mkdir(parents=True, exist_ok=True)

    robots_dir.joinpath("robot_a.py").write_text(
        "\n".join(
            [
                "from roboclaw.embodied import SO101_ROBOT",
                "from roboclaw.embodied.workspace import (",
                "    WORKSPACE_SCHEMA_VERSION,",
                "    WorkspaceAssetContract,",
                "    WorkspaceAssetKind,",
                "    WorkspaceExportConvention,",
                ")",
                "",
                "WORKSPACE_ASSET = WorkspaceAssetContract(",
                "    kind=WorkspaceAssetKind.ROBOT,",
                "    schema_version=WORKSPACE_SCHEMA_VERSION,",
                "    export_convention=WorkspaceExportConvention.ROBOT,",
                ")",
                "",
                "ROBOT = SO101_ROBOT",
                "",
            ]
        ),
        encoding="utf-8",
    )
    robots_dir.joinpath("robot_b.py").write_text(
        "\n".join(
            [
                "from roboclaw.embodied import SO101_ROBOT",
                "from roboclaw.embodied.workspace import (",
                "    WORKSPACE_SCHEMA_VERSION,",
                "    WorkspaceAssetContract,",
                "    WorkspaceAssetKind,",
                "    WorkspaceExportConvention,",
                ")",
                "",
                "WORKSPACE_ASSET = WorkspaceAssetContract(",
                "    kind=WorkspaceAssetKind.ROBOT,",
                "    schema_version=WORKSPACE_SCHEMA_VERSION,",
                "    export_convention=WorkspaceExportConvention.ROBOT,",
                ")",
                "",
                "ROBOT = SO101_ROBOT",
                "",
            ]
        ),
        encoding="utf-8",
    )

    report = inspect_workspace_assets(tmp_path)

    assert report.has_errors
    assert any(issue.code == "DUPLICATE_ASSET_ID" for issue in report.issues)
    assert any(issue.stage == WorkspaceValidationStage.SCHEMA for issue in report.issues)
    assert report.loaded_counts[WorkspaceAssetKind.ROBOT] == 1


def test_workspace_asset_contract_supports_migration_policy(tmp_path: Path) -> None:
    robots_dir = tmp_path / "embodied" / "robots"
    robots_dir.mkdir(parents=True, exist_ok=True)

    robots_dir.joinpath("future_schema.py").write_text(
        "\n".join(
            [
                "from roboclaw.embodied import SO101_ROBOT",
                "from roboclaw.embodied.workspace import (",
                "    WorkspaceAssetContract,",
                "    WorkspaceAssetKind,",
                "    WorkspaceExportConvention,",
                "    WorkspaceMigrationPolicy,",
                ")",
                "",
                "WORKSPACE_ASSET = WorkspaceAssetContract(",
                "    kind=WorkspaceAssetKind.ROBOT,",
                "    schema_version='2.0',",
                "    export_convention=WorkspaceExportConvention.ROBOT,",
                "    migration_policy=WorkspaceMigrationPolicy.ACCEPT_UNSUPPORTED,",
                ")",
                "",
                "ROBOT = SO101_ROBOT",
                "",
            ]
        ),
        encoding="utf-8",
    )

    report = inspect_workspace_assets(tmp_path)

    assert report.has_errors is False
    assert report.has_warnings
    assert any(issue.level == WorkspaceIssueLevel.WARNING for issue in report.issues)
    assert any(issue.code == "UNSUPPORTED_SCHEMA_VERSION" for issue in report.issues)
    assert any(issue.stage == WorkspaceValidationStage.SCHEMA for issue in report.issues)
    assert any("accept_unsupported" in issue.message for issue in report.issues)
    assert report.loaded_counts[WorkspaceAssetKind.ROBOT] == 1
    assert WorkspaceMigrationPolicy.ACCEPT_UNSUPPORTED.value == "accept_unsupported"


def test_workspace_dry_run_reports_staged_provenance(tmp_path: Path) -> None:
    robots_dir = tmp_path / "embodied" / "robots"
    robots_dir.mkdir(parents=True, exist_ok=True)

    robots_dir.joinpath("robot.py").write_text(
        "\n".join(
            [
                "from roboclaw.embodied import SO101_ROBOT",
                "from roboclaw.embodied.workspace import (",
                "    WORKSPACE_SCHEMA_VERSION,",
                "    WorkspaceAssetContract,",
                "    WorkspaceAssetKind,",
                "    WorkspaceExportConvention,",
                "    WorkspaceProvenance,",
                ")",
                "",
                "WORKSPACE_ASSET = WorkspaceAssetContract(",
                "    kind=WorkspaceAssetKind.ROBOT,",
                "    schema_version=WORKSPACE_SCHEMA_VERSION,",
                "    export_convention=WorkspaceExportConvention.ROBOT,",
                "    provenance=WorkspaceProvenance(",
                "        source='workspace',",
                "        generator='roboclaw_agent',",
                "        generated_by='agent:test',",
                "        generated_at='2026-03-17T15:00:00Z',",
                "    ),",
                ")",
                "",
                "ROBOT = SO101_ROBOT",
                "",
            ]
        ),
        encoding="utf-8",
    )

    report = inspect_workspace_assets(tmp_path)

    assert report.has_errors is False
    assert report.staged_assets
    staged = report.staged_assets[0]
    assert staged.kind == WorkspaceAssetKind.ROBOT
    assert staged.provenance.generator == "roboclaw_agent"
    assert staged.provenance.generated_by == "agent:test"
    assert report.stage_counts[WorkspaceValidationStage.LINT] == 0


def test_workspace_strict_lint_blocks_missing_contract_metadata(tmp_path: Path) -> None:
    robots_dir = tmp_path / "embodied" / "robots"
    robots_dir.mkdir(parents=True, exist_ok=True)

    robots_dir.joinpath("legacy_robot.py").write_text(
        "\n".join(
            [
                "from roboclaw.embodied import SO101_ROBOT",
                "ROBOT = SO101_ROBOT",
                "",
            ]
        ),
        encoding="utf-8",
    )

    report = inspect_workspace_assets(
        tmp_path,
        options=WorkspaceInspectOptions(lint_profile=WorkspaceLintProfile.STRICT),
    )

    assert report.has_errors
    assert any(issue.code == "CONTRACT_METADATA_MISSING" for issue in report.issues)
    assert any(issue.stage == WorkspaceValidationStage.LINT for issue in report.issues)
