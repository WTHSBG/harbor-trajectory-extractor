from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from harbor_trajectory_extractor.cli import main
from harbor_trajectory_extractor.hermes import (
    convert_session,
    load_export,
    load_state_db,
)


def sample_session(session_id: str = "20260810_120000_abcdef") -> dict:
    return {
        "id": session_id,
        "source": "cli",
        "model": "openrouter/test-model",
        "title": "Hermes 测试",
        "cwd": "/tmp/project",
        "started_at": 1786324800,
        "input_tokens": 120,
        "output_tokens": 30,
        "cache_read_tokens": 20,
        "cache_write_tokens": 4,
        "reasoning_tokens": 8,
        "actual_cost_usd": 0.012,
        "api_call_count": 2,
        "model_config": json.dumps({"reasoning_config": {"effort": "high"}}),
        "messages": [
            {
                "id": 1,
                "role": "user",
                "content": "检查项目",
                "timestamp": 1786324801,
            },
            {
                "id": 2,
                "role": "assistant",
                "content": "我先查看。",
                "reasoning": "先列目录",
                # The same text commonly appears in both provider-facing fields.
                "reasoning_content": "先列目录",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "terminal",
                            "arguments": '{"command":"ls"}',
                        },
                    }
                ],
                "timestamp": 1786324802,
                "token_count": 10,
            },
            {
                "id": 3,
                "role": "tool",
                "tool_call_id": "call_1",
                "tool_name": "terminal",
                "content": "README.md",
                "timestamp": 1786324803,
            },
            {
                "id": 4,
                "role": "assistant",
                "content": "完成。",
                "reasoning_details": json.dumps(
                    [{"type": "reasoning.text", "text": "结果正常"}]
                ),
                "codex_reasoning_items": [
                    {
                        "type": "reasoning",
                        "summary": [
                            {"type": "summary_text", "text": "复核结论"}
                        ],
                        "encrypted_content": "opaque-do-not-export",
                    }
                ],
                "timestamp": 1786324804,
                "token_count": 20,
            },
        ],
    }


class HermesConverterTest(unittest.TestCase):
    def test_full_conversion_preserves_reasoning_tools_and_metrics(self) -> None:
        trajectory = convert_session(sample_session())
        self.assertIsNotNone(trajectory)
        assert trajectory is not None
        data = trajectory.to_json_dict()

        self.assertEqual(data["schema_version"], "ATIF-v1.7")
        self.assertEqual(data["session_id"], "20260810_120000_abcdef")
        self.assertEqual(data["agent"]["name"], "hermes")
        self.assertEqual(data["agent"]["model_name"], "openrouter/test-model")
        self.assertEqual(data["agent"]["extra"]["cwd"], "/tmp/project")

        steps = data["steps"]
        self.assertEqual([step["source"] for step in steps], ["user", "agent", "agent"])
        self.assertEqual(steps[1]["reasoning_content"], "先列目录")
        self.assertEqual(steps[1]["reasoning_effort"], "high")
        self.assertEqual(
            steps[1]["tool_calls"][0],
            {
                "tool_call_id": "call_1",
                "function_name": "terminal",
                "arguments": {"command": "ls"},
            },
        )
        self.assertEqual(
            steps[1]["observation"]["results"][0]["content"], "README.md"
        )
        self.assertEqual(
            steps[2]["reasoning_content"], "结果正常\n\n复核结论"
        )
        self.assertNotIn("opaque-do-not-export", steps[2]["reasoning_content"])

        final = data["final_metrics"]
        self.assertEqual(final["total_prompt_tokens"], 120)
        self.assertEqual(final["total_completion_tokens"], 30)
        self.assertEqual(final["total_cached_tokens"], 20)
        self.assertEqual(final["extra"]["reasoning_tokens"], 8)
        self.assertEqual(final["extra"]["cache_write_tokens"], 4)

    def test_reasoning_only_message_gets_a_valid_display_message(self) -> None:
        session = {
            "id": "reasoning-only",
            "messages": [
                {"role": "assistant", "content": "", "reasoning_content": "思考中"}
            ],
        }
        data = convert_session(session).to_json_dict()
        self.assertEqual(data["steps"][0]["message"], "(reasoning)")
        self.assertEqual(data["steps"][0]["reasoning_content"], "思考中")

    def test_multi_session_export_requires_or_uses_selector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "all.jsonl"
            path.write_text(
                "\n".join(
                    json.dumps(sample_session(session_id), ensure_ascii=False)
                    for session_id in ("session-one", "session-two")
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "multiple sessions"):
                load_export(path)
            selected = load_export(path, session_id="session-t")
            self.assertEqual(selected["id"], "session-two")


class HermesStateDbTest(unittest.TestCase):
    def create_db(self, path: Path) -> None:
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                source TEXT,
                model TEXT,
                model_config TEXT,
                system_prompt TEXT,
                started_at REAL,
                ended_at REAL,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cache_read_tokens INTEGER,
                reasoning_tokens INTEGER
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                tool_call_id TEXT,
                tool_calls TEXT,
                tool_name TEXT,
                timestamp REAL,
                token_count INTEGER,
                reasoning TEXT,
                reasoning_content TEXT,
                reasoning_details TEXT,
                codex_reasoning_items TEXT,
                codex_message_items TEXT,
                active INTEGER DEFAULT 1
            );
            """
        )
        conn.executemany(
            "INSERT INTO sessions (id, source, model, started_at, ended_at, input_tokens, output_tokens) "
            "VALUES (?, 'cli', 'test/model', ?, ?, 10, 5)",
            [
                ("old-session", 100.0, 101.0),
                ("new-session", 200.0, 201.0),
            ],
        )
        conn.executemany(
            "INSERT INTO messages (session_id, role, content, timestamp, reasoning_content) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                ("old-session", "user", "旧问题", 100.0, None),
                ("new-session", "user", "新问题", 200.0, None),
                ("new-session", "assistant", "新回答", 201.0, "数据库中的思考"),
            ],
        )
        conn.commit()
        conn.close()

    def test_state_db_defaults_to_latest_and_accepts_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.db"
            self.create_db(path)
            latest = load_state_db(path)
            self.assertEqual(latest["id"], "new-session")
            self.assertEqual(latest["messages"][1]["reasoning_content"], "数据库中的思考")
            old = load_state_db(path, session_id="old-s")
            self.assertEqual(old["id"], "old-session")

    def test_cli_extracts_selected_state_db_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "state.db"
            output = root / "out.json"
            self.create_db(path)
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--agent",
                        "hermes",
                        "--source",
                        str(path),
                        "--session",
                        "new-s",
                        "--output",
                        str(output),
                        "--summary",
                    ]
                )
            self.assertEqual(exit_code, 0, stderr.getvalue())
            summary = json.loads(stdout.getvalue())
            self.assertEqual(summary["session_id"], "new-session")
            self.assertEqual(summary["reasoning_steps"], 1)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["steps"][1]["reasoning_content"], "数据库中的思考")


if __name__ == "__main__":
    unittest.main()
