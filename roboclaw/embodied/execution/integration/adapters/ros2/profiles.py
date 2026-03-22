"""ROS2 embodiment profile types and lookup helpers."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from roboclaw.embodied.execution.integration.transports.ros2.contracts import Ros2ServiceSpec


def _normalize_text(content: str) -> str:
    return " ".join(content.strip().lower().split())


def _default_control_pythonpath() -> str:
    paths: list[str] = []

    def add(path: str | None) -> None:
        if not path:
            return
        expanded = str(Path(path).expanduser())
        if expanded and expanded not in paths:
            paths.append(expanded)

    try:
        import roboclaw

        add(str(Path(inspect.getfile(roboclaw)).resolve().parent.parent))
    except Exception:
        pass

    add("/app")
    add("/usr/lib/python3/dist-packages")

    return ":".join(paths) or "/app"


@dataclass(frozen=True)
class PrimitiveAliasSpec:
    """One natural-language alias group for a normalized primitive."""

    primitive_name: str
    aliases: tuple[str, ...]
    default_args: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.primitive_name.strip():
            raise ValueError("Primitive alias primitive_name cannot be empty.")
        if not self.aliases:
            raise ValueError(f"Primitive alias '{self.primitive_name}' must declare at least one alias.")
        if any(not alias.strip() for alias in self.aliases):
            raise ValueError(f"Primitive alias '{self.primitive_name}' cannot contain empty aliases.")


@dataclass(frozen=True)
class PrimitiveAliasResolution:
    """Resolved primitive request from a user utterance."""

    primitive_name: str
    args: dict[str, Any] = field(default_factory=dict)
    matched_alias: str | None = None


@dataclass(frozen=True)
class PrimitiveServiceSpec:
    """One primitive routed through a ROS2 service instead of an action."""

    primitive_name: str
    service_name: str
    service_type: str = "std_srvs/srv/Trigger"

    def __post_init__(self) -> None:
        if not self.primitive_name.strip():
            raise ValueError("Primitive service primitive_name cannot be empty.")
        if not self.service_name.strip():
            raise ValueError(f"Primitive service '{self.primitive_name}' must declare a service_name.")
        if not self.service_type.strip():
            raise ValueError(f"Primitive service '{self.primitive_name}' must declare a service_type.")


@dataclass(frozen=True)
class Ros2EmbodimentProfile:
    """Framework-owned ROS2 execution profile for one known robot family."""

    id: str
    robot_id: str
    primitive_aliases: tuple[PrimitiveAliasSpec, ...] = field(default_factory=tuple)
    primitive_services: tuple[PrimitiveServiceSpec, ...] = field(default_factory=tuple)
    required_services: tuple[str, ...] = ("connect", "stop", "reset", "recover", "debug_snapshot")
    required_actions: tuple[str, ...] = ()
    optional_topics: tuple[str, ...] = ("state", "health", "events", "joint_states")
    default_reset_mode: str = "home"
    auto_probe_serial: bool = False
    control_surface_server_module: str | None = None
    calibration_robot_name: str | None = None
    control_default_calibration_id: str | None = None
    calibration_driver_id: str | None = None
    probe_provider_id: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def requires_calibration(self) -> bool:
        return bool(self.calibration_robot_name and self.control_default_calibration_id)

    def canonical_calibration_path(self) -> Path | None:
        if not self.requires_calibration:
            return None
        from roboclaw.config.paths import get_robot_calibration_file

        return get_robot_calibration_file(self.calibration_robot_name or self.robot_id, self.control_default_calibration_id or "")

    def ensure_canonical_calibration(self) -> Path | None:
        if not self.requires_calibration:
            return None
        from roboclaw.config.paths import ensure_robot_calibration_file

        return ensure_robot_calibration_file(self.calibration_robot_name or self.robot_id, self.control_default_calibration_id or "")

    def resolve_primitive_alias(self, content: str) -> PrimitiveAliasResolution | None:
        normalized = _normalize_text(content)
        for alias_spec in self.primitive_aliases:
            for alias in alias_spec.aliases:
                normalized_alias = _normalize_text(alias)
                if normalized == normalized_alias or normalized_alias in normalized:
                    return PrimitiveAliasResolution(
                        primitive_name=alias_spec.primitive_name,
                        args=dict(alias_spec.default_args),
                        matched_alias=alias,
                    )
        return None

    def primitive_service_for(
        self,
        primitive_name: str,
        args: dict[str, Any] | None = None,
    ) -> PrimitiveServiceSpec | None:
        del args
        for item in self.primitive_services:
            if item.primitive_name == primitive_name:
                return item
        return None

    def extra_service_specs(self, namespace: str) -> tuple[Ros2ServiceSpec, ...]:
        return tuple(
            Ros2ServiceSpec(
                name=item.service_name,
                service_type=item.service_type,
                path=f"{namespace}/{item.service_name}",
                description=f"Control-surface primitive service for `{item.primitive_name}`.",
            )
            for item in self.primitive_services
        )

    def control_launch_command(
        self,
        *,
        namespace: str,
        robot_id: str,
        device_by_id: str,
    ) -> str | None:
        if not self.control_surface_server_module or not device_by_id.strip():
            return None
        ros_setup = (
            'if [ "${ROBOCLAW_ROS2_DISTRO:-none}" != "none" ] '
            '&& [ -f "/opt/ros/${ROBOCLAW_ROS2_DISTRO}/setup.bash" ]; then '
            'set +u; source "/opt/ros/${ROBOCLAW_ROS2_DISTRO}/setup.bash"; set -u; '
            "fi &&"
        )
        command = [
            ros_setup,
            (
                'PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}'
                f'${{ROBOCLAW_ROS2_CONTROL_PYTHONPATH:-{_default_control_pythonpath()}}}"'
            ),
            f"${{ROBOCLAW_ROS2_CONTROL_PYTHON:-/usr/bin/python3}} -m {self.control_surface_server_module}",
            f"--namespace {shlex.quote(namespace)}",
            f"--profile-id {shlex.quote(self.id)}",
            f"--robot-id {shlex.quote(robot_id)}",
            f"--device-by-id {shlex.quote(device_by_id)}",
        ]
        if self.control_default_calibration_id:
            command.append(f"--calibration-id {shlex.quote(self.control_default_calibration_id)}")
        return " ".join(command)

def list_ros2_profiles() -> tuple[Ros2EmbodimentProfile, ...]:
    """List all built-in ROS2 profiles."""

    from roboclaw.embodied.builtins import list_ros2_profiles as _list_ros2_profiles

    return tuple(_list_ros2_profiles())


def get_ros2_profile(profile_or_robot_id: str | None) -> Ros2EmbodimentProfile | None:
    """Resolve one framework ROS2 profile by profile id or robot id."""

    if profile_or_robot_id is None:
        return None
    from roboclaw.embodied.builtins import get_ros2_profile_from_builtins

    return get_ros2_profile_from_builtins(profile_or_robot_id)


__all__ = [
    "PrimitiveAliasResolution",
    "PrimitiveAliasSpec",
    "PrimitiveServiceSpec",
    "Ros2EmbodimentProfile",
    "get_ros2_profile",
    "list_ros2_profiles",
]
