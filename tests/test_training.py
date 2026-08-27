from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from harbor_trajectory_extractor.claude_code_prompts import (
    UNKNOWN_SUBAGENT_SYSTEM_PROMPT,
)
from harbor_trajectory_extractor.training import export_training_jsonl


def write_jsonl(path: Path, events: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )


class TrainingExportTest(unittest.TestCase):
    def make_task(self, root: Path) -> tuple[Path, Path, str]:
        task = root / "tasks" / "arvo_1"
        task.mkdir(parents=True)
        (task / "final_status.json").write_text(
            json.dumps({"task_id": "arvo:1", "status": "success"}),
            encoding="utf-8",
        )
        session_id = "session-main"
        project = (
            task
            / "logs"
            / "arvo_1-agent"
            / "cc_session"
            / ".claude"
            / "projects"
            / "-workspace"
        )
        return task, project, session_id

    def make_hanxueming_task(self, root: Path) -> tuple[Path, Path, str]:
        task = (
            root
            / "node0"
            / "worker1"
            / "logs"
            / "arvo_42-deadbeef"
        )
        project = task / "logs" / "projects" / "-workspace"
        session_id = "han-session"
        return task, project, session_id

    def make_rujia_task(self, root: Path, category: str = "v8") -> tuple[Path, Path, str]:
        task = root / "worker_0" / category / "v8_clusterfuzz_123"
        project = task / "logs" / "projects" / "-workspace"
        return task, project, "rujia-session"

    def test_rujia_layout_discovers_worker_user_and_v8_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task, project, session_id = self.make_rujia_task(root)
            write_jsonl(
                project / f"{session_id}.jsonl",
                [
                    {"type": "user", "uuid": "u", "message": {"role": "user", "content": "Task"}},
                    {"type": "assistant", "uuid": "a", "parentUuid": "u", "message": {"id": "m", "role": "assistant", "content": [{"type": "text", "text": "Done"}]}},
                ],
            )
            output = root / "training.jsonl"
            report = export_training_jsonl(source=root, output=output, layout="rujia")
            self.assertEqual(report.layout, "rujia")
            self.assertEqual(report.tasks_seen, 1)
            self.assertGreater(report.samples_written, 0)

    def test_rujia_success_only_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_rujia_task(root)
            with self.assertRaisesRegex(ValueError, "success-only.*rujia"):
                export_training_jsonl(
                    source=root,
                    output=root / "training.jsonl",
                    layout="rujia",
                    success_only=True,
                )

    def test_unknown_subagent_type_uses_minimal_sdk_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task, project, session_id = self.make_task(root)
            write_jsonl(
                project / f"{session_id}.jsonl",
                [
                    {"type": "user", "uuid": "u", "message": {"role": "user", "content": "Task"}},
                    {
                        "type": "assistant",
                        "uuid": "a",
                        "parentUuid": "u",
                        "message": {"id": "m", "role": "assistant", "content": [{"type": "text", "text": "Done"}]},
                    },
                ],
            )
            subagents = project / session_id / "subagents"
            write_jsonl(
                subagents / "agent-general.jsonl",
                [
                    {"type": "user", "uuid": "su", "message": {"role": "user", "content": "Analyze"}},
                    {
                        "type": "assistant",
                        "uuid": "sa",
                        "parentUuid": "su",
                        "message": {"id": "sm", "role": "assistant", "content": [{"type": "text", "text": "Result"}]},
                    },
                ],
            )
            (subagents / "agent-general.meta.json").write_text(
                json.dumps({"agentType": "general-purpose"}), encoding="utf-8"
            )

            output = root / "training.jsonl"
            export_training_jsonl(source=root, output=output)
            samples = [json.loads(line) for line in output.read_text().splitlines()]
            subagent = next(sample for sample in samples if sample["sample_type"] == "subagent")
            self.assertEqual(
                subagent["messages"][0]["content"], UNKNOWN_SUBAGENT_SYSTEM_PROMPT
            )

    def test_discovers_sessions_splits_compaction_and_includes_acompact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task, project, session_id = self.make_task(root)
            main = project / f"{session_id}.jsonl"
            events = [
                {
                    "type": "user",
                    "uuid": "u1",
                    "parentUuid": None,
                    "message": {"role": "user", "content": "Read the task."},
                },
                {
                    "type": "assistant",
                    "uuid": "a1",
                    "parentUuid": "u1",
                    "message": {
                        "id": "m1",
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Before compact."}],
                    },
                },
                {
                    "type": "system",
                    "subtype": "compact_boundary",
                    "uuid": "c1",
                    "parentUuid": None,
                    "logicalParentUuid": "pruned-parent-not-in-session",
                },
                {
                    "type": "user",
                    "uuid": "u2",
                    "parentUuid": "c1",
                    "isCompactSummary": True,
                    "message": {"role": "user", "content": "Summary state."},
                },
                {
                    "type": "assistant",
                    "uuid": "a2",
                    "parentUuid": "u2",
                    "message": {
                        "id": "m2",
                        "role": "assistant",
                        "content": [{"type": "text", "text": "After compact."}],
                    },
                },
            ]
            write_jsonl(main, events)

            sub_dir = project / session_id / "subagents"
            write_jsonl(
                sub_dir / "agent-real.jsonl",
                [
                    {
                        "type": "user",
                        "uuid": "su",
                        "parentUuid": None,
                        "message": {"role": "user", "content": "Inspect parser."},
                    },
                    {
                        "type": "assistant",
                        "uuid": "sa",
                        "parentUuid": "su",
                        "message": {
                            "id": "sm",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Parser result."}],
                        },
                    },
                ],
            )
            (sub_dir / "agent-real.meta.json").write_text(
                json.dumps({"agentType": "Explore"}), encoding="utf-8"
            )
            write_jsonl(
                sub_dir / "agent-acompact-deadbeef.jsonl",
                [
                    *events[:2],
                    {
                        "type": "user",
                        "uuid": "cu",
                        "parentUuid": "a1",
                        "agentId": "acompact-deadbeef",
                        "isSidechain": True,
                        "message": {
                            "role": "user",
                            "content": "Summarize the conversation. Respond with a summary block.",
                        },
                    },
                    {
                        "type": "assistant",
                        "uuid": "ca",
                        "parentUuid": "cu",
                        "agentId": "acompact-deadbeef",
                        "isSidechain": True,
                        "message": {
                            "id": "cm",
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "<summary>Compressed state.</summary>"}
                            ],
                        },
                    },
                ],
            )

            output = root / "training.jsonl"
            report = export_training_jsonl(
                source=root,
                output=output,
                main_system_prompt="MAIN SYSTEM",
                subagent_system_prompt="SUBAGENT SYSTEM",
            )
            samples = [json.loads(line) for line in output.read_text().splitlines()]

            self.assertEqual(report.samples_written, 4)
            self.assertEqual(report.tasks_eligible, 1)
            self.assertEqual(report.tasks_with_samples, 1)
            self.assertEqual(report.main_samples_written, 2)
            self.assertEqual(report.subagent_samples_written, 1)
            self.assertEqual(report.context_compaction_samples_written, 1)
            report_data = json.loads(
                output.with_suffix(".jsonl.report.json").read_text()
            )
            self.assertFalse(report_data["success_only"])
            self.assertIsNone(report_data["successful_tasks_selected"])
            self.assertEqual(
                report_data["sample_type_counts"],
                {"main": 2, "subagent": 1, "context_compaction": 1},
            )
            self.assertEqual(report.compact_agents_included, 1)
            self.assertEqual(report.valid_compact_agents, 1)
            self.assertEqual(report.invalid_compact_agents_skipped, 0)
            self.assertEqual(len(samples), 4)
            self.assertTrue(
                all(
                    sample["messages"][0]["content"] == "MAIN SYSTEM"
                    for sample in samples
                    if sample["sample_type"] == "main"
                )
            )
            self.assertTrue(
                all(
                    sample["messages"][0]["content"] == "SUBAGENT SYSTEM"
                    for sample in samples
                    if sample["sample_type"] == "subagent"
                )
            )
            self.assertTrue(
                all(
                    sample["messages"][0]["content"] == "MAIN SYSTEM"
                    for sample in samples
                    if sample["sample_type"] == "context_compaction"
                )
            )
            compact = next(
                sample for sample in samples if sample["sample_type"] == "context_compaction"
            )
            self.assertIn("context-compaction-acompact-deadbeef", compact["id"])
            self.assertEqual(
                compact["messages"][-1]["content"],
                "<summary>Compressed state.</summary>",
            )
            post = next(
                sample
                for sample in samples
                if sample["sample_type"] == "main"
                and sample["id"].endswith("segment-002")
            )
            self.assertIn("[CONTEXT_SUMMARY]", post["messages"][1]["content"])
            self.assertNotIn("Before compact", json.dumps(post))

    def test_failed_compaction_is_skipped_before_deduplication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task, project, session_id = self.make_task(root)
            main_events = [
                {
                    "type": "user",
                    "uuid": "u",
                    "parentUuid": None,
                    "message": {"role": "user", "content": "Task"},
                },
                {
                    "type": "assistant",
                    "uuid": "a",
                    "parentUuid": "u",
                    "message": {
                        "id": "m",
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Normal final answer"}],
                    },
                },
            ]
            write_jsonl(project / f"{session_id}.jsonl", main_events)
            write_jsonl(
                project / session_id / "subagents" / "agent-acompact-failed.jsonl",
                [
                    *main_events,
                    {
                        "type": "user",
                        "uuid": "compact-request",
                        "parentUuid": "a",
                        "message": {
                            "role": "user",
                            "content": "Create a detailed summary of the conversation.",
                        },
                    },
                ],
            )

            output = root / "training.jsonl"
            report = export_training_jsonl(source=root, output=output)
            samples = [json.loads(line) for line in output.read_text().splitlines()]

            self.assertEqual(report.compact_agents_included, 1)
            self.assertEqual(report.valid_compact_agents, 0)
            self.assertEqual(report.invalid_compact_agents_skipped, 1)
            self.assertEqual(report.duplicate_samples_skipped, 0)
            self.assertEqual(report.samples_written, 1)
            self.assertEqual(samples[0]["sample_type"], "main")
            self.assertTrue(any("invalid compact agent" in item for item in report.warnings))

    def test_terminal_missing_tool_result_is_retained_and_marked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task, project, session_id = self.make_task(root)
            write_jsonl(
                project / f"{session_id}.jsonl",
                [
                    {
                        "type": "user",
                        "uuid": "u",
                        "parentUuid": None,
                        "message": {"role": "user", "content": "Run it"},
                    },
                    {
                        "type": "assistant",
                        "uuid": "a",
                        "parentUuid": "u",
                        "message": {
                            "id": "m",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "call_wait",
                                    "name": "Bash",
                                    "input": {"command": "sleep 300"},
                                }
                            ],
                        },
                    },
                ],
            )

            output = root / "training.jsonl"
            report = export_training_jsonl(source=root, output=output)
            sample = json.loads(output.read_text())

            self.assertEqual(report.samples_written, 1)
            self.assertEqual(report.incomplete_segments_skipped, 0)
            self.assertEqual(report.terminal_tool_result_missing_samples_included, 1)
            self.assertEqual(sample["messages"][-1]["role"], "assistant")
            self.assertEqual(sample["messages"][-1]["tool_calls"][0]["name"], "Bash")
            self.assertEqual(
                sample["termination"],
                {"reason": "missing_terminal_tool_result", "tool_names": ["Bash"]},
            )

    def test_nonterminal_missing_tool_result_requires_explicit_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task, project, session_id = self.make_task(root)
            write_jsonl(
                project / f"{session_id}.jsonl",
                [
                    {
                        "type": "user",
                        "uuid": "u",
                        "parentUuid": None,
                        "message": {"role": "user", "content": "Run it"},
                    },
                    {
                        "type": "assistant",
                        "uuid": "a1",
                        "parentUuid": "u",
                        "message": {
                            "id": "m1",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "call_missing",
                                    "name": "Bash",
                                    "input": {"command": "false"},
                                }
                            ],
                        },
                    },
                    {
                        "type": "assistant",
                        "uuid": "a2",
                        "parentUuid": "a1",
                        "message": {
                            "id": "m2",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Continued without result"}],
                        },
                    },
                ],
            )

            strict_output = root / "strict.jsonl"
            strict_report = export_training_jsonl(source=root, output=strict_output)
            self.assertEqual(strict_report.samples_written, 0)
            self.assertEqual(strict_report.incomplete_segments_skipped, 1)

            generic_incomplete_output = root / "generic-incomplete.jsonl"
            generic_incomplete_report = export_training_jsonl(
                source=root,
                output=generic_incomplete_output,
                include_incomplete=True,
            )
            self.assertEqual(generic_incomplete_report.samples_written, 0)
            self.assertEqual(
                generic_incomplete_report.incomplete_segments_skipped, 1
            )

            permissive_output = root / "permissive.jsonl"
            permissive_report = export_training_jsonl(
                source=root,
                output=permissive_output,
                include_nonterminal_missing_tool_results=True,
            )
            sample = json.loads(permissive_output.read_text())
            self.assertEqual(permissive_report.samples_written, 1)
            self.assertEqual(
                permissive_report.nonterminal_missing_tool_results_samples_included,
                1,
            )
            self.assertEqual(
                sample["termination"]["reason"],
                "nonterminal_missing_tool_results_included",
            )

    def test_parallel_tools_are_one_assistant_turn_and_results_follow_call_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task, project, session_id = self.make_task(root)
            write_jsonl(
                project / f"{session_id}.jsonl",
                [
                    {
                        "type": "user",
                        "uuid": "u",
                        "parentUuid": None,
                        "message": {"role": "user", "content": "Inspect."},
                    },
                    {
                        "type": "assistant",
                        "uuid": "a1",
                        "parentUuid": "u",
                        "message": {
                            "id": "m",
                            "role": "assistant",
                            "content": [
                                {"type": "tool_use", "id": "call_1", "name": "Read", "input": {"path": "a"}}
                            ],
                        },
                    },
                    {
                        "type": "assistant",
                        "uuid": "a2",
                        "parentUuid": "a1",
                        "message": {
                            "id": "m",
                            "role": "assistant",
                            "content": [
                                {"type": "tool_use", "id": "call_2", "name": "Read", "input": {"path": "b"}}
                            ],
                        },
                    },
                    {
                        "type": "user",
                        "uuid": "r2",
                        "parentUuid": "a2",
                        "message": {
                            "role": "user",
                            "content": [{"type": "tool_result", "tool_use_id": "call_2", "content": "B"}],
                        },
                    },
                    {
                        "type": "user",
                        "uuid": "r1",
                        "parentUuid": "a1",
                        "message": {
                            "role": "user",
                            "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "A"}],
                        },
                    },
                    {
                        "type": "assistant",
                        "uuid": "done",
                        "parentUuid": "r2",
                        "message": {
                            "id": "done-message",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Done."}],
                        },
                    },
                    {
                        "type": "user",
                        "uuid": "late",
                        "parentUuid": "done",
                        "message": {"role": "user", "content": "<task-notification>late</task-notification>"},
                    },
                ],
            )
            output = root / "training.jsonl"
            export_training_jsonl(source=root, output=output, system_prompt="SYSTEM")
            sample = json.loads(output.read_text().splitlines()[0])
            assistant = sample["messages"][2]

            self.assertEqual(assistant["role"], "assistant")
            self.assertEqual([call["name"] for call in assistant["tool_calls"]], ["Read", "Read"])
            self.assertEqual(
                sample["messages"][3],
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "name": "Read",
                    "content": "OBSERVATION:\nA",
                },
            )
            self.assertEqual(
                sample["messages"][4],
                {
                    "role": "tool",
                    "tool_call_id": "call_2",
                    "name": "Read",
                    "content": "OBSERVATION:\nB",
                },
            )
            self.assertNotIn("late", json.dumps(sample))

    def test_precompact_segment_can_end_with_completed_tool_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task, project, session_id = self.make_task(root)
            write_jsonl(
                project / f"{session_id}.jsonl",
                [
                    {
                        "type": "user",
                        "uuid": "u1",
                        "parentUuid": None,
                        "message": {"role": "user", "content": "Inspect."},
                    },
                    {
                        "type": "assistant",
                        "uuid": "a1",
                        "parentUuid": "u1",
                        "message": {
                            "id": "m1",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "call_1",
                                    "name": "Read",
                                    "input": {"path": "a"},
                                }
                            ],
                        },
                    },
                    {
                        "type": "user",
                        "uuid": "r1",
                        "parentUuid": "a1",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "call_1",
                                    "content": "A",
                                }
                            ],
                        },
                    },
                    {
                        "type": "system",
                        "subtype": "compact_boundary",
                        "uuid": "c1",
                        "logicalParentUuid": "missing-logical-parent",
                    },
                    {
                        "type": "user",
                        "uuid": "u2",
                        "parentUuid": "c1",
                        "isCompactSummary": True,
                        "message": {"role": "user", "content": "Summary."},
                    },
                    {
                        "type": "assistant",
                        "uuid": "a2",
                        "parentUuid": "u2",
                        "message": {
                            "id": "m2",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Continue."}],
                        },
                    },
                ],
            )

            output = root / "training.jsonl"
            report = export_training_jsonl(source=root, output=output, system_prompt="SYSTEM")
            samples = [json.loads(line) for line in output.read_text().splitlines()]

            self.assertEqual(report.samples_written, 2)
            precompact = next(
                sample for sample in samples if sample["id"].endswith("segment-001")
            )
            self.assertEqual(
                precompact["messages"][-1],
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "name": "Read",
                    "content": "OBSERVATION:\nA",
                },
            )

    def test_tool_error_is_preserved_in_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task, project, session_id = self.make_task(root)
            write_jsonl(
                project / f"{session_id}.jsonl",
                [
                    {"type": "user", "uuid": "u", "message": {"role": "user", "content": "Run."}},
                    {
                        "type": "assistant",
                        "uuid": "a",
                        "parentUuid": "u",
                        "message": {
                            "id": "m",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "call_1",
                                    "name": "Bash",
                                    "input": {"command": "false"},
                                }
                            ],
                        },
                    },
                    {
                        "type": "user",
                        "uuid": "r",
                        "parentUuid": "a",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "call_1",
                                    "content": "exit status 1",
                                    "is_error": True,
                                }
                            ],
                        },
                    },
                ],
            )
            output = root / "training.jsonl"
            export_training_jsonl(source=root, output=output, system_prompt="SYSTEM")
            sample = json.loads(output.read_text().splitlines()[0])
            self.assertEqual(
                sample["messages"][-1],
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "name": "Bash",
                    "content": "ERROR:\nexit status 1",
                },
            )

    def test_runtime_state_is_injected_into_system_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task, project, session_id = self.make_task(root)
            write_jsonl(
                project / f"{session_id}.jsonl",
                [
                    {
                        "type": "user",
                        "uuid": "u",
                        "parentUuid": None,
                        "message": {"role": "user", "content": "Task"},
                    },
                    {
                        "type": "assistant",
                        "uuid": "a",
                        "parentUuid": "u",
                        "message": {
                            "id": "m",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Answer"}],
                        },
                    },
                ],
            )
            debug = project.parents[1] / "debug" / f"{session_id}.txt"
            debug.parent.mkdir(parents=True)
            payload = "Hook SessionStart:startup (SessionStart) success:\nphase: searching"
            debug.write_text(
                f"2026-01-01T00:00:00Z [DEBUG] {json.dumps(payload)}\n",
                encoding="utf-8",
            )
            output = root / "training.jsonl"
            export_training_jsonl(source=root, output=output, system_prompt="SYSTEM")
            sample = json.loads(output.read_text().splitlines()[0])
            self.assertEqual(sample["messages"][0]["content"], "SYSTEM")

            output_with_state = root / "training-with-runtime-state.jsonl"
            export_training_jsonl(
                source=root,
                output=output_with_state,
                system_prompt="SYSTEM",
                include_runtime_state=True,
            )
            sample = json.loads(output_with_state.read_text().splitlines()[0])
            self.assertIn("[RUNTIME_STATE]", sample["messages"][0]["content"])
            self.assertIn("phase: searching", sample["messages"][0]["content"])

    def test_drop_observer_keeps_non_observer_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _task, project, session_id = self.make_task(root)
            write_jsonl(
                project / f"{session_id}.jsonl",
                [
                    {"type": "user", "uuid": "u", "message": {"role": "user", "content": "Task"}},
                    {
                        "type": "assistant",
                        "uuid": "a",
                        "parentUuid": "u",
                        "message": {
                            "id": "m",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Answer"}],
                        },
                    },
                ],
            )
            debug = project.parents[1] / "debug" / f"{session_id}.txt"
            debug.parent.mkdir(parents=True)
            payload = (
                "Hook SessionStart:startup (SessionStart) success:\n"
                "## Current State\nphase: searching\n\n"
                "## Observer\nObserver Advisory\nuse this only as a hint"
            )
            debug.write_text(
                f"2026-01-01T00:00:00Z [DEBUG] {json.dumps(payload)}\n",
                encoding="utf-8",
            )
            output = root / "training.jsonl"
            export_training_jsonl(
                source=root,
                output=output,
                system_prompt="SYSTEM",
                include_runtime_state=True,
                drop_observer=True,
            )
            system = json.loads(output.read_text().splitlines()[0])["messages"][0]["content"]
            self.assertIn("phase: searching", system)
            self.assertNotIn("Observer Advisory", system)

    def test_failed_task_is_included_by_default_and_success_only_is_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, project, session_id = self.make_task(root)
            (task / "final_status.json").write_text(
                json.dumps({"task_id": "arvo:1", "status": "failed"}),
                encoding="utf-8",
            )
            write_jsonl(
                project / f"{session_id}.jsonl",
                [
                    {"type": "user", "uuid": "u", "message": {"role": "user", "content": "Task"}},
                    {
                        "type": "assistant",
                        "uuid": "a",
                        "parentUuid": "u",
                        "message": {
                            "id": "m",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Attempt"}],
                        },
                    },
                ],
            )
            output = root / "training.jsonl"
            report = export_training_jsonl(source=root, output=output)
            self.assertEqual(report.samples_written, 1)

            success_output = root / "success-only.jsonl"
            success_report = export_training_jsonl(
                source=root, output=success_output, success_only=True
            )
            self.assertEqual(success_report.tasks_skipped, 1)
            self.assertEqual(success_output.read_text(), "")

    def test_hanxueming_success_only_uses_result_log_last_submit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, project, session_id = self.make_hanxueming_task(root)
            task.mkdir(parents=True)
            (task / "final_status.json").write_text(
                json.dumps({"task_id": "arvo:42", "status": "failed"}),
                encoding="utf-8",
            )
            write_jsonl(
                project / f"{session_id}.jsonl",
                [
                    {
                        "type": "user",
                        "uuid": "u",
                        "message": {"role": "user", "content": "Task"},
                    },
                    {
                        "type": "assistant",
                        "uuid": "a",
                        "parentUuid": "u",
                        "message": {
                            "id": "m",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Attempt"}],
                        },
                    },
                ],
            )
            result_log = (
                root
                / "node0"
                / "worker1"
                / "result"
                / "arvo_42_deadbeef.log"
            )
            result_log.parent.mkdir(parents=True)
            result_log.write_text(
                '{"vul_exit_code": 139, "fix_exit_code": 0}\n',
                encoding="utf-8",
            )

            correct_output = root / "correct.jsonl"
            correct_report = export_training_jsonl(
                source=root,
                output=correct_output,
                layout="hanxueming",
                success_only=True,
            )
            self.assertEqual(correct_report.samples_written, 1)
            self.assertEqual(correct_report.tasks_eligible, 1)
            self.assertEqual(correct_report.tasks_with_samples, 1)
            self.assertNotEqual(correct_output.read_text(), "")
            correct_report_data = json.loads(
                correct_output.with_suffix(".jsonl.report.json").read_text()
            )
            self.assertTrue(correct_report_data["success_only"])
            self.assertEqual(correct_report_data["successful_tasks_selected"], 1)
            self.assertEqual(
                correct_report_data["sample_type_counts"],
                {"main": 1, "subagent": 0, "context_compaction": 0},
            )

            # print_result.py keeps the last result whose vul_exit_code is not
            # zero. A later failed fix therefore makes this task unsuccessful.
            result_log.write_text(
                '{"vul_exit_code": 139, "fix_exit_code": 0}\n'
                '{"vul_exit_code": 139, "fix_exit_code": 1}\n',
                encoding="utf-8",
            )
            failed_output = root / "failed.jsonl"
            failed_report = export_training_jsonl(
                source=root,
                output=failed_output,
                layout="hanxueming",
                success_only=True,
            )
            self.assertEqual(failed_report.tasks_skipped, 1)
            self.assertEqual(failed_report.samples_written, 0)
            self.assertEqual(failed_output.read_text(), "")
            self.assertTrue(
                any(
                    "status=vul_crashed_fix_failed" in warning
                    for warning in failed_report.warnings
                )
            )

            # print_result.py removes vul_exit_code=0 rows and, when no rows
            # remain, treats the result as (0, 0): the vulnerability did not
            # crash, so this is not a successful training task.
            result_log.write_text(
                '{"vul_exit_code": 0, "fix_exit_code": 0}\n',
                encoding="utf-8",
            )
            no_crash_output = root / "no-crash.jsonl"
            no_crash_report = export_training_jsonl(
                source=root,
                output=no_crash_output,
                layout="hanxueming",
                success_only=True,
            )
            self.assertEqual(no_crash_report.samples_written, 0)
            self.assertTrue(
                any(
                    "status=vul_not_crashed" in warning
                    for warning in no_crash_report.warnings
                )
            )

            result_log.unlink()
            missing_output = root / "missing-result.jsonl"
            missing_report = export_training_jsonl(
                source=root,
                output=missing_output,
                layout="hanxueming",
                success_only=True,
            )
            self.assertEqual(missing_report.samples_written, 0)
            self.assertTrue(
                any(
                    "status=missing_result_log" in warning
                    for warning in missing_report.warnings
                )
            )

    def test_hanxueming_layout_discovers_tasks_runtime_and_thinking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, project, session_id = self.make_hanxueming_task(root)
            write_jsonl(
                project / f"{session_id}.jsonl",
                [
                    {
                        "type": "user",
                        "uuid": "u",
                        "message": {"role": "user", "content": "Task"},
                    },
                    {
                        "type": "assistant",
                        "uuid": "a",
                        "parentUuid": "u",
                        "message": {
                            "id": "m",
                            "role": "assistant",
                            "content": [
                                {"type": "thinking", "thinking": "Inspect first."},
                                {"type": "text", "text": "Answer"},
                            ],
                        },
                    },
                ],
            )
            subagents = project / session_id / "subagents"
            write_jsonl(subagents / "agent-acompact-ignore.jsonl", [])
            debug = task / "logs" / "debug" / f"{session_id}.txt"
            debug.parent.mkdir(parents=True)
            payload = "Hook SessionStart:startup (SessionStart) success:\nphase: searching"
            debug.write_text(
                f"2026-01-01T00:00:00Z [DEBUG] {json.dumps(payload)}\n",
                encoding="utf-8",
            )
            (root / "node0" / "worker1" / "logs" / "arvo_99-no-session").mkdir(
                parents=True
            )

            output = root / "training.jsonl"
            report = export_training_jsonl(
                source=root, output=output, include_runtime_state=True
            )
            sample = json.loads(output.read_text().splitlines()[0])

            self.assertEqual(report.layout, "hanxueming")
            self.assertEqual(report.tasks_seen, 2)
            self.assertEqual(report.tasks_skipped, 1)
            self.assertEqual(report.tasks_without_sessions, 1)
            self.assertEqual(report.compact_agents_included, 1)
            self.assertTrue(sample["id"].startswith("arvo_42-han-session-main"))
            self.assertIn("phase: searching", sample["messages"][0]["content"])
            self.assertEqual(sample["messages"][2]["reasoning_content"], "Inspect first.")


if __name__ == "__main__":
    unittest.main()
