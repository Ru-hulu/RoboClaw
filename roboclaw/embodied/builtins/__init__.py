"""Framework-owned built-in embodiment declarations."""

from roboclaw.embodied.builtins.model import BuiltinEmbodiment
from roboclaw.embodied.builtins.registry import (
    get_builtin_calibration_driver,
    get_builtin_embodiment,
    get_builtin_embodiment_for_robot,
    get_builtin_probe_provider,
    get_control_surface_runtime_factory,
    get_ros2_profile_from_builtins,
    list_builtin_embodiments,
    list_builtin_robot_aliases,
    list_ros2_profiles,
    list_supported_robot_labels,
    register_builtin_embodiment,
)

__all__ = [
    "BuiltinEmbodiment",
    "get_builtin_calibration_driver",
    "get_builtin_embodiment",
    "get_builtin_embodiment_for_robot",
    "get_builtin_probe_provider",
    "get_control_surface_runtime_factory",
    "get_ros2_profile_from_builtins",
    "list_builtin_embodiments",
    "list_builtin_robot_aliases",
    "list_ros2_profiles",
    "list_supported_robot_labels",
    "register_builtin_embodiment",
]
