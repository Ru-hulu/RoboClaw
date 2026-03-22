"""System-layer exports for embodied definitions."""

from roboclaw.embodied.definition.systems.assemblies import (
    AssemblyBlueprint,
    AssemblyManifest,
    AssemblyRegistry,
    FrameTransform,
    RobotAttachment,
    SensorAttachment,
    ToolAttachment,
    Transform3D,
    compose_assemblies,
)
from roboclaw.embodied.definition.systems.deployments import (
    DeploymentProfile,
    DeploymentRegistry,
)
from roboclaw.embodied.definition.systems.simulators import (
    SimulatorRegistry,
    SimulatorScenario,
    SimulatorWorld,
)

__all__ = [
    "AssemblyBlueprint",
    "AssemblyManifest",
    "AssemblyRegistry",
    "DeploymentProfile",
    "DeploymentRegistry",
    "FrameTransform",
    "RobotAttachment",
    "SensorAttachment",
    "SimulatorRegistry",
    "SimulatorScenario",
    "SimulatorWorld",
    "ToolAttachment",
    "Transform3D",
    "compose_assemblies",
]
