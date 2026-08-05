from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from harbor_trajectory_extractor.cli import build_extract_request, main, parse_args
from harbor_trajectory_extractor.kimi_code import convert_session, locate_wire_file


def sample_wire_events() -> list[dict]:
    """Minimal but realistic Kimi Code wire.jsonl event sequence."""
    return [
        {"type": "metadata", "protocol_version": "1.5", "created_at": 1785906663201},
        {"type": "profile.bind", "modelAlias": "k2-test", "profileName": "agent"},
        {
            "type": "turn.prompt",
            "input": [{"type": "text", "text": "你好，帮我看下项目"}],
            "origin": {"kind": "user"},
            "time": 1785906663294,
        },
        {
            "type": "context.append_message",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "你好，帮我看下项目"}],
                "toolCalls": [],
                "origin": {"kind": "user"},
                "id": "msg_1",
            },
            "time": 1785906663296,
        },
        {
            "type": "context.append_loop_event",
            "event": {"type": "step.begin", "uuid": "u1", "turnId": "0", "step": 1},
            "time": 1785906663298,
        },
        {
            "type": "llm.request",
            "kind": "loop",
            "model": "k2",
            "modelAlias": "k2-test",
            "time": 1785906663306,
        },
        {
            "type": "usage.record",
            "model": "k2-test",
            "usage": {
                "inputOther": 100,
                "output": 10,
                "inputCacheRead": 50,
                "inputCacheCreation": 5,
            },
            "usageScope": "turn",
            "time": 1785906672378,
        },
        {
            "type": "context.append_loop_event",
            "event": {
                "type": "content.part",
                "uuid": "c1",
                "turnId": "0",
                "step": 1,
                "part": {"type": "think", "think": "先思考一下"},
            },
            "time": 1785906672380,
        },
        {
            "type": "context.append_loop_event",
            "event": {
                "type": "content.part",
                "uuid": "c2",
                "turnId": "0",
                "step": 1,
                "part": {"type": "text", "text": "好的，我来执行。"},
            },
            "time": 1785906672381,
        },
        {
            "type": "context.append_loop_event",
            "event": {
                "type": "tool.call",
                "uuid": "t1",
                "turnId": "0",
                "step": 1,
                "toolCallId": "Bash:0",
                "name": "Bash",
                "args": {"command": "ls"},
            },
            "time": 1785906672481,
        },
        {
            "type": "context.append_loop_event",
            "event": {
                "type": "tool.result",
                "parentUuid": "t1",
                "toolCallId": "Bash:0",
                "result": {"output": "file1\nfile2", "truncated": True},
            },
            "time": 1785906672550,
        },
        {
            "type": "context.append_loop_event",
            "event": {
                "type": "step.end",
                "uuid": "u1",
                "turnId": "0",
                "step": 1,
                "finishReason": "tool_use",
                "usage": {
                    "inputOther": 100,
                    "output": 10,
                    "inputCacheRead": 50,
                    "inputCacheCreation": 5,
                },
            },
            "time": 1785906672558,
        },
        {
            "type": "context.append_message",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "<system-reminder>注意</system-reminder>"}],
                "origin": {"kind": "injection"},
                "id": "msg_2",
            },
            "time": 1785906673000,
        },
        # Dangling step: no step.end arrives, so usage falls back to usage.record.
        {
            "type": "context.append_loop_event",
            "event": {"type": "step.begin", "uuid": "u2", "turnId": "0", "step": 2},
            "time": 1785906674000,
        },
        {
            "type": "usage.record",
            "model": "k2-test",
            "usage": {
                "inputOther": 200,
                "output": 20,
                "inputCacheRead": 0,
                "inputCacheCreation": 0,
            },
            "usageScope": "turn",
            "time": 1785906674100,
        },
        {
            "type": "context.append_loop_event",
            "event": {
                "type": "content.part",
                "uuid": "c3",
                "turnId": "0",
                "step": 2,
                "part": {"type": "text", "text": "完成。"},
            },
            "time": 1785906674200,
        },
        {"type": "turn.ended", "turnId": 0, "reason": "completed", "time": 1785906675000},
    ]


def write_session(root: Path, events: list[dict] | None = None) -> Path:
    """Create a session_<uuid>/ directory layout with wire.jsonl + state.json."""
    session_dir = root / "session_abc-123"
    wire_dir = session_dir / "agents" / "main"
    wire_dir.mkdir(parents=True)
    lines = events if events is not None else sample_wire_events()
    (wire_dir / "wire.jsonl").write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in lines) + "\n"
    )
    (session_dir / "state.json").write_text(
        json.dumps(
            {
                "id": "session_abc-123",
                "version": 2,
                "cwd": "/tmp/proj",
                "title": "测试会话",
                "createdAt": 1785906662884,
            },
            ensure_ascii=False,
        )
    )
    return session_dir


