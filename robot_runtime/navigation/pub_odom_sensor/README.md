# pubOdomSensor

`pubOdomSensor` is the Gazebo navigation input bridge. It listens to:

- `/livox/lidar` (`sensor_msgs/msg/PointCloud2`) for the simulated Mid-360 scan

For each lidar frame, the node immediately calls `/gazebo/get_entity_state`
(`gazebo_msgs/srv/GetEntityState`) for the current `openarm_v20` ground-truth
pose and twist, then publishes the lidar frame on `/registered_scan#sensor_msgs.PointCloud2` and the existing merged payload on `ROBOCLAW_ODOM_SENSOR_FRAME`.
The payload is:

```text
uint32 little-endian JSON header length
JSON header with odom and lidar layout
raw PointCloud2 data bytes
```

The fixed remote Gazebo extrinsic is hard-coded as:

```text
base_footprint -> livox_mid360_link
xyz = 0.13 0.0 0.21345
rpy = 0.0 0.0 0.0
```

This comes from the remote model chain:

```text
base_link -> body_link: z=0.05
body_link -> cover_link: z=0.08345
cover_link -> livox_mid360_link: xyz=0.13 0 0.08
```

## Dimos-compatible target protocol

The current publisher keeps the existing `ROBOCLAW_ODOM_SENSOR_FRAME` payload and also publishes dimos-compatible point cloud frames.
For the future FastLIO-compatible path, the target dimos channels are declared in
`dimos_lcm_protocol.py`:

```text
/registered_scan#sensor_msgs.PointCloud2
/odometry#nav_msgs.Odometry
```

`dimos_lcm_protocol.py` currently declares the message shapes locally without
introducing a runtime dependency on `dimos_lcm`. The later publisher step should
map ROS/Gazebo data into these shapes, then encode them with the generated LCM
classes or an equivalent local encoder.

