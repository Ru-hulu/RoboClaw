"""Assembly exports."""

from roboclaw.embodied.definition.systems.assemblies.blueprint import AssemblyBlueprint, compose_assemblies
from roboclaw.embodied.definition.systems.assemblies.model import (
    AssemblyManifest,
    FrameTransform,
    RobotAttachment,
    SensorAttachment,
    ToolAttachment,
    Transform3D,
)
from roboclaw.embodied.definition.systems.assemblies.registry import AssemblyRegistry

__all__ = [
    "AssemblyBlueprint",
    "AssemblyManifest",
    "AssemblyRegistry",
    "FrameTransform",
    "RobotAttachment",
    "SensorAttachment",
    "ToolAttachment",
    "Transform3D",
    "compose_assemblies",
]
