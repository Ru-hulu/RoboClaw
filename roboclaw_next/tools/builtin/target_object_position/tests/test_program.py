from __future__ import annotations

import unittest

from roboclaw_next.tools.builtin.target_object_position.program import (
    TargetObjectPositionResolver,
)


class FakeSegmentClient:
    def __init__(self, result: dict[str, object] | None = None) -> None:
        self.result = result or {}
        self.prompts: list[str] = []

    def segment(self, text_prompt: str) -> dict[str, object]:
        self.prompts.append(text_prompt)
        return self.result


class FailingSegmentClient:
    def segment(self, text_prompt: str) -> dict[str, object]:
        del text_prompt
        raise RuntimeError("SAM3 service is not running")


class TargetObjectPositionResolverTest(unittest.TestCase):
    def test_returns_best_segmentation_source_without_position(self) -> None:
        client = FakeSegmentClient(
            {
                "request_id": "request-1",
                "instances": [
                    {
                        "score": 0.3,
                        "mask_area_pixels": 10,
                        "box_xyxy_pixels": [1, 2, 3, 4],
                    },
                    {
                        "score": 0.8,
                        "mask_area_pixels": 20,
                        "box_xyxy_pixels": [5, 6, 7, 8],
                    },
                ],
                "result_json_path": "/tmp/result.json",
                "overlay_path": "/tmp/overlay.png",
            }
        )
        resolver = TargetObjectPositionResolver(lambda: client)

        result = resolver.get_position(" cube ")

        self.assertTrue(result.success)
        self.assertFalse(result.position_valid)
        self.assertIsNone(result.position)
        self.assertEqual(result.confidence, 0.8)
        self.assertEqual(result.source.segmentation_request_id, "request-1")
        self.assertEqual(result.source.mask_area_pixels, 20)
        self.assertEqual(result.source.box_xyxy_pixels, [5.0, 6.0, 7.0, 8.0])
        self.assertEqual(result.source.result_json_path, "/tmp/result.json")
        self.assertEqual(result.source.overlay_path, "/tmp/overlay.png")
        self.assertEqual(client.prompts, ["cube"])

    def test_reads_position_returned_by_sam3(self) -> None:
        client = FakeSegmentClient(
            {
                "request_id": "request-3",
                "instances": [
                    {
                        "index": 0,
                        "score": 0.9,
                        "mask_area_pixels": 2,
                        "box_xyxy_pixels": [319, 239, 320, 240],
                    }
                ],
                "position_valid": True,
                "position": {
                    "frame_id": "head_realsense_link",
                    "x": 0.1,
                    "y": -0.2,
                    "z": 2.0,
                },
            }
        )
        resolver = TargetObjectPositionResolver(lambda: client)

        result = resolver.get_position("cube")

        self.assertTrue(result.success)
        self.assertTrue(result.position_valid)
        self.assertIsNotNone(result.position)
        assert result.position is not None
        self.assertEqual(result.position.frame_id, "head_realsense_link")
        self.assertAlmostEqual(result.position.x, 0.1, places=6)
        self.assertAlmostEqual(result.position.y, -0.2, places=6)
        self.assertAlmostEqual(result.position.z, 2.0, places=6)
        self.assertEqual(result.confidence, 0.9)

    def test_returns_success_without_detection(self) -> None:
        resolver = TargetObjectPositionResolver(
            lambda: FakeSegmentClient({"request_id": "request-2", "instances": []})
        )

        result = resolver.get_position("cube")

        self.assertTrue(result.success)
        self.assertFalse(result.position_valid)
        self.assertIsNone(result.position)
        self.assertIsNone(result.confidence)
        self.assertEqual(result.source.segmentation_request_id, "request-2")

    def test_returns_failure_when_rpc_fails(self) -> None:
        resolver = TargetObjectPositionResolver(lambda: FailingSegmentClient())

        result = resolver.get_position("cube")

        self.assertFalse(result.success)
        self.assertFalse(result.position_valid)
        self.assertIsNone(result.position)
        self.assertIn("SAM3 service is not running", result.message)


if __name__ == "__main__":
    unittest.main()
