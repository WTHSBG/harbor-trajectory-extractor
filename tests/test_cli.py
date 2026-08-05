from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from harbor_trajectory_extractor.cli import build_extract_request, main, parse_args


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
        self.assertIn("--source", output)
        self.assertNotIn("--agent-dir", output)
        self.assertNotIn("--backend", output)
        self.assertNotIn("--kwargs-json", output)

    def test_missing_source_explains_next_step(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            exit_code = main(["--agent", "opencode"])

        self.assertEqual(exit_code, 2)
        output = stderr.getvalue()
        self.assertIn("Missing --source", output)
        self.assertIn("--source <path>", output)
        self.assertIn("htextract --describe-agent opencode", output)

    def test_list_agents_only_exposes_supported_extractors(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = main(["--list-agents"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            stdout.getvalue().splitlines(),
            ["claude-code", "codex", "kimi-code", "opencode"],
        )

    def test_unsupported_agent_is_explicitly_rejected(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            exit_code = main(["--describe-agent", "gemini-cli"])

        self.assertEqual(exit_code, 2)
        output = stderr.getvalue()
        self.assertIn("unsupported agent: gemini-cli", output)
        self.assertIn(
            "currently supported agents: claude-code, codex, kimi-code, opencode", output
        )

    def test_claude_code_describes_cost_log_as_optional(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = main(["--describe-agent", "claude-code"])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Pass this run's native artifact directly with --source:", output)
        self.assertIn("Native artifacts this converter needs:", output)
        self.assertIn("Optional artifacts:", output)
        self.assertIn("Claude Code session .jsonl", output)
        self.assertIn("claude-code.txt", output)
        self.assertNotIn("--agent-dir", output)

    def test_opencode_describes_required_capture_flags(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = main(["--describe-agent", "opencode"])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("opencode export <sessionID>", output)
        self.assertIn("opencode-export.json", output)
        self.assertIn("opencode --source ./opencode.jsonl", output)
        self.assertIn("run --format=json", output)
        self.assertIn("--thinking", output)
        self.assertNotIn("--agent-dir", output)

    def test_codex_describes_session_jsonl_not_stdout(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = main(["--describe-agent", "codex"])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("CODEX_HOME/sessions", output)
        self.assertIn("session JSONL", output)
        self.assertIn("codex.txt is only a human-readable run log", output)
        self.assertNotIn("--agent-dir", output)

    def test_claude_code_source_file_is_staged_as_session_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "session.jsonl"
            source.write_text('{"type":"user","message":{"content":"hi"}}\n')
            args = parse_args(["--agent", "claude-code", "--source", str(source)])
            request = build_extract_request(args)
            try:
                staged = (
                    request.work_dir
                    / "sessions"
                    / "projects"
                    / "imported"
                    / "session.jsonl"
                )
                self.assertTrue(staged.exists())
                self.assertEqual(request.output, (source.parent / "trajectory.json").resolve())
            finally:
                if request.cleanup is not None:
                    request.cleanup.cleanup()

    def test_opencode_source_file_is_staged_as_opencode_txt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "opencode.jsonl"
            source.write_text('{"type":"step_start"}\n')
            args = parse_args(["--agent", "opencode", "--source", str(source)])
            request = build_extract_request(args)
            try:
                self.assertTrue((request.work_dir / "opencode.txt").exists())
                self.assertEqual(request.output, (source.parent / "trajectory.json").resolve())
            finally:
                if request.cleanup is not None:
                    request.cleanup.cleanup()

    def test_codex_source_file_is_staged_under_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "codex-session.jsonl"
            source.write_text('{"type":"session_meta","payload":{"id":"s"}}\n')
            args = parse_args(["--agent", "codex", "--source", str(source)])
            request = build_extract_request(args)
            try:
                staged = request.work_dir / "sessions" / "imported" / source.name
                self.assertTrue(staged.exists())
                self.assertEqual(request.output, (source.parent / "trajectory.json").resolve())
            finally:
                if request.cleanup is not None:
                    request.cleanup.cleanup()


if __name__ == "__main__":
    unittest.main()
