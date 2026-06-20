from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harbor_trajectory_extractor import vendored
from harbor_trajectory_extractor.vendored import activate_vendor_namespace, vendor_root


class VendoredBackendTest(unittest.TestCase):
    def test_harbor_import_resolves_to_project_vendor(self) -> None:
        activate_vendor_namespace()
        harbor = importlib.import_module("harbor")
        self.assertTrue(str(harbor.__file__).startswith(str(vendor_root())))

    def test_vendored_output_is_rewritten_with_utf8_text(self) -> None:
        class DummyAgent:
            def __init__(self, logs_dir: Path) -> None:
                self.logs_dir = logs_dir

            def populate_context_post_run(self, _context: object) -> None:
                payload = {
                    "schema_version": "ATIF-v1.7",
                    "agent": {"name": "codex", "version": "unknown"},
                    "steps": [
                        {
                            "step_id": 1,
                            "source": "agent",
                            "message": "没有在运行。",
                        }
                    ],
                }
                (self.logs_dir / "trajectory.json").write_text(
                    json.dumps(payload, indent=2),
                    encoding="utf-8",
                )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output = tmp_path / "out.json"

            with mock.patch.object(
                vendored,
                "_build_agent",
                return_value=DummyAgent(tmp_path),
            ):
                vendored.extract_with_vendored_backend(
                    agent_name="codex",
                    agent_dir=tmp_path,
                    output=output,
                    model_name=None,
                    kwargs={},
                    instruction_path=None,
                )

            output_text = output.read_text(encoding="utf-8")
            self.assertIn("没有在运行。", output_text)
            self.assertNotIn("\\u6ca1", output_text)

    def test_opencode_flushes_unfinished_stream_turn(self) -> None:
        activate_vendor_namespace()
        from harbor.agents.installed.opencode import OpenCode

        agent = object.__new__(OpenCode)
        agent.model_name = "gpt-5.5"
        agent._version = None
        agent._instruction = "Analyze the incident."

        trajectory = agent._convert_events_to_trajectory(
            [
                {
                    "type": "step_start",
                    "timestamp": 1781946570898,
                    "sessionID": "ses_test",
                    "part": {"type": "step-start"},
                },
                {
                    "type": "reasoning",
                    "timestamp": 1781946580563,
                    "sessionID": "ses_test",
                    "part": {
                        "type": "reasoning",
                        "text": "Considering pod isolation strategies",
                    },
                },
                {
                    "type": "text",
                    "timestamp": 1781946615870,
                    "sessionID": "ses_test",
                    "part": {"type": "text", "text": "结论：隔离构建机。"},
                },
            ]
        )

        self.assertIsNotNone(trajectory)
        assert trajectory is not None
        self.assertEqual(len(trajectory.steps), 2)
        self.assertEqual(trajectory.steps[0].source, "user")
        self.assertEqual(trajectory.steps[1].source, "agent")
        self.assertEqual(
            trajectory.steps[1].reasoning_content,
            "Considering pod isolation strategies",
        )


if __name__ == "__main__":
    unittest.main()
