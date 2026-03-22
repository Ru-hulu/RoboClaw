#!/usr/bin/env bash
set -euo pipefail

if [ "${ROBOCLAW_ROS2_DISTRO:-none}" != "none" ] && [ -f "/opt/ros/${ROBOCLAW_ROS2_DISTRO}/setup.sh" ]; then
  # ROS setup scripts assume several tracing vars may be unset.
  set +u
  # shellcheck disable=SC1090
  source "/opt/ros/${ROBOCLAW_ROS2_DISTRO}/setup.sh"
  set -u
fi

# Run the CLI via python3, which is the same Python used for all
# components after the unified-environment simplification.
exec python3 /usr/local/bin/roboclaw-real "$@"
