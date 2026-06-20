from __future__ import annotations

import contextlib
import io
import unittest

from harbor_trajectory_extractor.cli import main


class CliTest(unittest.TestCase):
    def test_no_args_prints_help(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = main([])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Workflows:", output)
        self.assertIn("Agent already ran:", output)
        self.assertIn("--describe-agent", output)

    def test_missing_agent_dir_explains_next_step(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            exit_code = main(["--agent", "opencode"])

        self.assertEqual(exit_code, 2)
        output = stderr.getvalue()
        self.assertIn("Missing --agent-dir", output)
        self.assertIn("htextract --describe-agent opencode", output)


if __name__ == "__main__":
    unittest.main()