class ConvertSessionTest(unittest.TestCase):
    def convert(self, events: list[dict] | None = None, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = write_session(Path(tmp), events)
            trajectory = convert_session(
                session_dir / "agents" / "main" / "wire.jsonl", **kwargs
            )
            self.assertIsNotNone(trajectory)
            return trajectory.to_json_dict()

    def test_full_conversion(self) -> None:
        data = self.convert()

        self.assertEqual(data["schema_version"], "ATIF-v1.7")
        self.assertEqual(data["session_id"], "abc-123")
        self.assertEqual(data["agent"]["name"], "kimi-code")
        self.assertEqual(data["agent"]["model_name"], "k2-test")
        self.assertEqual(data["agent"]["extra"]["cwd"], "/tmp/proj")
        self.assertEqual(data["agent"]["extra"]["title"], "测试会话")
        self.assertEqual(data["agent"]["extra"]["wire_protocol_version"], "1.5")

        steps = data["steps"]
        self.assertEqual([s["source"] for s in steps], ["user", "agent", "system", "agent"])

        user_step = steps[0]
        # turn.prompt was deduplicated against context.append_message.
        self.assertEqual(user_step["message"], "你好，帮我看下项目")
        self.assertEqual(user_step["extra"]["message_id"], "msg_1")
        self.assertEqual(user_step["timestamp"], "2026-08-05T05:11:03.296Z")

        agent_step = steps[1]
        self.assertEqual(agent_step["message"], "好的，我来执行。")
        self.assertEqual(agent_step["reasoning_content"], "先思考一下")
        self.assertEqual(agent_step["llm_call_count"], 1)
        self.assertEqual(
            agent_step["tool_calls"],
            [
                {
                    "tool_call_id": "Bash:0",
                    "function_name": "Bash",
                    "arguments": {"command": "ls"},
                }
            ],
        )
        results = agent_step["observation"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_call_id"], "Bash:0")
        self.assertEqual(results[0]["content"], "file1\nfile2")
        self.assertTrue(results[0]["extra"]["truncated"])
        metrics = agent_step["metrics"]
        self.assertEqual(metrics["prompt_tokens"], 155)  # 100 + 50 + 5
        self.assertEqual(metrics["completion_tokens"], 10)
        self.assertEqual(metrics["cached_tokens"], 50)
        self.assertEqual(metrics["extra"]["input_cache_creation"], 5)

        system_step = steps[2]
        self.assertEqual(system_step["source"], "system")
        self.assertEqual(system_step["extra"]["origin"], "injection")

        dangling = steps[3]
        self.assertEqual(dangling["message"], "完成。")
        # The step had no step.end; metrics came from the usage.record fallback.
        self.assertEqual(dangling["metrics"]["prompt_tokens"], 200)
        self.assertEqual(dangling["metrics"]["completion_tokens"], 20)

        final = data["final_metrics"]
        self.assertEqual(final["total_prompt_tokens"], 355)
        self.assertEqual(final["total_completion_tokens"], 30)
        self.assertEqual(final["total_cached_tokens"], 50)
        self.assertEqual(final["total_steps"], 4)

    def test_model_override_wins_over_wire_hint(self) -> None:
        data = self.convert(model_name="override-model")
        self.assertEqual(data["agent"]["model_name"], "override-model")

    def test_prompt_without_matching_message_is_kept(self) -> None:
        events = [
            event
            for event in sample_wire_events()
            if not (
                event["type"] == "context.append_message"
                and event["message"].get("id") == "msg_1"
            )
        ]
        data = self.convert(events)
        self.assertEqual(data["steps"][0]["source"], "user")
        self.assertEqual(data["steps"][0]["message"], "你好，帮我看下项目")

    def test_session_id_from_path_when_state_has_no_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = write_session(Path(tmp))
            # Older sessions store workDir instead of cwd and have no id.
            (session_dir / "state.json").write_text(
                json.dumps({"workDir": "/legacy/proj", "title": "旧会话"})
            )
            data = convert_session(
                session_dir / "agents" / "main" / "wire.jsonl"
            ).to_json_dict()
            self.assertEqual(data["session_id"], "abc-123")
            self.assertEqual(data["agent"]["extra"]["cwd"], "/legacy/proj")

    def test_empty_wire_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wire = Path(tmp) / "wire.jsonl"
            wire.write_text('{"type": "metadata", "protocol_version": "1.5"}\n')
            self.assertIsNone(convert_session(wire))

    def test_blank_and_broken_lines_are_skipped(self) -> None:
        events = sample_wire_events()
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = write_session(Path(tmp), events)
            wire = session_dir / "agents" / "main" / "wire.jsonl"
            with wire.open("a", encoding="utf-8") as handle:
                handle.write("\nnot-json\n")
            data = convert_session(wire).to_json_dict()
            self.assertEqual(data["final_metrics"]["total_steps"], 4)


class SourcePreparationTest(unittest.TestCase):
    def build_request(self, argv: list[str]):
        args = parse_args(argv)
        return build_extract_request(args)

    def test_wire_file_is_staged_with_state_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = write_session(Path(tmp))
            wire = session_dir / "agents" / "main" / "wire.jsonl"
            request = self.build_request(
                ["--agent", "kimi-code", "--source", str(wire)]
            )
            try:
                # The session_<uuid> directory name is preserved so the
                # session id survives staging even without state.json.
                self.assertEqual(request.work_dir.name, session_dir.name)
                staged = request.work_dir / "agents" / "main" / "wire.jsonl"
                self.assertTrue(staged.exists())
                self.assertTrue((request.work_dir / "state.json").exists())
                self.assertEqual(
                    request.output, (wire.parent / "trajectory.json").resolve()
                )
            finally:
                if request.cleanup is not None:
                    request.cleanup.cleanup()

    def test_session_dir_is_used_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = write_session(Path(tmp))
            request = self.build_request(
                ["--agent", "kimi-code", "--source", str(session_dir)]
            )
            try:
                self.assertEqual(request.work_dir, session_dir.resolve())
                self.assertIsNone(request.cleanup)
            finally:
                if request.cleanup is not None:
                    request.cleanup.cleanup()

    def test_wd_dir_with_one_session_is_staged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wd_dir = Path(tmp) / "wd_proj_abcdef123456"
            wd_dir.mkdir()
            write_session(wd_dir)
            request = self.build_request(
                ["--agent", "kimi", "--source", str(wd_dir)]
            )
            try:
                self.assertEqual(request.agent, "kimi-code")  # alias normalized
                self.assertTrue(
                    (request.work_dir / "agents" / "main" / "wire.jsonl").exists()
                )
                self.assertTrue((request.work_dir / "state.json").exists())
            finally:
                if request.cleanup is not None:
                    request.cleanup.cleanup()

    def test_dir_with_multiple_sessions_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_session(root)
            second = root / "session_def-456" / "agents" / "main"
            second.mkdir(parents=True)
            (second / "wire.jsonl").write_text("{}\n")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main(
                    ["--agent", "kimi-code", "--source", str(root)]
                )
            self.assertEqual(exit_code, 2)
            self.assertIn("multiple sessions", stderr.getvalue())

    def test_locate_wire_file_prefers_main_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sub = root / "agents" / "agent-3"
            main_dir = root / "agents" / "main"
            sub.mkdir(parents=True)
            main_dir.mkdir(parents=True)
            (sub / "wire.jsonl").write_text("{}\n")
            (main_dir / "wire.jsonl").write_text("{}\n")
            self.assertEqual(locate_wire_file(root), main_dir / "wire.jsonl")


class CliEndToEndTest(unittest.TestCase):
    def run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(argv)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_extract_from_session_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = write_session(Path(tmp))
            output = Path(tmp) / "out" / "trajectory.json"
            exit_code, stdout, stderr = self.run_cli(
                [
                    "--agent",
                    "kimi-code",
                    "--source",
                    str(session_dir),
                    "--output",
                    str(output),
                    "--summary",
                ]
            )
            self.assertEqual(exit_code, 0, stderr)
            summary = json.loads(stdout)
            self.assertEqual(summary["agent"], "kimi-code")
            self.assertEqual(summary["session_id"], "abc-123")
            self.assertEqual(summary["steps"], 4)
            self.assertEqual(summary["reasoning_steps"], 1)
            self.assertEqual(summary["tool_calls"], 1)

            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["agent"]["name"], "kimi-code")
            # UTF-8 content must survive the whole pipeline unescaped.
            self.assertEqual(data["steps"][0]["message"], "你好，帮我看下项目")

    def test_extract_from_wire_file_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = write_session(Path(tmp))
            wire = session_dir / "agents" / "main" / "wire.jsonl"
            output = Path(tmp) / "trajectory.json"
            exit_code, stdout, stderr = self.run_cli(
                [
                    "--agent",
                    "kimi",
                    "--source",
                    str(wire),
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(exit_code, 0, stderr)
            self.assertEqual(stdout.strip(), str(output.resolve()))
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["agent"]["name"], "kimi-code")

    def test_extract_wire_file_without_state_json_keeps_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = write_session(Path(tmp))
            (session_dir / "state.json").unlink()
            wire = session_dir / "agents" / "main" / "wire.jsonl"
            output = Path(tmp) / "trajectory.json"
            exit_code, _, stderr = self.run_cli(
                [
                    "--agent",
                    "kimi-code",
                    "--source",
                    str(wire),
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(exit_code, 0, stderr)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["session_id"], "abc-123")

    def test_empty_wire_fails_with_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wire = Path(tmp) / "wire.jsonl"
            wire.write_text('{"type": "metadata"}\n')
            exit_code, _, stderr = self.run_cli(
                [
                    "--agent",
                    "kimi-code",
                    "--source",
                    str(wire),
                    "--output",
                    str(Path(tmp) / "out.json"),
                ]
            )
            self.assertEqual(exit_code, 1)
            self.assertIn("native converter", stderr)


if __name__ == "__main__":
    unittest.main()
