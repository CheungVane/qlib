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

try:  # works under both `unittest discover -s tests` and `-m unittest tests.*`
    from tests.sandbox import isolated_repo_root
except ImportError:
    from sandbox import isolated_repo_root  # type: ignore[no-redef]


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
        # The shipped policy now enforces both, so a missing memory capability is a blocker.
        self.assertEqual(ep.unsupported_limits(policy, caps), ["memory"])
        self.assertEqual(ep.unsupported_limits(policy, {"cpu": True, "memory": True}), [])
        self.assertEqual(ep.unsupported_limits(policy, {"cpu": False, "memory": False}),
                         ["cpu", "memory"])

    def test_child_limits_follow_the_enforce_list(self):
        policy = ep.load_policy()
        self.assertEqual(set(ep.child_limits(policy)), {"cpu_seconds", "memory_bytes"})
        cpu_only = ep.ExecutionPolicy(
            max_concurrent=policy.max_concurrent, timeout_seconds=policy.timeout_seconds,
            terminate_grace_seconds=policy.terminate_grace_seconds,
            cpu_seconds=policy.cpu_seconds, memory_bytes=policy.memory_bytes,
            enforce=("cpu",), agent_max_trials=policy.agent_max_trials,
            agent_max_calls=policy.agent_max_calls, agent_scope=policy.agent_scope)
        self.assertEqual(set(ep.child_limits(cpu_only)), {"cpu_seconds"})
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
        # T04 container route: both limits are mandatory, so a route that cannot apply them
        # has to refuse admission (the executor precondition checks carry that refusal).
        self.assertEqual(profile["enforced"], ["cpu", "memory"])
        self.assertEqual(profile["unenforced"], [])
        self.assertEqual(ep.container_limits(ep.load_policy()),
                         [f"--memory={ep.load_policy().memory_bytes}b",
                          f"--memory-swap={ep.load_policy().memory_bytes}b",
                          f"--ulimit=cpu={ep.load_policy().cpu_seconds}:{ep.load_policy().cpu_seconds}"])


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
            # The limit is enforced either way; the classification depends on whether the wrapper
            # shell survives long enough to write the marker (see the spec note).
            self.assertIn(state, ("failed", "interrupted"))
            self.assertLess(time.time() - started_at, 20, "limit did not stop the child promptly")
            marker_path = Path(f"{folder}/exit_code")
            if state == "failed":
                self.assertEqual(polled.get("error_code"), "resource_limit")
                self.assertEqual(marker_path.read_text().strip(), "resource_limit")
            else:
                self.assertFalse(marker_path.exists(),
                                 "a lost-process classification must not carry a marker")

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


class ConcurrencyAdmissionTests(unittest.TestCase):
    """EXEC13 / A41: slots are bounded and a full service refuses new work (409)."""

    def setUp(self):
        try:  # works under both `unittest discover -s tests` and `-m unittest tests.*`
            from tests.test_execution import StubExecutor
        except ImportError:
            from test_execution import StubExecutor  # type: ignore[no-redef]
        from quant_workbench.execution import ExecutionService
        from quant_workbench.storage import LocalResultRepository

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = isolated_repo_root(self.tmp.name)
        self.repo = LocalResultRepository(root)
        policy = ep.ExecutionPolicy(
            max_concurrent=1, timeout_seconds=60, terminate_grace_seconds=2, cpu_seconds=60,
            memory_bytes=1 << 30, enforce=("cpu",), agent_max_trials=2, agent_max_calls=10,
            agent_scope="policy_revision")
        self.service = ExecutionService(self.repo, executors=[StubExecutor(root)], policy=policy)

    def tearDown(self):
        for attempt in self.repo.list_open_attempts():
            try:
                self.service.cancel(attempt["attempt_id"])
            except Exception:
                pass

    def submit(self, key, seconds="30"):
        return self.service.submit("stub.sleep", {"seconds": seconds}, idempotency_key=key)

    def test_second_submit_is_refused_while_the_slot_is_taken(self):
        from quant_workbench.execution import CapacityExceeded

        first = self.submit("k1")
        self.assertEqual(first["attempt"]["status"], "running")
        with self.assertRaises(CapacityExceeded) as raised:
            self.submit("k2")
        self.assertEqual(raised.exception.code, "capacity_exceeded")
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(len(self.repo.list_open_attempts()), 1, "refusal must not create an attempt")

    def test_cancelling_releases_the_slot(self):
        first = self.submit("k1")
        self.service.cancel(first["attempt"]["attempt_id"])
        self.assertEqual(self.repo.list_open_attempts(), [])
        second = self.submit("k2", seconds="0")
        self.assertEqual(second["attempt"]["status"], "running")

    def test_idempotent_replay_still_works_when_full(self):
        first = self.submit("k1")
        again = self.service.submit("stub.sleep", {"seconds": "30"}, idempotency_key="k1")
        self.assertFalse(again["created"])
        self.assertEqual(again["attempt"]["attempt_id"], first["attempt"]["attempt_id"])

    def test_deadline_is_enforced_and_confirmed_as_timeout(self):
        from datetime import datetime, timedelta, timezone

        first = self.submit("k1")
        attempt_id = first["attempt"]["attempt_id"]
        started = datetime.fromisoformat(first["attempt"]["created_at"].replace("Z", "+00:00"))
        # not yet due
        early = (started + timedelta(seconds=0.5)).isoformat().replace("+00:00", "Z")
        self.assertEqual(self.service.enforce_timeouts(now=early)["timed_out"], [])
        # past the 1s deadline in the injected policy? the stub policy allows 60s, so force one
        late = (started + timedelta(seconds=90)).isoformat().replace("+00:00", "Z")
        result = self.service.enforce_timeouts(now=late)
        self.assertEqual(len(result["timed_out"]), 1)
        row = self.repo.get_attempt(attempt_id)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error_code"], "timeout")
        self.assertIn("deadline", row["error_message"])

    def test_completed_attempts_are_not_retroactively_timed_out(self):
        from datetime import datetime, timedelta

        finished = self.submit("k0", seconds="0")
        attempt_id = finished["attempt"]["attempt_id"]
        row = None
        for _ in range(40):
            self.service.reconcile([attempt_id])
            row = self.repo.get_attempt(attempt_id)
            if row["status"] != "running":
                break
            time.sleep(0.25)
        self.assertEqual(row["status"], "succeeded")
        late = (datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                + timedelta(seconds=600)).isoformat().replace("+00:00", "Z")
        self.service.enforce_timeouts(now=late)
        self.assertEqual(self.repo.get_attempt(row["attempt_id"])["status"], "succeeded")


