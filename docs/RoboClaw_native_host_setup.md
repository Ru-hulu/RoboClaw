# RoboClaw Native Host Setup

This is the no-Docker workflow for the upgraded remote host:
Ubuntu 22.04 + ROS 2 Humble.

## System Packages

```bash
sudo apt update
sudo apt install -y \
  python3-venv \
  python3-pip \
  python3-colcon-common-extensions \
  python3-rosdep \
  ros-humble-desktop \
  libboost-dev \
  libompl-dev \
  libopencv-dev
```

## Build ROS 2 Workspace

Run these commands from the repository root:

```bash
source /opt/ros/humble/setup.bash
rm -rf build install log
rosdep install --from-paths robot_runtime --ignore-src -r -y
colcon build --packages-up-to hybrid_astar
source install/setup.bash
```

The Hybrid A* executable used by the MCP tool is installed at:

```text
install/lib/hybrid_astar/hybrid_astar_plan
```

## Python Agent Environment

Create a host venv that can still see ROS 2 Python packages:

```bash
python3 -m venv --system-site-packages ~/roboclaw-agent-venv
~/roboclaw-agent-venv/bin/python -m pip install --upgrade pip
~/roboclaw-agent-venv/bin/python -m pip install -r requirements-host.txt
```

## Start Agent

```bash
cd ~/RoboClaw
source /opt/ros/humble/setup.bash
source install/setup.bash
export PYTHONPATH="$PWD"
~/roboclaw-agent-venv/bin/python roboclaw_next/examples/RuboclawClient.py
```

## Optional RViz

RViz can run directly on the host after the same ROS workspace is sourced:

```bash
cd ~/RoboClaw
source /opt/ros/humble/setup.bash
source install/setup.bash
rviz2
```
