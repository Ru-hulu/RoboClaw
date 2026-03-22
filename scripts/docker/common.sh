#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ROBOCLAW_DOCKER_HOME="${ROBOCLAW_DOCKER_HOME:-${HOME}/.roboclaw-docker}"
DEFAULT_DOCKER_PROFILE="${ROBOCLAW_DOCKER_PROFILE:-ubuntu2404-ros2}"
DEFAULT_MATRIX_PROFILES="${ROBOCLAW_DOCKER_MATRIX_PROFILES:-ubuntu2204-ros2,ubuntu2404-ros2}"
ROBOCLAW_CONTAINER_HOST_DEV_ROOT="${ROBOCLAW_CONTAINER_HOST_DEV_ROOT:-/roboclaw-host-dev}"

die() {
  echo "error: $*" >&2
  exit 1
}

host_python_cmd() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
    return 0
  fi
  die "python3 or python is required on the host"
}

require_instance() {
  local instance="${1:-}"
  [ -n "${instance}" ] || die "instance name is required"
  [[ "${instance}" =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid instance name: ${instance}"
}

docker_profile() {
  local profile="${1:-${DEFAULT_DOCKER_PROFILE}}"
  case "${profile}" in
    ubuntu2204-ros2|ubuntu2404-ros2)
      printf '%s\n' "${profile}"
      ;;
    *)
      die "unknown docker profile: ${profile}"
      ;;
  esac
}

docker_profile_base_image() {
  local profile
  profile="$(docker_profile "${1:-}")"
  case "${profile}" in
    ubuntu2204-ros2)
      printf '%s\n' "ubuntu:22.04"
      ;;
    ubuntu2404-ros2)
      printf '%s\n' "ubuntu:24.04"
      ;;
  esac
}

docker_profile_ros_distro() {
  local profile
  profile="$(docker_profile "${1:-}")"
  case "${profile}" in
    ubuntu2204-ros2)
      printf '%s\n' "humble"
      ;;
    ubuntu2404-ros2)
      printf '%s\n' "jazzy"
      ;;
    *)
      printf '%s\n' "none"
      ;;
  esac
}

docker_profile_installs_ros2() {
  docker_profile "${1:-}" >/dev/null
  printf '%s\n' "1"
}

docker_profile_control_bridge_python() {
  docker_profile "${1:-}" >/dev/null
  printf '%s\n' "/usr/bin/python3"
}

list_docker_profiles() {
  printf '%s\n' ubuntu2204-ros2 ubuntu2404-ros2
}

parse_profile_flag() {
  local profile="${DEFAULT_DOCKER_PROFILE}"
  if [ "${1:-}" = "--profile" ]; then
    [ -n "${2:-}" ] || die "missing value for --profile"
    profile="$(docker_profile "${2}")"
    shift 2
  fi
  printf '%s\n' "${profile}"
}

join_profiles_csv() {
  local first=1
  local profile
  for profile in "$@"; do
    if [ "${first}" -eq 1 ]; then
      printf '%s' "${profile}"
      first=0
    else
      printf ',%s' "${profile}"
    fi
  done
  printf '\n'
}

split_profiles_csv() {
  local csv="${1:-}"
  [ -n "${csv}" ] || return 0
  local old_ifs="${IFS}"
  IFS=',' read -r -a _profiles <<< "${csv}"
  IFS="${old_ifs}"
  local profile
  for profile in "${_profiles[@]}"; do
    docker_profile "${profile}"
  done
}

instance_key() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  printf '%s--%s\n' "${instance}" "${profile}"
}

ros2_namespace_prefix() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  local raw
  raw="$(instance_key "${instance}" "${profile}")"
  raw="${raw//[^A-Za-z0-9_]/_}"
  printf '/roboclaw/%s\n' "${raw}"
}

instance_dir() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  printf '%s/instances/%s\n' "${ROBOCLAW_DOCKER_HOME}" "$(instance_key "${instance}" "${profile}")"
}

instance_bootstrap_stamp_path() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  printf '%s/.bootstrap-%s\n' "$(instance_dir "${instance}" "${profile}")" "$(current_commit_short)"
}

image_ref() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  printf 'roboclaw:%s-%s-%s\n' "${instance}" "${profile}" "$(current_commit_short)"
}

dev_image_ref() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  printf 'roboclaw:dev-%s-%s\n' "${instance}" "${profile}"
}

current_commit_short() {
  git -C "${REPO_ROOT}" rev-parse --short HEAD
}

