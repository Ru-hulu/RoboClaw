"""Assembly blueprint composition."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from roboclaw.embodied.definition.systems.assemblies.model import (
    AssemblyManifest,
    FrameTransform,
    RobotAttachment,
    SensorAttachment,
    ToolAttachment,
)
from roboclaw.embodied.execution.integration.carriers import ExecutionTarget


def _dedupe_by_key(items, key_fn):
    """Keep the last item for each key while preserving final order."""

    seen = set()
    result = []
    for item in reversed(tuple(items)):
        key = key_fn(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    result.reverse()
    return tuple(result)


@dataclass(frozen=True)
class AssemblyBlueprint:
    """Immutable assembly composition unit."""

    id: str
    name: str
    description: str
    robots: tuple[RobotAttachment, ...] = field(default_factory=tuple)
    sensors: tuple[SensorAttachment, ...] = field(default_factory=tuple)
    execution_targets: tuple[ExecutionTarget, ...] = field(default_factory=tuple)
    default_execution_target_id: str | None = None
    frame_transforms: tuple[FrameTransform, ...] = field(default_factory=tuple)
    tools: tuple[ToolAttachment, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_manifest(cls, manifest: AssemblyManifest) -> "AssemblyBlueprint":
        return cls(
            id=manifest.id,
            name=manifest.name,
            description=manifest.description,
            robots=manifest.robots,
            sensors=manifest.sensors,
            execution_targets=manifest.execution_targets,
            default_execution_target_id=manifest.default_execution_target_id,
            frame_transforms=manifest.frame_transforms,
            tools=manifest.tools,
            notes=manifest.notes,
        )

    def with_robot(self, attachment: RobotAttachment) -> "AssemblyBlueprint":
        robots = _dedupe_by_key((*self.robots, attachment), key_fn=lambda item: item.attachment_id)
        return replace(self, robots=robots)

    def with_sensor(self, attachment: SensorAttachment) -> "AssemblyBlueprint":
        sensors = _dedupe_by_key(
            (*self.sensors, attachment),
            key_fn=lambda item: item.attachment_id,
        )
        return replace(self, sensors=sensors)

    def with_execution_target(self, target: ExecutionTarget) -> "AssemblyBlueprint":
        targets = _dedupe_by_key(
            (*self.execution_targets, target),
            key_fn=lambda item: item.id,
        )
        return replace(self, execution_targets=targets)

    def with_frame_transform(self, frame_transform: FrameTransform) -> "AssemblyBlueprint":
        transforms = _dedupe_by_key(
            (*self.frame_transforms, frame_transform),
            key_fn=lambda item: item.child_frame,
        )
        return replace(self, frame_transforms=transforms)

    def with_tool(self, tool: ToolAttachment) -> "AssemblyBlueprint":
        tools = _dedupe_by_key(
            (*self.tools, tool),
            key_fn=lambda item: item.attachment_id,
        )
        return replace(self, tools=tools)

    def remap_sensor(
        self,
        sensor_ref: str,
        *,
        to_mount: str,
        from_mount: str | None = None,
    ) -> "AssemblyBlueprint":
        updated = []
        changed = False
        for sensor in self.sensors:
            matched = sensor.attachment_id == sensor_ref
            if from_mount is not None:
                matched = sensor.sensor_id == sensor_ref and sensor.mount == from_mount
            if matched:
                updated.append(
                    SensorAttachment(
                        attachment_id=sensor.attachment_id,
                        sensor_id=sensor.sensor_id,
                        mount=to_mount,
                        mount_frame=sensor.mount_frame,
                        mount_transform=sensor.mount_transform,
                        config=sensor.config,
                        optional=sensor.optional,
                    )
                )
                changed = True
            else:
                updated.append(sensor)
        if not changed:
            sensor_key = sensor_ref if from_mount is None else f"{sensor_ref}@{from_mount}"
            raise KeyError(f"Sensor attachment '{sensor_key}' was not found in blueprint '{self.id}'.")
        return replace(self, sensors=tuple(updated))

    def use_default_execution_target(self, target_id: str) -> "AssemblyBlueprint":
        if target_id not in {target.id for target in self.execution_targets}:
            raise KeyError(
                f"Execution target '{target_id}' was not found in blueprint '{self.id}'."
            )
        return replace(self, default_execution_target_id=target_id)

    def extend_notes(self, *notes: str) -> "AssemblyBlueprint":
        return replace(self, notes=self.notes + tuple(notes))

    def build(self) -> AssemblyManifest:
        return AssemblyManifest(
            id=self.id,
            name=self.name,
            description=self.description,
            robots=self.robots,
            sensors=self.sensors,
            execution_targets=self.execution_targets,
            default_execution_target_id=self.default_execution_target_id,
            frame_transforms=self.frame_transforms,
            tools=self.tools,
            notes=self.notes,
        )


def compose_assemblies(*blueprints: AssemblyBlueprint) -> AssemblyBlueprint:
    """Compose multiple assembly blueprints with later override semantics."""

    if not blueprints:
        raise ValueError("compose_assemblies requires at least one blueprint.")

    base = blueprints[0]
    robots = _dedupe_by_key(
        tuple(robot for blueprint in blueprints for robot in blueprint.robots),
        key_fn=lambda item: item.attachment_id,
    )
    sensors = _dedupe_by_key(
        tuple(sensor for blueprint in blueprints for sensor in blueprint.sensors),
        key_fn=lambda item: item.attachment_id,
    )
    targets = _dedupe_by_key(
        tuple(target for blueprint in blueprints for target in blueprint.execution_targets),
        key_fn=lambda item: item.id,
    )
    frame_transforms = _dedupe_by_key(
        tuple(frame for blueprint in blueprints for frame in blueprint.frame_transforms),
        key_fn=lambda item: item.child_frame,
    )
    tools = _dedupe_by_key(
        tuple(tool for blueprint in blueprints for tool in blueprint.tools),
        key_fn=lambda item: item.attachment_id,
    )
    default_target = None
    for blueprint in blueprints:
        if blueprint.default_execution_target_id:
            default_target = blueprint.default_execution_target_id

    return AssemblyBlueprint(
        id=base.id,
        name=base.name,
        description=base.description,
        robots=robots,
        sensors=sensors,
        execution_targets=targets,
        default_execution_target_id=default_target,
        frame_transforms=frame_transforms,
        tools=tools,
        notes=tuple(note for blueprint in blueprints for note in blueprint.notes),
    )
