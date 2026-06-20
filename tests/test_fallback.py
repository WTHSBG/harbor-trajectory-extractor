from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from harbor_trajectory_extractor.fallback import extract_with_fallback


class FallbackTest(unittest.TestCase):
    def test_fallback_copies_existing_atif(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            agent_dir = tmp_path / "agent"
            agent_dir.mkdir()
            source = agent_dir / "trajectory.json"
            source.write_text(
                json.dumps(
                    {
                        "schema_version": "ATIF-v1.7",
                        "agent": {"name": "nop", "version": "unknown"},
                        "steps": [{"step_id": 1, "source": "user", "message": "没有在运行。"}],
                    }
                )
            )
            output = tmp_path / "out.json"
            self.assertTrue(extract_with_fallback(agent_dir, output))
            self.assertEqual(json.loads(output.read_text())["agent"]["name"], "nop")
            output_text = output.read_text(encoding="utf-8")
            self.assertIn("没有在运行。", output_text)
            self.assertNotIn("\\u6ca1", output_text)


if __name__ == "__main__":
    unittest.main()