require_clean_git() {
  if [ -n "$(git -C "${REPO_ROOT}" status --porcelain)" ]; then
    die "git worktree is dirty; commit or stash changes before building the Docker image"
  fi
}

compose_project() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  printf 'roboclaw-%s-%s\n' "${instance}" "${profile}"
}

collect_proxy_build_args() {
  local -n build_args_ref="$1"
  local key value
  for key in HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; do
    value="${!key:-}"
    if [ -n "${value}" ]; then
      build_args_ref+=(--build-arg "${key}=${value}")
    fi
  done
}

append_proxy_env_args() {
  local -n docker_args_ref="$1"
  local key
  for key in HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; do
    docker_args_ref+=(-e "${key}=${!key:-}")
  done
}

dev_container_name() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  printf 'roboclaw-dev-%s-%s\n' "${instance}" "${profile}"
}

find_proxy_port() {
  local proxy_spec
  proxy_spec="$(find_proxy_endpoint || true)"
  [ -n "${proxy_spec}" ] || return 1
  printf '%s\n' "${proxy_spec##*:}"
}

infer_proxy_scheme_for_port() {
  local port="${1:-}"
  case "${port}" in
    7891|7898|7899)
      printf '%s\n' "socks5"
      ;;
    *)
      printf '%s\n' "http"
      ;;
  esac
}

_known_proxy_process_regex() {
  printf '%s\n' 'verge-mihomo|clash|mihomo|sing-box|xray|v2ray|dae|hysteria'
}

_find_proxy_endpoint_from_ss_output() {
  local ss_output="${1:-}"
  [ -n "${ss_output}" ] || return 1

  local process_pattern port line
  process_pattern="$(_known_proxy_process_regex)"

  if printf '%s\n' "${ss_output}" | awk '/verge-mihomo/ && $4 ~ /127\.0\.0\.1:7897$/ { print "http:7897"; exit }' | grep -q .; then
    printf '%s\n' "http:7897"
    return 0
  fi

  for port in 7897 7890 7891 20170 7895 7898 7899; do
    if printf '%s\n' "${ss_output}" | awk -v port="${port}" '$4 ~ ("127\\.0\\.0\\.1:" port "$") { found=1 } END { exit(found ? 0 : 1) }'; then
      printf '%s:%s\n' "$(infer_proxy_scheme_for_port "${port}")" "${port}"
      return 0
    fi
  done

  line="$(printf '%s\n' "${ss_output}" | grep -E "127\\.0\\.0\\.1:.*(${process_pattern})" | head -n 1 || true)"
  if [ -n "${line}" ]; then
    port="$(printf '%s\n' "${line}" | sed -E 's/.*127\.0\.0\.1:([0-9]+).*/\1/')"
    if [ -n "${port}" ]; then
      printf '%s:%s\n' "$(infer_proxy_scheme_for_port "${port}")" "${port}"
      return 0
    fi
  fi

  return 1
}

_find_proxy_endpoint_from_lsof_output() {
  local lsof_output="${1:-}"
  [ -n "${lsof_output}" ] || return 1

  local process_pattern port line
  process_pattern="$(_known_proxy_process_regex)"

  if printf '%s\n' "${lsof_output}" | grep -E '^[^[:space:]]*verge-mihomo[^[:space:]]*[[:space:]].*127\.0\.0\.1:7897([[:space:]]|\(|$)' | head -n 1 | grep -q .; then
    printf '%s\n' "http:7897"
    return 0
  fi

  for port in 7897 7890 7891 20170 7895 7898 7899; do
    if printf '%s\n' "${lsof_output}" | grep -E "127\\.0\\.0\\.1:${port}([[:space:]]|\\(|$)" >/dev/null; then
      printf '%s:%s\n' "$(infer_proxy_scheme_for_port "${port}")" "${port}"
      return 0
    fi
  done

  line="$(printf '%s\n' "${lsof_output}" | grep -E "^[^[:space:]]*(${process_pattern})[^[:space:]]*[[:space:]].*127\\.0\\.0\\.1:" | head -n 1 || true)"
  if [ -n "${line}" ]; then
    port="$(printf '%s\n' "${line}" | sed -E 's/.*127\.0\.0\.1:([0-9]+).*/\1/')"
    if [ -n "${port}" ]; then
      printf '%s:%s\n' "$(infer_proxy_scheme_for_port "${port}")" "${port}"
      return 0
    fi
  fi

  return 1
}

