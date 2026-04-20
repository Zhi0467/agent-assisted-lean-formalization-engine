from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lean_formalization_engine.subprocess_agent import (
    ProviderResponseError,
    SubprocessFormalizationAgent,
    _default_agent_name,
)


def _make_completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> CompletedProcess:
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestSubprocessAgentConstruction(unittest.TestCase):
    def test_empty_command_raises_value_error(self):
        with self.assertRaises(ValueError):
            SubprocessFormalizationAgent([])

    def test_name_defaults_to_default_agent_name(self):
        agent = SubprocessFormalizationAgent(["echo"])
        self.assertEqual(agent.name, _default_agent_name(["echo"]))

    def test_explicit_name_is_preserved(self):
        agent = SubprocessFormalizationAgent(["echo"], name="my-agent")
        self.assertEqual(agent.name, "my-agent")

    def test_working_directory_stored(self):
        wd = Path("/tmp")
        agent = SubprocessFormalizationAgent(["echo"], working_directory=wd)
        self.assertEqual(agent.working_directory, wd)


class TestDefaultAgentName(unittest.TestCase):
    def test_python_m_form(self):
        self.assertEqual(_default_agent_name(["python", "-m", "mymodule"]), "subprocess:mymodule")

    def test_python_c_form(self):
        self.assertEqual(_default_agent_name(["python", "-c"]), "subprocess:python-inline")

    def test_generic_executable(self):
        self.assertEqual(_default_agent_name(["my-provider"]), "subprocess:my-provider")

    def test_path_executable_uses_basename(self):
        self.assertEqual(_default_agent_name(["/usr/bin/my-tool"]), "subprocess:my-tool")

    def test_python_with_script(self):
        self.assertEqual(
            _default_agent_name(["python", "script.py"]), "subprocess:script.py"
        )


class TestProviderResponseError(unittest.TestCase):
    def test_is_value_error(self):
        err = ProviderResponseError("oops")
        self.assertIsInstance(err, ValueError)

    def test_response_text_attribute(self):
        err = ProviderResponseError("msg", response_text="raw output")
        self.assertEqual(err.response_text, "raw output")

    def test_provider_payload_attribute(self):
        payload = {"key": "val"}
        err = ProviderResponseError("msg", provider_payload=payload)
        self.assertEqual(err.provider_payload, payload)

    def test_defaults(self):
        err = ProviderResponseError("msg")
        self.assertEqual(err.response_text, "")
        self.assertIsNone(err.provider_payload)


class TestInvokeProvider(unittest.TestCase):
    def _agent(self) -> SubprocessFormalizationAgent:
        return SubprocessFormalizationAgent(["fake-cmd"])

    def test_nonzero_exit_code_raises_runtime_error(self):
        agent = self._agent()
        with patch("subprocess.run", return_value=_make_completed(stderr="err", returncode=1)):
            with self.assertRaises(RuntimeError) as ctx:
                agent._invoke_provider({}, stage_label="enrichment")
        self.assertIn("exited with code 1", str(ctx.exception))
        self.assertIn("enrichment", str(ctx.exception))

    def test_nonzero_includes_stderr_in_message(self):
        agent = self._agent()
        with patch("subprocess.run", return_value=_make_completed(stderr="something broke", returncode=2)):
            with self.assertRaises(RuntimeError) as ctx:
                agent._invoke_provider({}, stage_label="plan")
        self.assertIn("something broke", str(ctx.exception))

    def test_missing_command_raises_runtime_error(self):
        agent = self._agent()
        with patch("subprocess.run", side_effect=FileNotFoundError("no such file")):
            with self.assertRaises(RuntimeError) as ctx:
                agent._invoke_provider({}, stage_label="proof")
        self.assertIn("fake-cmd", str(ctx.exception))

    def test_invalid_json_response_raises_provider_error(self):
        agent = self._agent()
        with patch("subprocess.run", return_value=_make_completed(stdout="not-json")):
            with self.assertRaises(ProviderResponseError) as ctx:
                agent._invoke_provider({}, stage_label="review")
        self.assertIn("invalid JSON", str(ctx.exception))

    def test_valid_json_dict_returned(self):
        agent = self._agent()
        payload = {"prompt": "do something", "raw_response": "ok"}
        with patch("subprocess.run", return_value=_make_completed(stdout=json.dumps(payload))):
            result = agent._invoke_provider({}, stage_label="enrichment")
        self.assertEqual(result["prompt"], "do something")

    def test_progress_callback_receives_heartbeat_for_long_provider_run(self):
        agent = SubprocessFormalizationAgent(["fake-cmd"], heartbeat_interval_seconds=0.01)
        events: list[tuple[str, str, dict[str, object] | None]] = []

        def slow_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            time.sleep(0.03)
            return _make_completed(stdout=json.dumps({"prompt": "ok", "raw_response": "done"}))

        with patch("lean_formalization_engine.subprocess_agent.subprocess.run", side_effect=slow_run):
            agent._invoke_provider(
                {},
                stage_label="proof",
                progress_callback=lambda event_type, summary, details=None: events.append(
                    (event_type, summary, details)
                ),
            )

        event_types = [event_type for event_type, _, _ in events]
        self.assertIn("backend_process_started", event_types)
        self.assertIn("backend_process_heartbeat", event_types)
        self.assertIn("backend_process_completed", event_types)


