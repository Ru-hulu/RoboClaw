#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=./common.sh
source "${SCRIPT_DIR}/common.sh"

PROFILE="${DEFAULT_DOCKER_PROFILE}"
if [ "${1:-}" = "--profile" ]; then
  [ -n "${2:-}" ] || die "missing value for --profile"
  PROFILE="$(docker_profile "${2}")"
  shift 2
fi

INSTANCE="${1:-}"
shift || true
require_instance "${INSTANCE}"
ensure_image_exists "${INSTANCE}" "${PROFILE}"
ensure_instance_dir "${INSTANCE}" "${PROFILE}"
configure_proxy_env
prepare_auth_mounts "${INSTANCE}" "${PROFILE}"
prepare_instance_calibration "${INSTANCE}" "${PROFILE}"
AUTH_PATH="$(host_codex_auth_path || true)"
OAUTH_CLI_KIT_AUTH_DIR="$(host_oauth_cli_kit_auth_dir || true)"

if [ "$#" -eq 0 ]; then
  set -- status
fi

bootstrap_instance_if_needed "${INSTANCE}" "${PROFILE}"

DOCKER_ARGS=(
  --rm
  --network host
  --user "$(id -u):$(id -g)"
  -e HOME=/roboclaw-instance/home
  -e ROBOCLAW_CONFIG_PATH=/roboclaw-instance/config.json
  -e ROBOCLAW_WORKSPACE_PATH=/roboclaw-instance/workspace
  -e ROBOCLAW_ROS2_NAMESPACE_PREFIX="$(ros2_namespace_prefix "${INSTANCE}" "${PROFILE}")"
  -e ROBOCLAW_ROS2_CONTROL_PYTHON="/usr/bin/python3"
  -e ROBOCLAW_ROS2_CONTROL_PYTHONPATH="/app"
  -v "$(instance_dir "${INSTANCE}" "${PROFILE}"):/roboclaw-instance"
)
append_proxy_env_args DOCKER_ARGS

if [ -n "${AUTH_PATH}" ]; then
  DOCKER_ARGS+=(-v "${AUTH_PATH}:/roboclaw-instance/home/.codex/auth.json:ro")
fi

if [ -n "${OAUTH_CLI_KIT_AUTH_DIR}" ]; then
  DOCKER_ARGS+=(-v "${OAUTH_CLI_KIT_AUTH_DIR}:/roboclaw-instance/home/.local/share/oauth-cli-kit/auth")
fi

append_hardware_device_args DOCKER_ARGS

docker run "${DOCKER_ARGS[@]}" \
  "$(image_ref "${INSTANCE}" "${PROFILE}")" \
  "$@"
