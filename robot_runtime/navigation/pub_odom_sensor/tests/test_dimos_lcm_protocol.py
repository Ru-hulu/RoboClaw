from __future__ import annotations

import struct
from types import SimpleNamespace
import unittest

from robot_runtime.navigation.pub_odom_sensor.dimos_lcm_protocol import (
    Header,
    ODOMETRY_CHANNEL,
    ODOMETRY_TOPIC,
    ODOMETRY_TYPE,
    POINTCLOUD2_TYPE,
    PointCloud2Message,
    PointField,
    REGISTERED_SCAN_CHANNEL,
    REGISTERED_SCAN_TOPIC,
    Time,
    encode_dimos_pointcloud2_lcm,
    ros_pointcloud2_to_dimos_lcm_message,
)


class DimosLcmProtocolTest(unittest.TestCase):
    def test_declares_dimos_typed_channels(self) -> None:
        self.assertEqual(
            REGISTERED_SCAN_CHANNEL,
            "/registered_scan#sensor_msgs.PointCloud2",
        )
        self.assertEqual(ODOMETRY_CHANNEL, "/odometry#nav_msgs.Odometry")

    def test_topic_metadata_matches_channels(self) -> None:
        self.assertEqual(REGISTERED_SCAN_TOPIC.stream, "registered_scan")
        self.assertEqual(REGISTERED_SCAN_TOPIC.message_type, POINTCLOUD2_TYPE)
        self.assertEqual(REGISTERED_SCAN_TOPIC.channel, REGISTERED_SCAN_CHANNEL)
        self.assertEqual(ODOMETRY_TOPIC.stream, "odometry")
        self.assertEqual(ODOMETRY_TOPIC.message_type, ODOMETRY_TYPE)
        self.assertEqual(ODOMETRY_TOPIC.channel, ODOMETRY_CHANNEL)

    def test_maps_ros_pointcloud2_to_dimos_message_shape(self) -> None:
        ros_message = SimpleNamespace(
            header=SimpleNamespace(
                stamp=SimpleNamespace(sec=1, nanosec=2),
                frame_id="livox_mid360_link",
            ),
            height=1,
            width=1,
            fields=(
                SimpleNamespace(name="x", offset=0, datatype=7, count=1),
                SimpleNamespace(name="intensity", offset=12, datatype=7, count=1),
            ),
            is_bigendian=False,
            point_step=16,
            row_step=16,
            data=b"1234567890123456",
            is_dense=True,
        )

        cloud = ros_pointcloud2_to_dimos_lcm_message(ros_message)

        self.assertEqual(cloud.header.stamp, Time(sec=1, nsec=2))
        self.assertEqual(cloud.header.frame_id, "livox_mid360_link")
        self.assertEqual(cloud.fields[1], PointField("intensity", 12, 7, 1))
        self.assertEqual(cloud.data, b"1234567890123456")

    def test_encodes_pointcloud2_with_dimos_lcm_wire_layout(self) -> None:
        cloud = PointCloud2Message(
            header=Header(seq=0, stamp=Time(sec=1, nsec=2), frame_id="lidar"),
            height=1,
            width=1,
            fields=(PointField(name="x", offset=0, datatype=7, count=1),),
            is_bigendian=False,
            point_step=4,
            row_step=4,
            data=b"abcd",
            is_dense=True,
        )

        payload = encode_dimos_pointcloud2_lcm(cloud)

        expected = b"".join(
            [
                struct.pack(">Q", 0xF5EB3DA1C2853175),
                struct.pack(">ii", 1, 4),
                struct.pack(">i", 0),
                struct.pack(">ii", 1, 2),
                struct.pack(">I", len(b"lidar") + 1),
                b"lidar\0",
                struct.pack(">ii", 1, 1),
                struct.pack(">I", len(b"x") + 1),
                b"x\0",
                struct.pack(">iBi", 0, 7, 1),
                struct.pack(">bii", 0, 4, 4),
                b"abcd",
                struct.pack(">b", 1),
            ]
        )
        self.assertEqual(payload, expected)


if __name__ == "__main__":
    unittest.main()
