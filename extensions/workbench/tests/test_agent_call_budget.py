"""EXEC13 / T04: agent call counting and enforcement, without touching RD-Agent's source.

The hook is injected through PYTHONPATH + sitecustomize, so these tests run a real child
interpreter with a fake `litellm` module: that is the whole mechanism under test, and it needs
neither RD-Agent nor a network call.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from quant_workbench.adapters.executors import (
    AGENT_BUDGET_HOOK_DIR, CONTAINER_AGENT_DIR, CONTAINER_HOOK_DIR, CONTAINER_PLATFORM_DIR,
    CONTAINER_REPO_DIR, RDAgentExecutor,
)
from quant_workbench.execution import ExecutionService
from quant_workbench.execution_policy import agent_limits, child_limits, load_policy
from quant_workbench.storage import LocalResultRepository

try:  # works under both `unittest discover -s tests` and `-m unittest tests.*`
    from tests.sandbox import isolated_repo_root
    from tests.test_execution import StubExecutor
except ImportError:
    from sandbox import isolated_repo_root  # type: ignore[no-redef]
    from test_execution import StubExecutor  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[3]


def load_helper():
    spec = importlib.util.spec_from_file_location(
        "qwb_agent_budget_under_test", AGENT_BUDGET_HOOK_DIR / "qwb_agent_budget.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Path(self.temp.name) / "ledger.json"
        self.helper = load_helper()

    def test_reservations_are_counted_and_the_limit_blocks(self):
        self.helper.seed(path=self.ledger, limit=2, used=0)
        self.assertTrue(self.helper.reserve(path=self.ledger, attempt_id="a")[0])
        self.assertTrue(self.helper.reserve(path=self.ledger, attempt_id="a")[0])
        allowed, used, limit = self.helper.reserve(path=self.ledger, attempt_id="a")
        self.assertFalse(allowed)
        self.assertEqual((used, limit), (2, 2))
        state = json.loads(self.ledger.read_text())
        self.assertEqual(state["used"], 2)
        self.assertIsNotNone(state["blocked_at"])

    def test_seeding_never_lowers_the_used_count(self):
        self.helper.seed(path=self.ledger, limit=10, used=4)
        self.assertEqual(self.helper.seed(path=self.ledger, limit=10, used=2)["used"], 4)

    def test_concurrent_processes_never_exceed_the_limit(self):
        self.helper.seed(path=self.ledger, limit=5, used=0)
        helper = AGENT_BUDGET_HOOK_DIR / "qwb_agent_budget.py"
        script = textwrap.dedent(f"""
            import importlib.util, sys
            spec = importlib.util.spec_from_file_location("h", {str(helper)!r})
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            granted = 0
            for _ in range(50):
                if module.reserve(path={str(self.ledger)!r}, attempt_id=sys.argv[1])[0]:
                    granted += 1
            print(granted)
        """)
        processes = [subprocess.Popen([sys.executable, "-c", script, f"p{index}"],
                                      stdout=subprocess.PIPE, text=True) for index in range(4)]
        granted = sum(int(process.communicate()[0].strip() or 0) for process in processes)
        self.assertEqual(granted, 5, "the ledger must hand out exactly the limit across processes")
        self.assertEqual(json.loads(self.ledger.read_text())["used"], 5)


class HookInjectionTests(unittest.TestCase):
    """sitecustomize + PYTHONPATH is the injection point; the fake litellm proves blocking."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fake = Path(self.temp.name) / "fakelib"
        self.fake.mkdir()
        (self.fake / "litellm.py").write_text(
            "CALLS = []\n\n"
            "def completion(**kwargs):\n"
            "    CALLS.append(kwargs)\n"
            "    return {'ok': True, 'n': len(CALLS)}\n", encoding="utf-8")
        self.ledger = Path(self.temp.name) / "ledger.json"

    def run_child(self, body: str) -> subprocess.CompletedProcess:
        env = {**os.environ,
               "PYTHONPATH": os.pathsep.join([str(AGENT_BUDGET_HOOK_DIR), str(self.fake)]),
               "QWB_AGENT_BUDGET_FILE": str(self.ledger),
               "QWB_AGENT_BUDGET_LIMIT": "2",
               "QWB_AGENT_BUDGET_STRICT": "1",
               "QWB_ATTEMPT_ID": "attempt-hook"}
        return subprocess.run([sys.executable, "-c", body], capture_output=True, text=True, env=env)

    def test_calls_are_counted_and_blocked_at_the_limit(self):
        body = ("from litellm import completion\n"
                "import json\n"
                "results = []\n"
                "for _ in range(3):\n"
                "    try:\n"
                "        results.append(completion(model='x', messages=[]))\n"
                "    except Exception as exc:\n"
                "        results.append(type(exc).__name__)\n"
                "print(json.dumps(results))\n")
        finished = self.run_child(body)
        self.assertEqual(finished.returncode, 0, finished.stderr)
        results = json.loads(finished.stdout.strip().splitlines()[-1])
        self.assertEqual(results[:2], [{"ok": True, "n": 1}, {"ok": True, "n": 2}])
        self.assertEqual(results[2], "AgentCallBudgetExhausted")
        state = json.loads(self.ledger.read_text())
        self.assertEqual(state["used"], 2)
        self.assertEqual(len(state["events"]), 2)
        self.assertEqual(state["events"][0]["attempt_id"], "attempt-hook")

    def test_hook_is_inert_without_the_platform_environment(self):
        env = {**os.environ,
               "PYTHONPATH": os.pathsep.join([str(AGENT_BUDGET_HOOK_DIR), str(self.fake)])}
        env.pop("QWB_AGENT_BUDGET_FILE", None)
        finished = subprocess.run(
            [sys.executable, "-c",
             "from litellm import completion\nprint(completion(model='x')['n'])"],
            capture_output=True, text=True, env=env)
        self.assertEqual(finished.returncode, 0, finished.stderr)
        self.assertFalse(self.ledger.exists(), "no ledger may be written outside a platform attempt")


class ExecutorWiringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = isolated_repo_root(self.temp.name)
        self.policy = load_policy()
        self.limits = {**child_limits(self.policy), **agent_limits(self.policy)}

    def test_container_carries_the_hook_the_ledger_and_the_limits(self):
        executor = RDAgentExecutor(repo_root=self.root, agent_root=self.root,
                                   profile_path=ROOT / "configs/cn/profile.json",
                                   limits=self.limits, budget_root=self.root / "agent_budget")
        host_env = executor.environment(executor.LOOP)
        self.assertNotIn("QWB_AGENT_BUDGET_FILE", host_env,
                         "the host process must not be pointed at the in-container ledger")
        container = executor.container_environment()
        self.assertEqual(container["QWB_AGENT_BUDGET_LIMIT"], str(self.policy.agent_max_calls))
        self.assertEqual(container["QWB_AGENT_BUDGET_STRICT"], "1")
        self.assertEqual(container["QWB_RDAGENT_IN_CONTAINER"], "1")
        self.assertEqual(container["QWB_RDAGENT_ROOT"], CONTAINER_AGENT_DIR)
        self.assertEqual(container["QWB_REPO_ROOT"], CONTAINER_REPO_DIR)
        self.assertTrue(container["PYTHONPATH"].startswith(CONTAINER_HOOK_DIR))
        self.assertEqual(container["QWB_AGENT_BUDGET_FILE"],
                         f"{CONTAINER_PLATFORM_DIR}/agent_budget/{executor.call_ledger_path().name}")
        prepared = executor.prepare("route-1", executor.LOOP, {"mode": "loop"})
        command = " ".join(prepared["command"])
        self.assertEqual(prepared["command"][:3], ["docker", "run", "--rm"])
        self.assertIn("--memory", command)
        self.assertIn(f"{CONTAINER_REPO_DIR}/scripts/run_rdagent_factor_smoke.py", command)
        mounts = " ".join(prepared["container"]["mounts"][index][0] for index in range(1))
        self.assertIn(str(self.root), mounts)
        checks = {item["id"]: item for item in executor.checks()}
        self.assertIn("rdagent.call_budget", checks, checks.keys())

    def test_seed_top_up_and_report_round_trip(self):
        executor = RDAgentExecutor(repo_root=self.root, agent_root=self.root, limits=self.limits,
                                   budget_root=self.root / "agent_budget")
        executor.seed_call_ledger(attempts_seen=4)
        state = json.loads(executor.call_ledger_path().read_text())
        self.assertEqual((state["limit"], state["used"]), (self.policy.agent_max_calls, 4))
        report = executor.agent_budget_report({"attempt_id": "attempt-x"})
        self.assertEqual((report["used"], report["attempt_used"], report["status"]),
                         (4, 0, "within_budget"), report)


class ServiceReconciliationTests(unittest.TestCase):
    def test_agent_template_compilation_honours_the_configured_checkout(self):
        spec = importlib.util.spec_from_file_location(
            "prepare_cn_scenario_under_test", ROOT / "scripts" / "prepare_cn_scenario.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        previous = os.environ.get("QWB_RDAGENT_ROOT")
        try:
            os.environ["QWB_RDAGENT_ROOT"] = str(ROOT.parent / "elsewhere" / "RD-Agent")
            self.assertEqual(module.agent_root(),
                             (ROOT.parent / "elsewhere" / "RD-Agent").expanduser())
            os.environ.pop("QWB_RDAGENT_ROOT", None)
            self.assertEqual(module.agent_root(), module.PROJECT.parent / "RD-Agent")
        finally:
            if previous is None:
                os.environ.pop("QWB_RDAGENT_ROOT", None)
            else:
                os.environ["QWB_RDAGENT_ROOT"] = previous

    def test_terminal_attempt_reconciles_calls_into_the_durable_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            root = isolated_repo_root(folder)
            repository = LocalResultRepository(root / "store")
            policy = load_policy()

            class ReportingStub(StubExecutor):
                kinds = ("rdagent.factor.baseline",)

                def agent_call_enforcement(self):
                    return True

                def seed_call_ledger(self, *, attempts_seen=0):
                    self.seeded = attempts_seen

                def agent_budget_report(self, attempt):
                    return {"kind": "calls", "used": 7, "limit": policy.agent_max_calls,
                            "scope": policy.agent_scope, "attempt_used": 3,
                            "status": "within_budget"}

            executor = ReportingStub(root)
            service = ExecutionService(repository, executors=[executor], policy=policy)
            submitted = service.submit("rdagent.factor.baseline", {"script": "exit 0"},
                                       idempotency_key="calls-1")
            attempt_id = submitted["attempt"]["attempt_id"]
            self.assertEqual(executor.seeded, 0)
            for _ in range(100):
                service.reconcile([attempt_id])
                row = repository.get_attempt(attempt_id)
                if row["status"] not in ("queued", "running"):
                    break
                time.sleep(0.1)
            self.assertEqual(row["status"], "succeeded", row)
            self.assertEqual(row["outcome"]["agent_budget"]["calls"]["attempt_used"], 3)
            rows = {row["kind"]: row for row in repository.agent_budget_rows(policy.revision())}
            self.assertEqual(rows["trials"]["used"], 1)
            self.assertIn("calls", rows, rows)
            self.assertTrue(service.policy_summary()["agent"]["calls_enforced"])
            self.assertEqual(service.policy_summary()["agent"]["used"]["calls"], 7)


if __name__ == "__main__":
    unittest.main()
