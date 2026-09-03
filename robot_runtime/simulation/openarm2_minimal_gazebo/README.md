# OpenArm 2.0 Minimal Gazebo Simulation

This package is the saved minimal simulation environment used for RoboClaw
experiments with OpenArm 2.0 mounted on a simple mobile platform.

## Design

- Gazebo Classic + ROS 2 Humble.
- OpenArm 2.0 is loaded from `openarm_description`.
- The mobile platform uses ROSbot XL meshes from `rosbot_description`.
- The world includes a static table and one dynamic cube on the table edge.
- A RealSense-like RGB camera is fixed to the robot head and tilted downward.
- The platform and arm are connected as one rigid model.
- Wheel links are fixed visual geometry only.
- Base motion is commanded directly through `/cmd_vel` by
  `libopenarm2_rigid_cmd_vel_plugin.so`.
- The plugin treats `linear.x` and `linear.y` as body-frame planar velocity,
  and `angular.z` as body yaw rate.
- This package intentionally does not simulate wheel-ground traction.

## Scene

The table is named `work_table`. Its top surface is at about `0.55 m`, roughly
two thirds of the current OpenArm-on-base model height observed in Gazebo. The
cube is named `edge_cube`; it is a `0.045 m` dynamic box placed on the table
edge, sized slightly smaller than the OpenArm pinch gripper finger width.

## Build

Copy this package into a ROS 2 workspace `src` directory, then run:

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select openarm2_minimal_gazebo --symlink-install
source install/setup.bash
```

## Launch

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch openarm2_minimal_gazebo openarm2_gazebo.launch.py gui:=true
```

## Command The Mobile Base

Move forward at `1 m/s` while rotating at `0.5 rad/s`:

```bash
ros2 topic pub --rate 20 /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 1.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.5}}"
```

Stop:

```bash
ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}"
```

## Arm Controller

The arm is exposed through:

```text
/openarm_joint_trajectory_controller/follow_joint_trajectory
```

The active controller list can be checked with:

```bash
ros2 control list_controllers
```

## Head Camera

The head camera link is named `head_realsense_link`. It is fixed to the robot
body at the head position and pitched downward. Gazebo publishes RGB and depth
images through camera plugins under the `/head_realsense` namespace. The default
capture topics are `/head_realsense/color/image_raw` and
`/head_realsense/depth/depth/image_raw`.
