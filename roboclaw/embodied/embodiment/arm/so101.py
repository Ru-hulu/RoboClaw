"""SO101 LeRobot 0.5.0 command builder."""

from __future__ import annotations

import json
from pathlib import Path

from roboclaw.embodied.ops.helpers import _WRAPPER_CMD, _arm_id


class SO101Controller:
    """Builds LeRobot CLI commands for SO101 robot arm.

    All methods take explicit params — the caller (tool.py) resolves
    setup.json into concrete values before calling these.
    """

    def doctor(self) -> list[str]:
        """Check lerobot, list supported robots, motors, and connected devices."""
        script = (
            "import lerobot, glob, os; "
            "print(f'lerobot_version: {lerobot.__version__}'); "
            "print(f'supported_robots: {lerobot.available_robots}'); "
            "print(f'supported_motors: {lerobot.available_motors}'); "
            "print(f'supported_cameras: {lerobot.available_cameras}'); "
            "by_id = sorted(glob.glob('/dev/serial/by-id/*')); "
            "pairs = [(p, os.path.realpath(p)) for p in by_id]; "
            "print(f'connected_ports_by_id: {pairs}'); "
            "from serial.tools import list_ports; "
            "ports = sorted(p.device for p in list_ports.comports() if getattr(p, 'device', '')); "
            "print(f'connected_ports: {ports}')"
        )
        return ["python3", "-c", script]

    def calibrate(
        self, arm_type: str, arm_port: str, calibration_dir: str, arm_id: str,
    ) -> list[str]:
        """Build calibration command for one arm.

        arm_type: "so101_follower" or "so101_leader"
        For follower uses --robot.* prefix, for leader uses --teleop.* prefix.
        """
        prefix = self._arm_prefix(arm_type)
        return [
            *_WRAPPER_CMD, "calibrate",
            *self._arm_args(prefix, arm_type, arm_port, calibration_dir, arm_id),
        ]

    def robot_argv(self, follower: dict, leader: dict) -> list[str]:
        """Return robot+teleop CLI args for single arm pair."""
        return [
            *self._arm_args("robot", follower["type"], follower["port"],
                            follower["calibration_dir"], _arm_id(follower)),
            *self._arm_args("teleop", leader["type"], leader["port"],
                            leader["calibration_dir"], _arm_id(leader)),
        ]

    def bimanual_robot_argv(
        self, robot_id: str, robot_cal_dir: str,
        left_robot: dict, right_robot: dict,
        teleop_id: str, teleop_cal_dir: str,
        left_teleop: dict, right_teleop: dict,
        cameras: dict[str, dict] | None = None,
    ) -> list[str]:
        """Return bimanual robot+teleop CLI args."""
        return [
            "--robot.type=bi_so_follower",
            f"--robot.id={robot_id}",
            f"--robot.calibration_dir={Path(robot_cal_dir).expanduser()}",
            *self._bimanual_arm_args("robot", left_robot, right_robot, cameras),
            "--teleop.type=bi_so_leader",
            f"--teleop.id={teleop_id}",
            f"--teleop.calibration_dir={Path(teleop_cal_dir).expanduser()}",
            *self._bimanual_arm_args("teleop", left_teleop, right_teleop),
        ]

    def follower_only_argv(self, follower: dict) -> list[str]:
        """Return robot-only CLI args (no teleop) for policy inference."""
        return self._arm_args("robot", follower["type"], follower["port"],
                              follower["calibration_dir"], _arm_id(follower))

    def bimanual_follower_only_argv(
        self, robot_id: str, robot_cal_dir: str,
        left_robot: dict, right_robot: dict,
        cameras: dict[str, dict] | None = None,
    ) -> list[str]:
        """Return bimanual robot-only CLI args for policy inference."""
        return [
            "--robot.type=bi_so_follower",
            f"--robot.id={robot_id}",
            f"--robot.calibration_dir={Path(robot_cal_dir).expanduser()}",
            *self._bimanual_arm_args("robot", left_robot, right_robot, cameras),
        ]

    def _arm_prefix(self, arm_type: str) -> str:
        if "leader" in arm_type:
            return "teleop"
        if "follower" in arm_type:
            return "robot"
        raise ValueError(f"Unsupported arm type: {arm_type}")

    def _arm_args(
        self, prefix: str, arm_type: str, port: str, cal_dir: str, arm_id: str,
    ) -> list[str]:
        return [
            f"--{prefix}.type={arm_type}",
            f"--{prefix}.id={arm_id}",
            f"--{prefix}.port={port}",
            f"--{prefix}.calibration_dir={Path(cal_dir).expanduser()}",
        ]

    def _bimanual_arm_args(
        self,
        prefix: str,
        left: dict,
        right: dict,
        cameras: dict[str, dict] | None = None,
    ) -> list[str]:
        """Build --{prefix}.left_arm_config.* and --{prefix}.right_arm_config.* args."""
        args: list[str] = []
        for side, arm in [("left", left), ("right", right)]:
            args.append(f"--{prefix}.{side}_arm_config.port={arm['port']}")
        if cameras:
            args.append(f"--{prefix}.left_arm_config.cameras={json.dumps(cameras)}")
        return args