_find_proxy_endpoint_from_netstat_output() {
  local netstat_output="${1:-}"
  [ -n "${netstat_output}" ] || return 1

  local port
  for port in 7897 7890 7891 20170 7895 7898 7899; do
    if printf '%s\n' "${netstat_output}" | grep -Eq "127\\.0\\.0\\.1[.:]${port}[[:space:]].*LISTEN"; then
      printf '%s:%s\n' "$(infer_proxy_scheme_for_port "${port}")" "${port}"
      return 0
    fi
  done

  return 1
}

find_proxy_endpoint() {
  local ss_output lsof_output netstat_output

  if command -v ss >/dev/null 2>&1; then
    ss_output="$(ss -ltnpH 2>/dev/null || true)"
    if _find_proxy_endpoint_from_ss_output "${ss_output}"; then
      return 0
    fi
  fi

  if command -v lsof >/dev/null 2>&1; then
    lsof_output="$(lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null || true)"
    if _find_proxy_endpoint_from_lsof_output "${lsof_output}"; then
      return 0
    fi
  fi

  if command -v netstat >/dev/null 2>&1; then
    netstat_output="$(netstat -an 2>/dev/null || true)"
    if _find_proxy_endpoint_from_netstat_output "${netstat_output}"; then
      return 0
    fi
  fi

  return 1
}

configure_proxy_env() {
  local proxy_spec="${1:-}"
  local proxy_scheme proxy_port
  if [ -z "${proxy_spec}" ]; then
    proxy_spec="$(find_proxy_endpoint || true)"
  fi
  if [ -z "${proxy_spec}" ]; then
    unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
    return 0
  fi

  if [[ "${proxy_spec}" == *:* ]]; then
    proxy_scheme="${proxy_spec%%:*}"
    proxy_port="${proxy_spec##*:}"
  else
    proxy_port="${proxy_spec}"
    proxy_scheme="$(infer_proxy_scheme_for_port "${proxy_port}")"
  fi

  export HTTP_PROXY="http://127.0.0.1:${proxy_port}"
  export HTTPS_PROXY="http://127.0.0.1:${proxy_port}"
  if [ "${proxy_scheme}" = "socks5" ]; then
    export ALL_PROXY="socks5://127.0.0.1:${proxy_port}"
  else
    unset ALL_PROXY
  fi
  export http_proxy="${HTTP_PROXY}"
  export https_proxy="${HTTPS_PROXY}"
  if [ -n "${ALL_PROXY:-}" ]; then
    export all_proxy="${ALL_PROXY}"
  else
    unset all_proxy
  fi
}

ensure_image_exists() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  docker image inspect "$(image_ref "${instance}" "${profile}")" >/dev/null 2>&1 || \
    die "image $(image_ref "${instance}" "${profile}") not found; run scripts/docker/build-image.sh --profile ${profile} ${instance}"
}

ensure_instance_dir() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  mkdir -p \
    "$(instance_dir "${instance}" "${profile}")/workspace" \
    "$(instance_dir "${instance}" "${profile}")/calibration" \
    "$(instance_dir "${instance}" "${profile}")/home" \
    "$(instance_dir "${instance}" "${profile}")/home/.codex" \
    "$(instance_dir "${instance}" "${profile}")/home/.local/share/oauth-cli-kit/auth"
}

host_codex_auth_path() {
  local path="${HOME}/.codex/auth.json"
  if [ -f "${path}" ]; then
    printf '%s\n' "${path}"
  fi
}

host_oauth_cli_kit_auth_dir() {
  local path="${HOME}/.local/share/oauth-cli-kit/auth"
  if [ -d "${path}" ]; then
    printf '%s\n' "${path}"
  fi
}

instance_calibration_dir() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  printf '%s/calibration\n' "$(instance_dir "${instance}" "${profile}")"
}

prepare_instance_calibration() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  mkdir -p "$(instance_calibration_dir "${instance}" "${profile}")"
}

instance_oauth_cli_kit_auth_dir() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  printf '%s/home/.local/share/oauth-cli-kit/auth\n' "$(instance_dir "${instance}" "${profile}")"
}

prepare_auth_mounts() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  local codex_auth_path oauth_dir instance_oauth_dir
  codex_auth_path="$(host_codex_auth_path || true)"
  oauth_dir="$(host_oauth_cli_kit_auth_dir || true)"
  instance_oauth_dir="$(instance_oauth_cli_kit_auth_dir "${instance}" "${profile}")"

  mkdir -p "${instance_oauth_dir}"

  if [ -n "${oauth_dir}" ]; then
    rm -f "${instance_oauth_dir}/codex.json"
  elif [ -n "${codex_auth_path}" ]; then
    rm -rf "${instance_oauth_dir}"
    mkdir -p "${instance_oauth_dir}"
  fi
}