class AgentBudgetTests(unittest.TestCase):
    """EXEC13 / A41: Agent trials are reserved before launch and blocked at the limit."""

    def setUp(self):
        try:
            from tests.test_execution import StubExecutor
        except ImportError:
            from test_execution import StubExecutor  # type: ignore[no-redef]
        from quant_workbench.execution import ExecutionService
        from quant_workbench.storage import LocalResultRepository

        class AgentStub(StubExecutor):
            kinds = ("rdagent.factor.baseline",)

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = isolated_repo_root(self.tmp.name)
        self.repo = LocalResultRepository(root)
        self.policy = ep.ExecutionPolicy(
            max_concurrent=5, timeout_seconds=60, terminate_grace_seconds=2, cpu_seconds=60,
            memory_bytes=1 << 30, enforce=("cpu",), agent_max_trials=2, agent_max_calls=10,
            agent_scope="policy_revision")
        self.executors = [AgentStub(root)]
        self.service = ExecutionService(self.repo, executors=self.executors, policy=self.policy)

    def tearDown(self):
        for attempt in self.repo.list_open_attempts():
            try:
                self.service.cancel(attempt["attempt_id"])
            except Exception:
                pass

    def submit(self, key):
        return self.service.submit("rdagent.factor.baseline", {}, idempotency_key=key)

    def test_trial_budget_blocks_the_next_call_and_survives_cancel(self):
        from quant_workbench.execution import BudgetExhausted, ExecutionService

        self.submit("b1")
        self.submit("b2")
        with self.assertRaises(BudgetExhausted) as raised:
            self.submit("b3")
        self.assertEqual(raised.exception.code, "budget_exhausted")
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(len(self.repo.list_open_attempts()), 2, "refusal must not create an attempt")
        # cancelling does not clear the ledger
        for attempt in self.repo.list_open_attempts():
            self.service.cancel(attempt["attempt_id"])
        with self.assertRaises(BudgetExhausted):
            self.submit("b4")
        # a restarted service over the same repository still sees the same ledger
        restarted = ExecutionService(self.repo, executors=self.executors, policy=self.policy)
        with self.assertRaises(BudgetExhausted):
            restarted.submit("rdagent.factor.baseline", {}, idempotency_key="b5")
        rows = self.repo.agent_budget_rows(self.policy.revision())
        self.assertEqual([dict(row) for row in rows][0]["used"], 2)

    def test_deadline_and_policy_revision_are_persisted(self):
        from datetime import datetime, timedelta

        from quant_workbench.execution import ExecutionService

        first = self.submit("p1")
        row = self.repo.get_attempt(first["attempt"]["attempt_id"])
        self.assertEqual(row["policy_revision"], self.policy.revision())
        self.assertIsNotNone(row["deadline_at"])
        stored = datetime.fromisoformat(row["deadline_at"].replace("Z", "+00:00"))
        started = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
        self.assertAlmostEqual((stored - started).total_seconds(),
                               self.policy.timeout_seconds, delta=2)
        # a policy change after the fact must NOT move an already-frozen deadline
        other = ep.ExecutionPolicy(
            max_concurrent=5, timeout_seconds=100000, terminate_grace_seconds=2, cpu_seconds=60,
            memory_bytes=1 << 30, enforce=("cpu",), agent_max_trials=2, agent_max_calls=10,
            agent_scope="policy_revision")
        switched = ExecutionService(self.repo, executors=self.executors, policy=other)
        switched.enforce_timeouts(now=(started + timedelta(seconds=self.policy.timeout_seconds + 5))
                                 .isoformat().replace("+00:00", "Z"))
        after = self.repo.get_attempt(first["attempt"]["attempt_id"])
        self.assertEqual(after["error_code"], "timeout")

    def test_policy_summary_reports_limits_and_usage(self):
        summary = self.service.policy_summary()
        self.assertTrue(summary["available"])
        self.assertEqual(summary["max_concurrent"], 5)
        self.assertEqual(summary["unenforced"], ["memory"])  # this fixture policy enforces cpu only
        self.assertFalse(summary["agent"]["calls_enforced"])
        self.submit("s1")
        self.assertEqual(self.service.policy_summary()["agent"]["used"]["trials"], 1)

    def test_non_agent_kinds_do_not_consume_the_agent_trial_budget(self):
        try:
            from tests.test_execution import StubExecutor
        except ImportError:
            from test_execution import StubExecutor  # type: ignore[no-redef]
        from quant_workbench.execution import ExecutionService

        root = isolated_repo_root(self.tmp.name)
        service = ExecutionService(self.repo, executors=[StubExecutor(root)], policy=self.policy)
        service.submit("stub.exit", {"script": "exit 0"}, idempotency_key="plain1")
        self.assertEqual(self.repo.agent_budget_rows(self.policy.revision()), [])


if __name__ == "__main__":
    unittest.main()
