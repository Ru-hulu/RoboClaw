# Differential-Drive MPC

这是一个独立、轻量的差速两轮机器人 MPC 控制器。核心算法不依赖 ROS、MCP、
Agent 或第三方优化器；两个 ROS 节点通过 Topic 组成最小反馈控制闭环。

## 控制流程

每个控制周期调用一次 `DifferentialDriveMPC.solve(...)`：

1. 使用左右轮线速度和差速运动学模型预测未来位姿。
2. 最小化参考轨迹误差、轮速代价和轮速变化代价。
3. 施加轮速与轮加速度约束。
4. 返回预测序列中的第一条轮速命令。
5. 下一周期读取新位姿并重新求解。

## 输入

- `current_pose`：机器人当前二维位姿 `x`、`y`、`yaw`。
- `reference_poses`：从当前时刻开始的参考 path 位姿序列。期望长度为
  `horizon + 1`，不足时自动使用最后一个位姿补齐。

MPC 的外部输入按 path 处理，而不是要求外部直接提供带时间戳的 trajectory。
Hybrid A* 输出的 JSON path 提供二维平面点 `x`、`y` 和 `direction`。
`reference_path.py` 会按 `direction` 切段，避免 B-Spline 跨越换向 cusp，
再把每一段转换为控制周期可用的 B-Spline reference pose 序列。
当前 MPC 求解器消费的是 `x/y/yaw` 位姿序列。

## 输出

`MPCResult` 包含：

- `command.left_speed`：左轮线速度，单位 m/s。
- `command.right_speed`：右轮线速度，单位 m/s。
- `command.linear_speed`：等效车体线速度，单位 m/s。
- `command.angular_speed`：等效车体角速度，单位 rad/s。
- `predicted_poses`：当前 MPC 时域内的预测位姿。
- `cost`、`iterations`、`converged`：本次求解状态。

## 可调参数

`MPCConfig` 中的参数分为四组：

- 模型：`dt`、`horizon`、`wheel_base`。
- 约束：`max_wheel_speed`、`max_wheel_acceleration`。
- 代价：`position_weight`、`yaw_weight`、终端误差权重、轮速和轮速变化权重。
- 求解器：`optimizer_iterations`、`learning_rate`、
  `finite_difference_epsilon`、`convergence_tolerance`。

## 最小 ROS 2 闭环

`ros_node.py` 可以读取 `reference_path_file` 参数指向的 Hybrid A* JSON path；
未提供该参数时，节点会直接退出。节点订阅 `/robot_posture`，
并将 MPC 得到的左右轮速度转换为 `geometry_msgs/msg/Twist` 发布到 `/cmd_vel`。

启动 MPC 节点时需要显式传入 Hybrid A* path 文件：

```bash
python3 -m robot_runtime.control.differential_drive_mpc.ros_node \
  --ros-args -p reference_path_file:=runtime_data/hybrid_astar/latest_hybrid_astar_path.json
```

定位/仿真桥节点需要另外提供 `/robot_posture`。其他终端可以观察 MPC 输出和姿态输入：

```bash
ros2 topic echo /cmd_vel geometry_msgs/msg/Twist
ros2 topic echo /robot_posture geometry_msgs/msg/PoseStamped
```

MPC 节点执行 60 个控制周期后发布零速度并自动退出。

## RViz 调试轨迹

调试可视化代码集中在 `robot_runtime/debug/rviz_path.py`，不参与 MPC 解算或定位计算。
节点额外发布：

- `/reference_path`：MPC 使用的参考轨迹。

在 RViz 中将 Fixed Frame 设置为 `map`，添加 `Path` Display 并选择上述 Topic。
不再需要调试显示时，可以删除该调试模块及两个节点中的发布器调用。

## 当前边界

当前实现采用运动学模型，只负责跟踪给定参考轨迹；不处理障碍物、碰撞、轮胎打滑、
电机动力学或路径规划。`/robot_posture` 需要由真实 SLAM、Gazebo 真值桥或其他定位节点提供。
