"""Assembly manifests compose robots, sensors, transports, and carriers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from roboclaw.embodied.execution.integration.carriers import ExecutionTarget


@dataclass(frozen=True)
class RobotAttachment:
    """Attach a robot manifest into one assembly."""

    attachment_id: str
    robot_id: str
    role: str = "primary"
    config: Any | None = None


@dataclass(frozen=True)
class SensorAttachment:
    """Attach a sensor manifest into one assembly."""

    attachment_id: str
    sensor_id: str
    mount: str
    mount_frame: str | None = None
    mount_transform: Transform3D | None = None
    config: Any | None = None
    optional: bool = False


@dataclass(frozen=True)
class Transform3D:
    """Rigid transform represented in XYZ translation + RPY rotation."""

    translation_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_rpy: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class FrameTransform:
    """Frame relation used by assembly topology."""

    parent_frame: str
    child_frame: str
    transform: Transform3D = field(default_factory=Transform3D)
    static: bool = True
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ToolAttachment:
    """Attach a tool or end-effector to one robot attachment."""

    attachment_id: str
    robot_attachment_id: str
    tool_id: str
    mount_frame: str
    tcp_frame: str | None = None
    kind: str = "end_effector"
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AssemblyManifest:
    """Composed system definition."""

    id: str
    name: str
    description: str
    robots: tuple[RobotAttachment, ...]
    sensors: tuple[SensorAttachment, ...]
    execution_targets: tuple[ExecutionTarget, ...]
    default_execution_target_id: str | None = None
    frame_transforms: tuple[FrameTransform, ...] = field(default_factory=tuple)
    tools: tuple[ToolAttachment, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.robots:
            raise ValueError("Assembly manifest must contain at least one robot.")
        if not self.execution_targets:
            raise ValueError("Assembly manifest must declare at least one execution target.")

        target_ids = [target.id for target in self.execution_targets]
        if len(set(target_ids)) != len(target_ids):
            raise ValueError(f"Duplicate execution target ids in assembly '{self.id}'.")
        robot_attachment_ids = [robot.attachment_id for robot in self.robots]
        if len(set(robot_attachment_ids)) != len(robot_attachment_ids):
            raise ValueError(f"Duplicate robot attachment ids in assembly '{self.id}'.")
        sensor_attachment_ids = [sensor.attachment_id for sensor in self.sensors]
        if len(set(sensor_attachment_ids)) != len(sensor_attachment_ids):
            raise ValueError(f"Duplicate sensor attachment ids in assembly '{self.id}'.")
        frame_child_ids = [frame.child_frame for frame in self.frame_transforms]
        if len(set(frame_child_ids)) != len(frame_child_ids):
            raise ValueError(f"Duplicate frame child ids in assembly '{self.id}'.")
        tool_attachment_ids = [tool.attachment_id for tool in self.tools]
        if len(set(tool_attachment_ids)) != len(tool_attachment_ids):
            raise ValueError(f"Duplicate tool attachment ids in assembly '{self.id}'.")

        robot_attachment_set = set(robot_attachment_ids)
        target_set = set(target_ids)
        frame_set = set(frame.parent_frame for frame in self.frame_transforms) | set(frame_child_ids)
        frame_set.update({"world"})
        frame_set.update(
            tool_frame
            for tool in self.tools
            for tool_frame in (tool.mount_frame, tool.tcp_frame)
            if tool_frame is not None
        )

        for sensor in self.sensors:
            if sensor.mount_frame is not None and sensor.mount_frame not in frame_set:
                raise ValueError(
                    f"Sensor attachment '{sensor.attachment_id}' references unknown mount_frame "
                    f"'{sensor.mount_frame}' in assembly '{self.id}'."
                )
            if sensor.mount_transform is not None and sensor.mount_frame is None:
                raise ValueError(
                    f"Sensor attachment '{sensor.attachment_id}' defines mount_transform "
                    f"without mount_frame in assembly '{self.id}'."
                )

        for tool in self.tools:
            if tool.robot_attachment_id not in robot_attachment_set:
                raise ValueError(
                    f"Tool '{tool.attachment_id}' references unknown robot attachment "
                    f"'{tool.robot_attachment_id}' in assembly '{self.id}'."
                )

        default_target = self.default_execution_target_id or self.execution_targets[0].id
        if default_target not in target_ids:
            raise ValueError(
                f"Default execution target '{default_target}' is not defined in assembly '{self.id}'."
            )
        object.__setattr__(self, "default_execution_target_id", default_target)

    def execution_target(self, target_id: str | None = None) -> ExecutionTarget:
        resolved_id = target_id or self.default_execution_target_id
        for target in self.execution_targets:
            if target.id == resolved_id:
                return target
        raise KeyError(f"Unknown execution target '{resolved_id}' for assembly '{self.id}'.")
