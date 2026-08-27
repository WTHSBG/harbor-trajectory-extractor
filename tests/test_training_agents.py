from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from harbor_trajectory_extractor.training_agents import export_agent_training_jsonl
from harbor_trajectory_extractor.training_claude import (
    export_claude_native_training_jsonl,
)
from harbor_trajectory_extractor.training_cli import main as training_main


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def kimi_wire(prompt: str, user_text: str, call_id: str) -> list[dict]:
    return [
        {"type": "metadata", "protocol_version": "1.5"},
        {
            "type": "profile.bind",
            "modelAlias": "k3-test",
            "systemPrompt": prompt,
        },
        {
            "type": "turn.prompt",
            "input": [{"type": "text", "text": user_text}],
            "origin": {"kind": "user"},
            "time": 1000,
        },
        {
            "type": "context.append_message",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": user_text}],
                "origin": {"kind": "user"},
                "id": "user-1",
            },
            "time": 1001,
        },
        {
            "type": "context.append_loop_event",
            "event": {"type": "step.begin", "uuid": "step-1"},
            "time": 1002,
        },
        {
            "type": "context.append_loop_event",
            "event": {
                "type": "content.part",
                "part": {"type": "think", "think": "先分析"},
            },
            "time": 1003,
        },
        {
            "type": "context.append_loop_event",
            "event": {
                "type": "tool.call",
                "toolCallId": call_id,
                "name": "Read",
                "args": {"path": "README.md"},
            },
            "time": 1004,
        },
        {
            "type": "context.append_loop_event",
            "event": {
                "type": "tool.result",
                "toolCallId": call_id,
                "result": {"output": "README content"},
            },
            "time": 1005,
        },
        {
            "type": "context.append_loop_event",
            "event": {"type": "step.end", "usage": {"inputOther": 5, "output": 2}},
            "time": 1006,
        },
    ]


