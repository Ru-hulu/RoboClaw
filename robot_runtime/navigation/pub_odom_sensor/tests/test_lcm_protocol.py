from __future__ import annotations

import unittest

from robot_runtime.navigation.pub_odom_sensor.lcm_protocol import (
    DECODE_OK,
    ERR_DATA_SIZE_MISMATCH,
    ERR_PAYLOAD_TOO_SHORT,
    decode_odom_sensor_frame,
    encode_odom_sensor_frame,
)


class OdomSensorLcmProtocolTest(unittest.TestCase):
    def test_encode_decode_round_trip(self) -> None:
        pointcloud = b"\x01\x02\x03\x04"
        payload = encode_odom_sensor_frame(
            {
                "stamp_sec": 12,
                "stamp_nanosec": 34,
                "odom": {"frame_id": "world"},
                "lidar": {"frame_id": "livox_mid360_link"},
            },
            pointcloud,
        )

        decoded = decode_odom_sensor_frame(payload)

        self.assertEqual(decoded.state, DECODE_OK)
        self.assertIsNotNone(decoded.header)
        assert decoded.header is not None
        self.assertEqual(decoded.header["schema"], "roboclaw.odom_sensor_frame.v1")
        self.assertEqual(decoded.header["pointcloud_data_size"], len(pointcloud))
        self.assertEqual(decoded.pointcloud_bytes, pointcloud)

    def test_decode_rejects_short_payload(self) -> None:
        decoded = decode_odom_sensor_frame(b"\x01")

        self.assertEqual(decoded.state, ERR_PAYLOAD_TOO_SHORT)

    def test_decode_rejects_truncated_pointcloud(self) -> None:
        payload = encode_odom_sensor_frame({"stamp_sec": 1}, b"1234")[:-1]

        decoded = decode_odom_sensor_frame(payload)

        self.assertEqual(decoded.state, ERR_DATA_SIZE_MISMATCH)


if __name__ == "__main__":
    unittest.main()
