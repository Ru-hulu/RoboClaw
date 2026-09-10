from __future__ import annotations

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

    def test_declares_pointcloud_message_shape(self) -> None:
        cloud = PointCloud2Message(
            header=Header(seq=0, stamp=Time(sec=1, nsec=2), frame_id="livox_mid360_link"),
            height=1,
            width=1,
            fields=(PointField(name="x", offset=0, datatype=7, count=1),),
            is_bigendian=False,
            point_step=16,
            row_step=16,
            data=b"1234567890123456",
            is_dense=True,
        )

        self.assertEqual(cloud.header.frame_id, "livox_mid360_link")
        self.assertEqual(cloud.fields[0].name, "x")
        self.assertEqual(cloud.point_step, 16)


if __name__ == "__main__":
    unittest.main()
