from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from robot_runtime.perception.lcm_protocol import DECODE_OK, DecodeImageResult
from robot_runtime.perception.sam3.position import estimate_position_from_mask_depth


class Sam3PositionTest(unittest.TestCase):
    def test_estimates_centroid_from_best_mask_and_depth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            masks_path = Path(directory) / "masks.npz"
            masks = np.zeros((2, 480, 640), dtype=bool)
            masks[0, 100, 100] = True
            masks[1, 240, 320] = True
            masks[1, 241, 321] = True
            np.savez_compressed(masks_path, masks=masks)

            depth = np.full((480, 640), 2.0, dtype=np.float32)
            depth_frame = DecodeImageResult(
                DECODE_OK,
                {
                    "frame_id": "head_realsense_link",
                    "width": 640,
                    "height": 480,
                    "encoding": "32FC1",
                    "is_bigendian": 0,
                    "step": 640 * 4,
                },
                depth.tobytes(),
            )
            result = estimate_position_from_mask_depth(
                {
                    "instances": [
                        {"index": 0, "score": 0.1},
                        {"index": 1, "score": 0.9},
                    ],
                    "masks_npz_path": str(masks_path),
                },
                depth_frame,
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["frame_id"], "head_realsense_link")
        self.assertAlmostEqual(float(result["x"]), 0.0, places=6)
        self.assertAlmostEqual(float(result["y"]), 0.0, places=6)
        self.assertAlmostEqual(float(result["z"]), 2.0, places=6)

    def test_returns_none_without_detection(self) -> None:
        depth_frame = DecodeImageResult(
            DECODE_OK,
            {
                "width": 640,
                "height": 480,
                "encoding": "32FC1",
                "is_bigendian": 0,
                "step": 640 * 4,
            },
            np.zeros((480, 640), dtype=np.float32).tobytes(),
        )

        result = estimate_position_from_mask_depth(
            {"instances": [], "masks_npz_path": "/tmp/masks.npz"},
            depth_frame,
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