class AgentTrainingExportTest(unittest.TestCase):
    def test_kimi_exports_main_and_subagent_with_captured_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "session_kimi"
            state = {
                "id": "session_kimi",
                "agents": {
                    "main": {"type": "main"},
                    "agent-1": {"type": "sub", "parentAgentId": "main"},
                },
            }
            root.mkdir(parents=True)
            (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
            write_jsonl(
                root / "agents" / "main" / "wire.jsonl",
                kimi_wire("KIMI MAIN SYSTEM", "主任务", "Read:0"),
            )
            write_jsonl(
                root / "agents" / "agent-1" / "wire.jsonl",
                kimi_wire("KIMI SUB SYSTEM", "子任务", "Read:1"),
            )
            output = Path(tmp) / "training.jsonl"
            report = export_agent_training_jsonl(
                agent="kimi-code", source=root, output=output
            )
            samples = [json.loads(line) for line in output.read_text().splitlines()]

            self.assertEqual(report.samples_written, 2)
            self.assertEqual([sample["sample_type"] for sample in samples], ["main", "subagent"])
            self.assertEqual(samples[0]["messages"][0]["content"], "KIMI MAIN SYSTEM")
            self.assertEqual(samples[1]["messages"][0]["content"], "KIMI SUB SYSTEM")
            self.assertEqual(samples[1]["metadata"]["parent_agent_id"], "main")
            assistant = samples[0]["messages"][2]
            self.assertEqual(assistant["reasoning_content"], "先分析")
            self.assertEqual(assistant["tool_calls"][0]["id"], "Read:0")
            self.assertEqual(samples[0]["messages"][3]["tool_call_id"], "Read:0")

    def test_kimi_subagent_compaction_is_split_and_rehydrated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "session_kimi_compact"
            root.mkdir(parents=True)
            (root / "state.json").write_text(
                json.dumps(
                    {
                        "id": "session_kimi_compact",
                        "agents": {
                            "agent-1": {"type": "sub", "parentAgentId": "main"}
                        },
                    }
                ),
                encoding="utf-8",
            )
            write_jsonl(
                root / "agents" / "main" / "wire.jsonl",
                [{"type": "metadata", "protocol_version": "1.5"}],
            )
            rows = kimi_wire("SUB SYSTEM", "压缩前任务", "Read:before")
            rows.extend(
                [
                    {"type": "full_compaction.begin", "agentId": "agent-1"},
                    {"type": "llm.request", "kind": "compaction", "model": "k3-test"},
                    {
                        "type": "context.apply_compaction",
                        "summary": "精简后的接手笔记",
                        "contextSummary": "压缩后的完整上下文摘要",
                        "keptUserMessageCount": 1,
                        "tokensBefore": 100,
                        "tokensAfter": 20,
                    },
                    {"type": "full_compaction.complete", "agentId": "agent-1"},
                    {
                        "type": "turn.prompt",
                        "input": [{"type": "text", "text": "压缩后继续"}],
                        "origin": {"kind": "user"},
                        "time": 2000,
                    },
                    {
                        "type": "context.append_message",
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": "压缩后继续"}],
                            "origin": {"kind": "user"},
                        },
                        "time": 2001,
                    },
                    {
                        "type": "context.append_loop_event",
                        "event": {"type": "step.begin", "uuid": "after"},
                        "time": 2002,
                    },
                    {
                        "type": "context.append_loop_event",
                        "event": {
                            "type": "content.part",
                            "part": {"type": "text", "text": "继续完成"},
                        },
                        "time": 2003,
                    },
                    {
                        "type": "context.append_loop_event",
                        "event": {"type": "step.end", "usage": {"inputOther": 2, "output": 1}},
                        "time": 2004,
                    },
                ]
            )
            write_jsonl(root / "agents" / "agent-1" / "wire.jsonl", rows)
            output = Path(tmp) / "training.jsonl"
            report = export_agent_training_jsonl(
                agent="kimi-code", source=root, output=output
            )
            samples = [json.loads(line) for line in output.read_text().splitlines()]

            self.assertEqual(report.samples_written, 3)
            self.assertEqual(
                [sample["sample_type"] for sample in samples],
                ["subagent", "context_compaction", "subagent"],
            )
            compact = samples[1]
            self.assertEqual(compact["messages"][-1]["content"], "精简后的接手笔记")
            self.assertEqual(compact["metadata"]["parent_agent_id"], "agent-1")
            self.assertEqual(
                compact["metadata"]["artifact"]["compaction_request_source"],
                "canonical-fallback",
            )
            post = samples[2]
            post_contents = [message.get("content", "") for message in post["messages"]]
            self.assertIn("压缩前任务", post_contents)
            self.assertIn("[CONTEXT_SUMMARY]\n压缩后的完整上下文摘要", post_contents)
            self.assertNotIn("README content", "\n".join(post_contents))

    def test_hermes_preserves_system_reasoning_and_tool_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "hermes.jsonl"
            session = {
                "id": "hermes-1",
                "model": "test-model",
                "system_prompt": "HERMES SYSTEM",
                "messages": [
                    {"role": "user", "content": "检查项目"},
                    {
                        "role": "assistant",
                        "content": "我先读取。",
                        "reasoning_content": "先看 README",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "terminal",
                                    "arguments": '{"command":"ls"}',
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call-1",
                        "tool_name": "terminal",
                        "content": "README.md",
                    },
                    {"role": "assistant", "content": "完成。"},
                ],
            }
            write_jsonl(source, [session])
            output = Path(tmp) / "training.jsonl"
            report = export_agent_training_jsonl(
                agent="hermes", source=source, output=output
            )
            sample = json.loads(output.read_text().splitlines()[0])

            self.assertEqual(report.samples_written, 1)
            self.assertEqual(sample["messages"][0]["content"], "HERMES SYSTEM")
            self.assertEqual(sample["messages"][2]["reasoning_content"], "先看 README")
            self.assertEqual(sample["messages"][2]["tool_calls"][0]["id"], "call-1")
            self.assertEqual(sample["messages"][3]["tool_call_id"], "call-1")

    def test_hermes_state_db_includes_descendant_subagents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.db"
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    parent_session_id TEXT,
                    model TEXT,
                    system_prompt TEXT,
                    started_at REAL,
                    ended_at REAL
                );
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    timestamp REAL,
                    active INTEGER DEFAULT 1
                );
                """
            )
            conn.executemany(
                "INSERT INTO sessions VALUES (?, ?, 'model', ?, ?, ?)",
                [
                    ("root", None, "ROOT SYSTEM", 1.0, 2.0),
                    ("child", "root", "CHILD SYSTEM", 1.5, 1.8),
                ],
            )
            conn.executemany(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                [
                    ("root", "user", "主任务", 1.0),
                    ("root", "assistant", "主回答", 2.0),
                    ("child", "user", "子任务", 1.5),
                    ("child", "assistant", "子回答", 1.8),
                ],
            )
            conn.commit()
            conn.close()

            output = Path(tmp) / "training.jsonl"
            report = export_agent_training_jsonl(
                agent="hermes",
                source=path,
                session_id="root",
                output=output,
            )
            samples = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual(report.samples_written, 2)
            self.assertEqual([sample["sample_type"] for sample in samples], ["main", "subagent"])
            self.assertEqual(samples[1]["metadata"]["parent_agent_id"], "root")
            self.assertEqual(samples[1]["messages"][0]["content"], "CHILD SYSTEM")

    def test_hermes_state_db_uses_post_compaction_active_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.db"
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    parent_session_id TEXT,
                    model TEXT,
                    system_prompt TEXT,
                    started_at REAL,
                    ended_at REAL
                );
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    timestamp REAL,
                    active INTEGER DEFAULT 1,
                    compacted INTEGER DEFAULT 0
                );
                """
            )
            conn.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
                ("compact-root", None, "model", "HERMES SYSTEM", 1.0, 3.0),
            )
            conn.executemany(
                """
                INSERT INTO messages
                    (session_id, role, content, timestamp, active, compacted)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    ("compact-root", "user", "压缩前旧任务", 1.0, 0, 1),
                    ("compact-root", "assistant", "压缩前旧回答", 1.5, 0, 1),
                    ("compact-root", "user", "[CONTEXT_SUMMARY]\n压缩后的上下文", 2.0, 1, 0),
                    ("compact-root", "assistant", "根据摘要继续完成", 3.0, 1, 0),
                ],
            )
            conn.commit()
            conn.close()

            output = Path(tmp) / "training.jsonl"
            report = export_agent_training_jsonl(
                agent="hermes",
                source=path,
                session_id="compact-root",
                output=output,
            )
            sample = json.loads(output.read_text().splitlines()[0])
            serialized = json.dumps(sample, ensure_ascii=False)

            self.assertEqual(report.samples_written, 1)
            self.assertIn("[CONTEXT_SUMMARY]", serialized)
            self.assertIn("根据摘要继续完成", serialized)
            self.assertNotIn("压缩前旧任务", serialized)
            self.assertNotIn("压缩前旧回答", serialized)

    def test_opencode_export_is_compiled_to_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "opencode-export.json"
            source.write_text(
                json.dumps(
                    {
                        "info": {"id": "ses-open"},
                        "messages": [
                            {
                                "info": {"role": "user", "sessionID": "ses-open"},
                                "parts": [{"type": "text", "text": "分析问题"}],
                            },
                            {
                                "info": {"role": "assistant", "sessionID": "ses-open"},
                                "parts": [
                                    {"type": "step-start", "sessionID": "ses-open"},
                                    {"type": "reasoning", "text": "先检查"},
                                    {"type": "text", "text": "结论"},
                                    {
                                        "type": "step-finish",
                                        "tokens": {"input": 1, "output": 1},
                                    },
                                ],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output = Path(tmp) / "training.jsonl"
            report = export_agent_training_jsonl(
                agent="opencode", source=source, output=output
            )
            sample = json.loads(output.read_text().splitlines()[0])

            self.assertEqual(report.samples_written, 1)
            self.assertEqual(sample["metadata"]["source_agent"], "opencode")
            self.assertEqual(sample["messages"][-1]["reasoning_content"], "先检查")
            self.assertEqual(sample["messages"][-1]["content"], "结论")

    def test_claude_direct_session_uses_native_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "claude-session.jsonl"
            write_jsonl(
                source,
                [
                    {
                        "type": "user",
                        "uuid": "u1",
                        "sessionId": "claude-1",
                        "timestamp": "2026-08-28T00:00:00Z",
                        "message": {"role": "user", "content": "检查项目"},
                    },
                    {
                        "type": "assistant",
                        "uuid": "a1",
                        "parentUuid": "u1",
                        "sessionId": "claude-1",
                        "timestamp": "2026-08-28T00:00:01Z",
                        "message": {
                            "id": "m1",
                            "role": "assistant",
                            "content": [
                                {"type": "thinking", "thinking": "先读取"},
                                {"type": "text", "text": "检查完成"},
                            ],
                        },
                    },
                ],
            )
            output = Path(tmp) / "training.jsonl"
            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = training_main(
                    [
                        "--agent",
                        "claude-code",
                        "--source",
                        str(source),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(exit_code, 0)
            sample = json.loads(output.read_text().splitlines()[0])
            self.assertEqual(sample["metadata"]["source_agent"], "claude-code")
            self.assertEqual(sample["messages"][-1]["reasoning_content"], "先读取")

    def test_claude_direct_session_keeps_subagent_compaction_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / ".claude" / "projects" / "-workspace"
            session_id = "claude-compact"
            before = [
                {
                    "type": "user",
                    "uuid": "u1",
                    "parentUuid": None,
                    "message": {"role": "user", "content": "压缩前任务"},
                },
                {
                    "type": "assistant",
                    "uuid": "a1",
                    "parentUuid": "u1",
                    "message": {
                        "id": "m1",
                        "role": "assistant",
                        "content": [{"type": "text", "text": "压缩前回答"}],
                    },
                },
            ]
            write_jsonl(
                project / f"{session_id}.jsonl",
                [
                    *before,
                    {
                        "type": "system",
                        "subtype": "compact_boundary",
                        "uuid": "boundary",
                        "logicalParentUuid": "a1",
                    },
                    {
                        "type": "user",
                        "uuid": "summary-user",
                        "parentUuid": "boundary",
                        "isCompactSummary": True,
                        "message": {"role": "user", "content": "压缩后的上下文"},
                    },
                    {
                        "type": "assistant",
                        "uuid": "a2",
                        "parentUuid": "summary-user",
                        "message": {
                            "id": "m2",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "压缩后回答"}],
                        },
                    },
                ],
            )
            subagents = project / session_id / "subagents"
            write_jsonl(
                subagents / "agent-acompact-test.jsonl",
                [
                    *before,
                    {
                        "type": "user",
                        "uuid": "compact-request",
                        "parentUuid": "a1",
                        "agentId": "acompact-test",
                        "message": {
                            "role": "user",
                            "content": "Summarize the conversation with a summary block.",
                        },
                    },
                    {
                        "type": "assistant",
                        "uuid": "compact-answer",
                        "parentUuid": "compact-request",
                        "agentId": "acompact-test",
                        "message": {
                            "id": "compact-message",
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "<summary>子 Agent 压缩摘要</summary>"}
                            ],
                        },
                    },
                ],
            )
            output = Path(tmp) / "training.jsonl"
            report = export_claude_native_training_jsonl(
                source=project / f"{session_id}.jsonl",
                output=output,
                system_prompt="CLAUDE SYSTEM",
            )
            samples = [json.loads(line) for line in output.read_text().splitlines()]

            self.assertEqual(report.main_samples_written, 2)
            self.assertEqual(report.context_compaction_samples_written, 1)
            compact = next(
                sample for sample in samples if sample["sample_type"] == "context_compaction"
            )
            self.assertEqual(compact["metadata"]["parent_agent_id"], "acompact-test")
            self.assertEqual(
                compact["messages"][-1]["content"],
                "<summary>子 Agent 压缩摘要</summary>",
            )

    def test_codex_training_is_not_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "codex.jsonl"
            source.write_text("{}\n", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                exit_code = training_main(
                    [
                        "--agent",
                        "codex",
                        "--source",
                        str(source),
                        "--output",
                        str(Path(tmp) / "training.jsonl"),
                    ]
                )
            self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
