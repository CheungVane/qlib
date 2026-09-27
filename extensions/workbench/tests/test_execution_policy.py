"""T04 / A41: execution policy validation and resource-limit capability probing."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from quant_workbench import execution_policy as ep
from quant_workbench.adapters.executors import SubprocessExecutor

REPO_ROOT = Path(__file__).resolve().parents[3]


class PolicyLoadingTests(unittest.TestCase):
    def test_shipped_policy_loads_with_explicit_numbers(self):
        policy = ep.load_policy()
        self.assertGreater(policy.max_concurrent, 0)
        self.assertGreater(policy.timeout_seconds, 0)
        self.assertGreater(policy.terminate_grace_seconds, 0)
        self.assertGreater(policy.cpu_seconds, 0)
        self.assertGreater(policy.memory_bytes, 0)
        self.assertIn("cpu", policy.enforce)
        self.assertGreater(policy.agent_max_trials, 0)
        self.assertGreater(policy.agent_max_calls, 0)

    def test_revision_is_stable_and_content_sensitive(self):
        policy = ep.load_policy()
        self.assertEqual(policy.revision(), ep.load_policy().revision())
        changed = ep.ExecutionPolicy(
            max_concurrent=policy.max_concurrent + 1, timeout_seconds=policy.timeout_seconds,
            terminate_grace_seconds=policy.terminate_grace_seconds,
            cpu_seconds=policy.cpu_seconds, memory_bytes=policy.memory_bytes,
            enforce=policy.enforce, agent_max_trials=policy.agent_max_trials,
            agent_max_calls=policy.agent_max_calls, agent_scope=policy.agent_scope)
        self.assertNotEqual(policy.revision(), changed.revision())

    def write(self, folder: str, payload: dict) -> Path:
        path = Path(folder) / "policy.json"
        path.write_text(json.dumps(payload))
        return path

    def base(self) -> dict:
        return json.loads(ep.DEFAULT_POLICY_PATH.read_text())

    def test_missing_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ep.PolicyError):
                ep.load_policy(Path(folder) / "absent.json")

    def test_invalid_numbers_fail_closed(self):
        for key, bad in (("max_concurrent", 0), ("timeout_seconds", -5), ("cpu_seconds", True),
                         ("terminate_grace_seconds", "10"), ("memory_bytes", None)):
            with self.subTest(key=key):
                payload = self.base()
                payload[key] = bad
                with tempfile.TemporaryDirectory() as folder:
                    with self.assertRaises(ep.PolicyError):
                        ep.load_policy(self.write(folder, payload))

    def test_enforce_must_be_an_explicit_list(self):
        for bad in ([], ["gpu"], "cpu", None):
            with self.subTest(bad=bad):
                payload = self.base()
                payload["enforce"] = bad
                with tempfile.TemporaryDirectory() as folder:
                    with self.assertRaises(ep.PolicyError):
                        ep.load_policy(self.write(folder, payload))

    def test_agent_budget_must_be_explicit(self):
        payload = self.base()
        payload["agent_budget"] = {"max_trials": 0, "max_calls": 10}
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ep.PolicyError):
                ep.load_policy(self.write(folder, payload))


class CapabilityTests(unittest.TestCase):
    def test_unsupported_limits_names_every_unenforceable_requirement(self):
        policy = ep.load_policy()
        memory_required = ep.ExecutionPolicy(
            max_concurrent=policy.max_concurrent, timeout_seconds=policy.timeout_seconds,
            terminate_grace_seconds=policy.terminate_grace_seconds,
            cpu_seconds=policy.cpu_seconds, memory_bytes=policy.memory_bytes,
            enforce=("cpu", "memory"), agent_max_trials=policy.agent_max_trials,
            agent_max_calls=policy.agent_max_calls, agent_scope=policy.agent_scope)
        caps = {"cpu": True, "memory": False}
        self.assertEqual(ep.unsupported_limits(memory_required, caps), ["memory"])
        self.assertEqual(ep.unsupported_limits(policy, caps), [])
        self.assertEqual(ep.unsupported_limits(policy, {"cpu": False, "memory": False}), ["cpu"])

    def test_child_limits_follow_the_enforce_list(self):
        policy = ep.load_policy()
        cpu_only = {(k, v) for k, v in ep.child_limits(policy).items()}
        self.assertIn("cpu_seconds", {name for name, _ in cpu_only})
        self.assertNotIn("memory_bytes", {name for name, _ in cpu_only})
        with_memory = ep.ExecutionPolicy(
            max_concurrent=policy.max_concurrent, timeout_seconds=policy.timeout_seconds,
            terminate_grace_seconds=policy.terminate_grace_seconds,
            cpu_seconds=policy.cpu_seconds, memory_bytes=policy.memory_bytes,
            enforce=("cpu", "memory"), agent_max_trials=policy.agent_max_trials,
            agent_max_calls=policy.agent_max_calls, agent_scope=policy.agent_scope)
        self.assertEqual(ep.child_limits(with_memory)["memory_bytes"],
                         (policy.memory_bytes, policy.memory_bytes))

    def test_probe_reports_real_booleans_and_limit_profile_is_explicit(self):
        capabilities = ep.probe_enforcement()
        self.assertIsInstance(capabilities["cpu"], bool)
        self.assertIsInstance(capabilities["memory"], bool)
        profile = ep.load_policy().limit_profile()
        self.assertEqual(profile["enforced"], ["cpu"])
        self.assertIn("memory", profile["unenforced"])


class ChildLimitEnforcementTests(unittest.TestCase):
    """The declared CPU cap must actually kill a runaway child, not just be written down."""

    def test_cpu_limit_is_injected_into_the_wrapper(self):
        with tempfile.TemporaryDirectory() as folder:
            executor = SubprocessExecutor(repo_root=REPO_ROOT, limits={"cpu_seconds": (1, 1)})
            prepared = {
                "workspace": folder, "log_path": f"{folder}/out.log",
                "exit_marker": f"{folder}/exit_code", "cwd": folder,
                "command": [sys.executable, "-c", "while True: pass"],
                "env": dict(os.environ),
            }
            executor.start("attempt-cpu", prepared)
            state, code = None, None
            started_at = time.time()
            deadline = time.time() + 25
            while time.time() < deadline:
                polled = executor.poll({"attempt_id": "attempt-cpu", "workspace": folder})
                if polled.get("exit_code") is not None or polled.get("state") in ("interrupted",):
                    state, code = polled.get("state"), polled.get("exit_code")
                    break
                time.sleep(0.2)
            self.assertIsNotNone(state, "runaway child was not stopped by the injected limit")
            # The wrapper shell itself receives SIGXCPU, so it never writes the exit marker:
            # the limit is enforced, but the kill currently surfaces as interrupted without an
            # exit code. Classifying it as failed/resource_limit still needs signal plumbing.
            self.assertEqual(state, "interrupted")
            self.assertIsNone(code)
            self.assertLess(time.time() - started_at, 20, "limit did not stop the child promptly")
            self.assertFalse(Path(f"{folder}/exit_code").exists())

    def test_no_limit_means_no_ulimit_preamble(self):
        with tempfile.TemporaryDirectory() as folder:
            executor = SubprocessExecutor(repo_root=REPO_ROOT)
            prepared = {
                "workspace": folder, "log_path": f"{folder}/out.log",
                "exit_marker": f"{folder}/exit_code", "cwd": folder,
                "command": [sys.executable, "-c", "print('ok')"], "env": dict(os.environ),
            }
            executor.start("attempt-plain", prepared)
            time.sleep(0.5)
            self.assertNotIn("ulimit", Path(f"{folder}/out.log").read_text())


if __name__ == "__main__":
    unittest.main()
