"""Helpers for the guided ROS2 prerequisite flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from roboclaw.embodied.localization import localize_text

ROS2_START_PHRASES = (
    "start ros2 install",
    "install ros2",
    "run ros2 install",
    "continue ros2 install",
    "begin ros2 install",
    "help me install ros2",
    "start ros install",
    "安装 ros2",
    "开始安装 ros2",
    "帮我安装 ros2",
    "开始装 ros2",
    "装 ros2",
)

ROS2_STEP_ADVANCE_PHRASES = (
    "done",
    "next",
    "step done",
    "go on",
    "finished",
    "completed",
    "okay next",
    "好了",
    "完成了",
    "做完了",
    "下一步",
    "继续",
    "这一步做完了",
    "这步做完了",
)


@dataclass(frozen=True)
class ROS2InstallRecipe:
    distro: str
    profile: str
    package_name: str
    shell_name: str
    setup_file: str
    shell_rc: str
    steps: tuple[dict[str, Any], ...]


def extract_ros2_state(content: str) -> bool | None:
    lower = content.lower()
    if "ros2" not in lower and "ros 2" not in lower and "ros" not in lower:
        return None
    if any(token in lower for token in (
        "missing",
        "not installed",
        "unavailable",
        "not available",
        "broken",
        "没装",
        "没有安装",
        "不可用",
        "还不能用",
    )):
        return False
    if any(token in lower for token in (
        "ros2 installed",
        "installed ros2",
        "ros2 available",
        "available ros2",
        "ros2 已安装",
        "ros2 装好了",
        "ros2 可以用了",
        "ros2 已经好了",
    )):
        return True
    return None


def extract_ros2_profile(content: str) -> str | None:
    lower = content.lower()
    if any(token in lower for token in ("desktop", "rviz", "gui", "桌面", "图形界面")):
        return "desktop"
    if any(token in lower for token in ("headless", "ros-base", "base only", "无头", "基础版")):
        return "ros-base"
    return None


def is_ros2_install_request(content: str) -> bool:
    normalized = _normalize(content)
    return any(phrase in normalized for phrase in ROS2_START_PHRASES)


def is_ros2_step_advance(content: str) -> bool:
    normalized = _normalize(content)
    return any(
        normalized == phrase or normalized.startswith(f"{phrase} ")
        for phrase in ROS2_STEP_ADVANCE_PHRASES
    )


def parse_key_value_output(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def select_ros2_recipe(facts: dict[str, Any]) -> ROS2InstallRecipe | None:
    if facts.get("host_os_id") != "ubuntu":
        return None
    version = str(facts.get("host_os_version", ""))
    codename = str(facts.get("host_os_codename", ""))
    requested_profile = str(facts.get("ros2_install_profile", "ros-base"))
    profile = "desktop" if requested_profile == "desktop" else "ros-base"
    shell_name = "zsh" if facts.get("host_shell") == "zsh" else "bash"

    distro: str | None = None
    if version.startswith("24.04") or codename == "noble":
        distro = "jazzy"
    elif version.startswith("22.04") or codename == "jammy":
        distro = "humble"
    if distro is None:
        return None

    package_name = f"ros-{distro}-{'desktop' if profile == 'desktop' else 'ros-base'}"
    return ROS2InstallRecipe(
        distro=distro,
        profile=profile,
        package_name=package_name,
        shell_name=shell_name,
        setup_file=f"setup.{shell_name}",
        shell_rc="$HOME/.zshrc" if shell_name == "zsh" else "$HOME/.bashrc",
        steps=build_ros2_install_steps(distro, profile, shell_name),
    )


def build_ros2_install_steps(distro: str, profile: str, shell_name: str) -> tuple[dict[str, Any], ...]:
    package_name = f"ros-{distro}-{'desktop' if profile == 'desktop' else 'ros-base'}"
    shell_rc = "~/.zshrc" if shell_name == "zsh" else "~/.bashrc"
    shell_setup = f"/opt/ros/{distro}/setup.{shell_name}"
    return (
        {
            "title": "Prepare locale and ROS apt source",
            "commands": (
                "sudo apt update",
                "sudo apt install -y locales software-properties-common curl",
                "sudo locale-gen en_US en_US.UTF-8",
                "sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8",
                "export LANG=en_US.UTF-8",
                "sudo add-apt-repository universe",
                "sudo apt update",
                "export ROS_APT_SOURCE_VERSION=$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest | grep -F \"tag_name\" | awk -F\\\" '{print $4}')",
                "curl -L -o /tmp/ros2-apt-source.deb \"https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.$(. /etc/os-release && echo ${UBUNTU_CODENAME:-${VERSION_CODENAME}})_all.deb\"",
                "sudo dpkg -i /tmp/ros2-apt-source.deb",
            ),
        },
        {
            "title": "Install ROS2 packages",
            "commands": (
                "sudo apt update",
                "sudo apt upgrade -y",
                f"sudo apt install -y {package_name} python3-rosdep ros-dev-tools",
            ),
        },
        {
            "title": "Initialize rosdep",
            "commands": (
                "sudo rosdep init || true",
                "rosdep update",
            ),
        },
        {
            "title": "Configure shell and validate",
            "commands": _shell_init_commands(distro, shell_name, shell_rc),
        },
    )


def ros2_install_summary(recipe: ROS2InstallRecipe | None, facts: dict[str, Any]) -> str:
    if recipe is None:
        return f"unsupported host `{facts.get('host_pretty_name', 'unknown')}`"
    host = facts.get("host_pretty_name", "unknown host")
    wsl_suffix = " via WSL2" if facts.get("host_is_wsl") else ""
    profile = "desktop" if recipe.profile == "desktop" else "ros-base"
    return f"`{host}`{wsl_suffix} -> ROS 2 {recipe.distro} ({profile})"


def render_ros2_install_step(
    facts: dict[str, Any],
    recipe: ROS2InstallRecipe | None = None,
    *,
    language: str | None = None,
) -> str:
    recipe = recipe or select_ros2_recipe(facts)
    if recipe is None:
        return localize_text(
            language,
            en=(
                "I cannot guide a first-run ROS2 install on this host automatically."
                "\nThe current guided path only supports Ubuntu 22.04 and Ubuntu 24.04, including Ubuntu inside WSL2."
            ),
            zh=(
                "我目前还不能在这台机器上自动引导首次 ROS2 安装。"
                "\n当前的引导流程只支持 Ubuntu 22.04 和 Ubuntu 24.04，包括 WSL2 里的 Ubuntu。"
            ),
        )
    step_index = int(facts.get("ros2_install_step_index", 0))
    step = recipe.steps[min(step_index, len(recipe.steps) - 1)]
    lines = [
        localize_text(
            language,
            en=f"I selected {ros2_install_summary(recipe, facts)}.",
            zh=f"我选择了 {ros2_install_summary(recipe, facts)}。",
        ),
        localize_text(
            language,
            en=f"Current step: `{min(step_index, len(recipe.steps) - 1) + 1}` of `{len(recipe.steps)}`.",
            zh=f"当前步骤：第 `{min(step_index, len(recipe.steps) - 1) + 1}` / `{len(recipe.steps)}` 步。",
        ),
        localize_text(
            language,
            en=f"Step title: {step['title']}.",
            zh=f"步骤标题：{step['title']}。",
        ),
    ]
    if facts.get("host_has_sudo") is False:
        lines.append(localize_text(
            language,
            en="Warning: this host does not expose `sudo` in PATH, so the guided apt install cannot proceed until a privileged shell is available.",
            zh="警告：这台机器的 PATH 里没有 `sudo`，因此在有可提权 shell 之前，无法继续引导式 apt 安装。",
        ))
    elif facts.get("host_passwordless_sudo") is False:
        lines.append(localize_text(
            language,
            en="Warning: this host needs an interactive sudo password. Run the commands below directly in your shell.",
            zh="警告：这台机器需要交互式 sudo 密码。请直接在你的 shell 里执行下面的命令。",
        ))
    if facts.get("host_is_wsl"):
        lines.append(localize_text(
            language,
            en="This looks like WSL2. Install ROS2 inside Ubuntu first, then attach the robot USB device from Windows.",
            zh="这看起来是 WSL2。请先在 Ubuntu 里安装 ROS2，然后再从 Windows 侧把机器人 USB 设备挂进来。",
        ))
    if str(facts.get("conda_prefix", "")):
        lines.append(localize_text(
            language,
            en="Conda is active. Prefer a clean shell for the official apt-based ROS2 install to avoid Python path conflicts.",
            zh="当前 Conda 处于激活状态。为了避免 Python 路径冲突，建议用一个干净的 shell 来做官方 apt 方式的 ROS2 安装。",
        ))
    lines.extend(
        [
            "```bash",
            *step["commands"],
            "```",
        ]
    )
    if step_index < len(recipe.steps) - 1:
        lines.append(localize_text(
            language,
            en="When this step finishes, tell me in natural language that you are done and I will give you the next step.",
            zh="这一步完成后，直接自然地告诉我你做完了，我就给你下一步。",
        ))
    else:
        lines.append(localize_text(
            language,
            en="When this step finishes, tell me that ROS2 is installed and I will validate the environment before generating the setup assets.",
            zh="这一步完成后，直接告诉我 ROS2 已经装好了，我会先验证环境，再生成 setup 资产。",
        ))
    lines.append(localize_text(
        language,
        en="If a command fails, paste the failing output and I will adjust the flow.",
        zh="如果有命令失败，把失败输出贴给我，我会调整这条流程。",
    ))
    return "\n".join(lines)


def render_ros2_shell_repair(
    facts: dict[str, Any],
    recipe: ROS2InstallRecipe | None = None,
    *,
    language: str | None = None,
) -> str:
    recipe = recipe or select_ros2_recipe(facts)
    distro = str(
        facts.get("ros2_distro")
        or next(iter(facts.get("ros2_installed_distros", [])), "")
        or (recipe.distro if recipe is not None else "")
    )
    shell_name = "zsh" if facts.get("host_shell") == "zsh" else "bash"
    shell_rc = "~/.zshrc" if shell_name == "zsh" else "~/.bashrc"
    if not distro:
        return localize_text(
            language,
            en=(
                "RoboClaw found partial ROS2 installation state, but could not determine which distro to source."
                "\nTell me which `/opt/ros/<distro>` path should be used and I will continue from there."
            ),
            zh=(
                "RoboClaw 发现这台机器上有部分 ROS2 安装状态，但还无法判断该 source 哪个 distro。"
                "\n请告诉我应该使用哪个 `/opt/ros/<distro>` 路径，我会从那里继续。"
            ),
        )
    lines = [
        localize_text(
            language,
            en=f"ROS2 packages are already present under `/opt/ros/{distro}`, but `ros2` is still unavailable in this shell.",
            zh=f"`/opt/ros/{distro}` 下已经有 ROS2 包了，但当前这个 shell 里仍然不能直接使用 `ros2`。",
        ),
        localize_text(
            language,
            en="Finish the shell setup below, open a fresh shell if needed, then tell me that ROS2 is installed so I can re-check.",
            zh="先完成下面的 shell 配置；如果需要，打开一个新的 shell，然后告诉我 ROS2 已经装好，我会重新检查。",
        ),
        "```bash",
        *_shell_init_commands(distro, shell_name, shell_rc),
        "```",
    ]
    return "\n".join(lines)


def advance_ros2_install_step(facts: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    recipe = select_ros2_recipe(facts)
    if recipe is None:
        return dict(facts), False
    next_facts = dict(facts)
    current = int(next_facts.get("ros2_install_step_index", 0))
    if current < len(recipe.steps) - 1:
        next_facts["ros2_install_step_index"] = current + 1
        return next_facts, False
    return next_facts, True


def _normalize(content: str) -> str:
    return " ".join(content.strip().lower().split())


def _shell_init_commands(distro: str, shell_name: str, shell_rc: str) -> tuple[str, ...]:
    shell_setup = f"/opt/ros/{distro}/setup.{shell_name}"
    return (
        f"echo 'source {shell_setup}' >> {shell_rc}",
        f"source {shell_setup}",
        "printenv | grep -i ROS || true",
        "which ros2",
        "ros2 --help",
    )