class TestRunStage(unittest.TestCase):
    def _agent(self) -> SubprocessFormalizationAgent:
        return SubprocessFormalizationAgent(["fake-cmd"])

    def _make_request(self):
        from lean_formalization_engine.models import BackendStage, StageRequest

        return StageRequest(
            stage=BackendStage.ENRICHMENT,
            run_id="test-run",
            repo_root="/tmp/repo",
            run_dir="/tmp/repo/artifacts/runs/test-run",
            output_dir="/tmp/repo/artifacts/runs/test-run/01_enrichment",
            input_paths={},
            required_outputs=[],
        )

    def test_non_dict_json_raises_provider_error(self):
        agent = self._agent()
        request = self._make_request()
        with patch("subprocess.run", return_value=_make_completed(stdout=json.dumps([1, 2, 3]))):
            with self.assertRaises(ProviderResponseError) as ctx:
                agent.run_stage(request)
        self.assertIn("non-object", str(ctx.exception))

    def test_missing_prompt_raises_provider_error(self):
        agent = self._agent()
        request = self._make_request()
        payload = {"raw_response": "something", "no_prompt": True}
        with patch("subprocess.run", return_value=_make_completed(stdout=json.dumps(payload))):
            with self.assertRaises(ProviderResponseError) as ctx:
                agent.run_stage(request)
        self.assertIn("prompt", str(ctx.exception))

    def test_valid_response_returns_agent_turn(self):
        from lean_formalization_engine.models import AgentTurn

        agent = self._agent()
        request = self._make_request()
        payload = {"prompt": "the prompt", "raw_response": "the response"}
        with patch("subprocess.run", return_value=_make_completed(stdout=json.dumps(payload))):
            turn = agent.run_stage(request)
        self.assertIsInstance(turn, AgentTurn)
        self.assertEqual(turn.prompt, "the prompt")
        self.assertEqual(turn.raw_response, "the response")

    def test_missing_raw_response_falls_back_to_full_payload(self):
        from lean_formalization_engine.models import AgentTurn

        agent = self._agent()
        request = self._make_request()
        payload = {"prompt": "the prompt"}
        with patch("subprocess.run", return_value=_make_completed(stdout=json.dumps(payload))):
            turn = agent.run_stage(request)
        self.assertIsInstance(turn, AgentTurn)
        # raw_response should be the JSON-dumped payload when key is absent
        parsed = json.loads(turn.raw_response)
        self.assertEqual(parsed["prompt"], "the prompt")


if __name__ == "__main__":
    unittest.main()
