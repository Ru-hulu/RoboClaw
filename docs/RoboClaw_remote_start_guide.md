# RoboClaw Remote Start Guide

> Legacy note: this document records the old Docker/Jazzy workflow. The remote
> host has moved to Ubuntu 22.04 + ROS 2 Humble; prefer
> `docs/RoboClaw_native_host_setup.md` for the no-Docker workflow.

这份说明用于在远程设备上启动 RoboClaw Agent 和 RViz，并通过自然语言 prompt 调用定位、Hybrid A* 路径规划和 MPC 路径跟踪。

## 1. SSH 到远程设备

在本地终端执行：

```bash
ssh bozhao_4060_2@192.168.107.154
```

进入项目目录：

```bash
cd ~/RoboClaw
```

## 2. 启动 Agent

在第一个 SSH 终端中执行：

```bash
docker run --rm -it --init \
  --name roboclaw_agent_gui \
  --network host \
  --ipc host \
  --user "$(id -u):$(id -g)" \
  --workdir /workspace/RoboClaw \
  --env HOME=/tmp \
  --env DISPLAY=:0 \
  --env QT_X11_NO_MITSHM=1 \
  --env LIBGL_ALWAYS_SOFTWARE=1 \
  --env-file ~/.config/roboclaw/agent.env \
  --volume /tmp/.X11-unix:/tmp/.X11-unix \
  --volume ~/RoboClaw:/workspace/RoboClaw \
  --volume ~/roboclaw-agent-venv:/opt/roboclaw-agent-venv \
  roboclaw-ros2:jazzy-hybrid-astar \
  bash -lc 'source /opt/ros/jazzy/setup.bash && source install/setup.bash && exec /opt/roboclaw-agent-venv/bin/python roboclaw_next/examples/RuboclawClient.py'
```

看到类似下面内容后，说明 Agent 已经启动：

```text
[mcp] registered tools:
- roboclaw_tools__start_mock_localization
- roboclaw_tools__get_mock_localization
- roboclaw_tools__plan_hybrid_astar_path
- roboclaw_tools__start_path_tracking

Enter /exit to quit.

You:
```

## 3. 启动 RViz

另开一个 SSH 终端：

```bash
ssh bozhao_4060_2@192.168.107.154
```

把 RViz 配置复制进同一个容器：

```bash
docker cp ~/roboclaw_path_debug.rviz roboclaw_agent_gui:/tmp/roboclaw_path_debug.rviz
```

进入同一个容器启动 RViz：

```bash
docker exec -it roboclaw_agent_gui bash -lc 'source /opt/ros/jazzy/setup.bash && source install/setup.bash && rviz2 -d /tmp/roboclaw_path_debug.rviz'
```

关键点：RViz 必须通过 `docker exec` 跑在同一个 `roboclaw_agent_gui` 容器里。只用另一个 Docker 容器启动 RViz，即使加了 `--network host`，也可能因为 ROS 2 DDS/IPC 问题导致 graph 能看到 topic 但收不到消息。

## 4. 在 Agent 终端输入 prompt

回到第一个 Agent 终端，在 `You:` 后输入自然语言指令。

查询当前位姿：

```text
告诉我机器人的当前位姿
```

移动到目标位姿：

```text
机器人移动到 x=70 y=40 yaw=1.57 的目标位姿
```

如果需要重新规划并替换当前 MPC 跟踪，可以说得更明确：

```text
机器人移动到 x=40 y=40 yaw=0 的目标位姿。如果当前已经有MPC路径跟踪在运行，请先停止当前路径跟踪，然后获取当前机器人位姿作为起点，重新调用Hybrid A*规划，并启动MPC跟踪新的路径。
```

## 5. RViz 中应该看到什么

RViz 配置中主要显示：

- `/reference_path`：MPC 使用的参考路径，通常是橙色。
- `/robot_path`：Mock Localization 累积出来的机器人实际运动轨迹，通常是蓝色。
- `/robot_posture`：机器人当前姿态箭头。

当前地图坐标系是 `map`，80x80 米。地图中心是 `(40, 40)`。

## 6. 常用检查命令

查看容器是否在运行：

```bash
docker ps
```

查看 ROS 2 节点：

```bash
docker exec -it roboclaw_agent_gui bash -lc 'source /opt/ros/jazzy/setup.bash && source install/setup.bash && ros2 node list'
```

查看 RViz 是否订阅 `/reference_path`：

```bash
docker exec -it roboclaw_agent_gui bash -lc 'source /opt/ros/jazzy/setup.bash && source install/setup.bash && ros2 topic info /reference_path -v'
```

临时查看一条参考路径消息：

```bash
docker exec -it roboclaw_agent_gui bash -lc 'source /opt/ros/jazzy/setup.bash && source install/setup.bash && ros2 topic echo /reference_path --qos-durability transient_local --once'
```

## 7. 清理旧状态

如果再次启动 Agent 时提示容器名已经存在，可以先清理：

```bash
docker rm -f roboclaw_agent_gui
```

如果用了 tmux 启动过旧会话，也可以清理：

```bash
tmux kill-session -t roboclaw_agent
tmux kill-session -t roboclaw_rviz
```

这些命令只清理运行中的容器或 tmux 会话，不会删除项目代码。