instance_bootstrap_needed() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  local instance_root stamp_path
  instance_root="$(instance_dir "${instance}" "${profile}")"
  stamp_path="$(instance_bootstrap_stamp_path "${instance}" "${profile}")"

  if [ "${ROBOCLAW_FORCE_BOOTSTRAP:-0}" = "1" ]; then
    return 0
  fi
  if [ ! -f "${instance_root}/config.json" ]; then
    return 0
  fi
  if [ ! -d "${instance_root}/workspace" ]; then
    return 0
  fi
  if [ ! -f "${instance_root}/workspace/AGENTS.md" ]; then
    return 0
  fi
  [ ! -f "${stamp_path}" ]
}

mark_instance_bootstrapped() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  local instance_root stamp_path
  instance_root="$(instance_dir "${instance}" "${profile}")"
  stamp_path="$(instance_bootstrap_stamp_path "${instance}" "${profile}")"
  find "${instance_root}" -maxdepth 1 -type f -name '.bootstrap-*' -delete
  : > "${stamp_path}"
}

bootstrap_instance_if_needed() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  if instance_bootstrap_needed "${instance}" "${profile}"; then
    "${SCRIPT_DIR}/bootstrap-instance.sh" --profile "${profile}" "${instance}"
  fi
}

host_serial_devices() {
  local device
  for device in /dev/ttyACM* /dev/ttyUSB*; do
    if [ -e "${device}" ]; then
      printf '%s\n' "${device}"
    fi
  done
}

host_serial_symlink_dir() {
  if [ -d /dev/serial/by-id ]; then
    printf '%s\n' "/dev/serial/by-id"
  fi
}

append_hardware_device_args() {
  local -n docker_args_ref="$1"
  local seen_group_ids=" "
  local device group_id serial_symlink_dir group_name host_dev_root

  while IFS= read -r device; do
    [ -n "${device}" ] || continue
    docker_args_ref+=(--device "${device}:${device}")
    group_id="$(stat -c '%g' "${device}")"
    if [[ "${seen_group_ids}" != *" ${group_id} "* ]]; then
      docker_args_ref+=(--group-add "${group_id}")
      seen_group_ids+="$(printf '%s ' "${group_id}")"
    fi
  done < <(host_serial_devices || true)

  for group_name in dialout uucp; do
    group_id="$(getent group "${group_name}" 2>/dev/null | cut -d: -f3 || true)"
    if [ -n "${group_id}" ] && [[ "${seen_group_ids}" != *" ${group_id} "* ]]; then
      docker_args_ref+=(--group-add "${group_id}")
      seen_group_ids+="$(printf '%s ' "${group_id}")"
    fi
  done

  docker_args_ref+=(--device-cgroup-rule "c 166:* rmw")
  docker_args_ref+=(--device-cgroup-rule "c 188:* rmw")

  serial_symlink_dir="$(host_serial_symlink_dir || true)"
  if [ -n "${serial_symlink_dir}" ]; then
    docker_args_ref+=(-v "${serial_symlink_dir}:${serial_symlink_dir}:ro")
  fi

  host_dev_root="${ROBOCLAW_CONTAINER_HOST_DEV_ROOT}"
  docker_args_ref+=(-v "/dev:${host_dev_root}")
}

compose_cmd() {
  local instance="${1}"
  local profile
  profile="$(docker_profile "${2:-}")"
  shift
  shift
  if docker compose version >/dev/null 2>&1; then
    ROBOCLAW_IMAGE="$(image_ref "${instance}" "${profile}")" \
    ROBOCLAW_INSTANCE_DIR="$(instance_dir "${instance}" "${profile}")" \
    ROBOCLAW_UID="$(id -u)" \
    ROBOCLAW_GID="$(id -g)" \
    docker compose -f "${REPO_ROOT}/docker-compose.yml" -p "$(compose_project "${instance}" "${profile}")" "$@"
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    ROBOCLAW_IMAGE="$(image_ref "${instance}" "${profile}")" \
    ROBOCLAW_INSTANCE_DIR="$(instance_dir "${instance}" "${profile}")" \
    ROBOCLAW_UID="$(id -u)" \
    ROBOCLAW_GID="$(id -g)" \
    docker-compose -f "${REPO_ROOT}/docker-compose.yml" -p "$(compose_project "${instance}" "${profile}")" "$@"
    return
  fi

  die "neither 'docker compose' nor 'docker-compose' is available"
}
