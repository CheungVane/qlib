"""T04/EXEC13: the container route that makes the memory cap a real cgroup limit.

Offline tests pin the command shape and the path rewrite. The real-container tests are gated
behind QWB_CONTAINER_TESTS=1 because they need a running Docker engine (colima); they are what
produces the A41 evidence: an attempt that exceeds the cap must end `failed/resource_limit`,
not `nonzero_exit`.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from quant_workbench.adapters.executors import (
    CONTAINER_RUN_DIR, QlibCNExecutor, SubprocessExecutor, container_command, container_name,
)
from quant_workbench.execution_policy import PROBE_IMAGE, child_limits, container_flags, load_policy

try:  # works under both `unittest discover -s tests` and `-m unittest tests.*`
    from tests.sandbox import isolated_repo_root
except ImportError:
    from sandbox import isolated_repo_root  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = ROOT / ".data" / "cn_current_demo"
CONTAINER_TESTS = os.environ.get("QWB_CONTAINER_TESTS") == "1"
DOCKER = shutil.which("docker") is not None


class HogExecutor(SubprocessExecutor):
    """Containerized stub: the inner command is a plain memory/CPU hog."""

    executor_id = "stub_container"
    kinds = ("stub.container.hog",)

    def __init__(self, root, limits, hog="bytearray(400*1024*1024)"):
        super().__init__(root, source_root=root, limits=limits)
        self.hog = hog

    def containerized(self) -> bool:
        return True

    def container_route(self, attempt_id, kind, params, run_dir):
        return {"name": container_name(self.executor_id, attempt_id), "image": PROBE_IMAGE,
                "image_id": None, "workdir": CONTAINER_RUN_DIR,
                "mounts": [(str(run_dir), CONTAINER_RUN_DIR, "rw")]}

    def command(self, attempt_id, kind, params, run_dir):
        route = self.container_route(attempt_id, kind, params, run_dir)
        return container_command(name=route["name"], image=route["image"],
                                 workdir=CONTAINER_RUN_DIR, mounts=route["mounts"],
                                 inner=["python", "-c", self.hog], limits=self.limits)

    def checks(self):
        return [{"id": "stub.ready", "status": "ok", "detail": "stub", "required_for": list(self.kinds)}]

    def describe(self, kind):
        return {"label": "container hog", "description": "test entry", "probe": True,
                "data_nature": "test", "params": []}


class ContainerFlagTests(unittest.TestCase):
    """The flags are the contract: without them the cap does not exist."""

    def test_limits_become_memory_and_cpu_flags(self):
        flags = container_flags({"memory_bytes": (2147483648, 2147483648),
                                 "cpu_seconds": (600, 600)})
        self.assertEqual(flags, ["--memory=2147483648b", "--memory-swap=2147483648b",
                                 "--ulimit=cpu=600:600"])

    def test_unenforced_memory_produces_no_memory_flag(self):
        self.assertEqual(container_flags({"cpu_seconds": (60, 60)}), ["--ulimit=cpu=60:60"])
        self.assertEqual(container_flags({}), [])

    def test_command_mounts_named_container_and_workdir(self):
        command = container_command(name="qwb-x", image="img:test", workdir=CONTAINER_RUN_DIR,
                                    mounts=[("/host/run", CONTAINER_RUN_DIR, "rw"),
                                            ("/host/data", "/qwb/data", "ro")],
                                    inner=["qrun", "/qwb/run/workflow.yaml"],
                                    limits={"memory_bytes": (1024, 1024)},
                                    env={"PYTHONPATH": "/qwb/src"})
        self.assertEqual(command[:4], ["docker", "run", "--rm", "--init"])
        self.assertIn("--memory=1024b", command)
        self.assertIn("-e", command)
        self.assertEqual(command[-3:], ["img:test", "qrun", "/qwb/run/workflow.yaml"])
        self.assertIn("/host/run:/qwb/run:rw", command)

    def test_container_name_is_deterministic_and_docker_legal(self):
        first = container_name("qlib_subprocess", "9f2c1b7a-1234-5678")
        self.assertEqual(first, container_name("qlib_subprocess", "9f2c1b7a-1234-5678"))
        self.assertNotEqual(first, container_name("rdagent_subprocess", "9f2c1b7a-1234-5678"))
        self.assertTrue(all(char.isalnum() or char in "-." for char in first), first)


class PathNormalizationTests(unittest.TestCase):
    """The container records /qwb/run/...; the host-side import must find the real files."""

    def test_attempt_store_paths_are_normalized_back_to_the_workspace(self):
        import sqlite3
        with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
            run_dir = Path(folder) / "run"
            (run_dir / "mlruns" / "1" / "abc").mkdir(parents=True)
            database = run_dir / "mlflow.db"
            connection = sqlite3.connect(database)
            connection.execute("create table experiments (artifact_location text)")
            connection.execute("create table runs (artifact_uri text)")
            connection.execute("insert into experiments values ('/qwb/run/mlruns/0')")
            connection.execute("insert into runs values ('/qwb/run/mlruns/1/abc/artifacts')")
            connection.commit()
            connection.close()
            meta = run_dir / "mlruns" / "1" / "abc" / "meta.yaml"
            meta.write_text("artifact_uri: /qwb/run/mlruns/1/abc/artifacts\n", encoding="utf-8")
            executor = QlibCNExecutor(repo_root=ROOT, limits={})
            record = executor._normalize_container_paths(run_dir)
            self.assertEqual((record["db_rows"], record["meta_files"]), (2, 1), record)
            connection = sqlite3.connect(database)
            rows = [row[0] for row in connection.execute("select artifact_location from experiments")]
            rows += [row[0] for row in connection.execute("select artifact_uri from runs")]
            connection.close()
            for row in rows:
                self.assertTrue(row.startswith(str(run_dir)), row)
            self.assertIn(str(run_dir), meta.read_text(encoding="utf-8"))
            self.assertIsNone(executor._normalize_container_paths(run_dir), "second pass must be a no-op")


@unittest.skipUnless(SNAPSHOT.is_dir(), "synthetic CN snapshot not materialised")
class QlibRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home())
        self.addCleanup(self.temp.cleanup)

    def test_prepared_command_targets_container_paths_and_rewrites_the_workflow(self):
        executor = QlibCNExecutor(repo_root=ROOT, limits=child_limits(load_policy()))
        prepared = executor.prepare("route-check", "qlib.cn_synthetic_backtest", {})
        command = " ".join(prepared["command"])
        self.assertEqual(prepared["command"][:3], ["docker", "run", "--rm"])
        self.assertIn("--memory", command)
        self.assertIn(f"qrun {CONTAINER_RUN_DIR}/workflow.yaml", command)
        text = (Path(prepared["workspace"]) / "workflow.yaml").read_text(encoding="utf-8")
        self.assertNotIn(str(Path.home()), text)
        self.assertIn("/qwb/data", text)
        self.assertIn("/qwb/src", text)


@unittest.skipUnless(CONTAINER_TESTS and DOCKER, "set QWB_CONTAINER_TESTS=1 with Docker running")
class ContainerLimitTests(unittest.TestCase):
    """Real enforcement, run on demand; produces the A41 evidence file."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.home())
        self.addCleanup(self.temp.cleanup)
        self.root = isolated_repo_root(self.temp.name)

    def run_attempt(self, executor, attempt_id, timeout=180):
        prepared = executor.prepare(attempt_id, "stub.container.hog", {})
        started = executor.start(attempt_id, prepared)
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = executor.poll({"attempt_id": attempt_id, "workspace": prepared["workspace"],
                                   "pid": started["pid"], "log_path": prepared["log_path"]})
            if state["state"] != "running":
                return state
            time.sleep(0.5)
        executor.cancel({"attempt_id": attempt_id, "workspace": prepared["workspace"],
                         "pid": started["pid"]})
        raise AssertionError("attempt did not finish inside the test timeout")

    def test_memory_cap_oom_kills_the_container(self):
        limits = {"memory_bytes": (134217728, 134217728), "cpu_seconds": (120, 120)}
        state = self.run_attempt(HogExecutor(self.root, limits), "container-oom")
        self.assertEqual((state["state"], state["error_code"]), ("failed", "resource_limit"), state)
        self.assertEqual(state["exit_code"], 137, state)
        self.assertTrue(state["evidence"]["containerized"])

    def test_cpu_cap_is_enforced_inside_the_container(self):
        limits = {"cpu_seconds": (2, 2), "memory_bytes": (536870912, 536870912)}
        executor = HogExecutor(self.root, limits, hog="\nwhile True: pass")
        state = self.run_attempt(executor, "container-cpu")
        self.assertEqual((state["state"], state["error_code"]), ("failed", "resource_limit"), state)
        self.assertIn(state["exit_code"], (137, 152), state)

    def test_cancel_removes_the_container_not_just_the_client(self):
        limits = {"memory_bytes": (536870912, 536870912), "cpu_seconds": (60, 60)}
        executor = HogExecutor(self.root, limits, hog="\nimport time\nwhile True: time.sleep(1)")
        prepared = executor.prepare("container-cancel", "stub.container.hog", {})
        started = executor.start("container-cancel", prepared)
        name = container_name(executor.executor_id, "container-cancel")
        deadline = time.time() + 60
        while time.time() < deadline and not self.container_listed(name):
            time.sleep(0.5)
        self.assertTrue(self.container_listed(name), "container never started")
        result = executor.cancel({"attempt_id": "container-cancel",
                                  "workspace": prepared["workspace"], "pid": started["pid"]})
        self.assertTrue(result["confirmed"], result)
        for _ in range(20):
            if not self.container_listed(name):
                break
            time.sleep(0.5)
        self.assertFalse(self.container_listed(name),
                         "killing the docker client must not leave the container running")

    @staticmethod
    def container_listed(name: str) -> bool:
        finished = subprocess.run(["docker", "ps", "-a", "--filter", f"name=^/{name}$",
                                   "--format", "{{.Names}}"], capture_output=True, text=True)
        return bool(finished.stdout.strip())

    def test_container_check_and_policy_are_recorded_as_evidence(self):
        policy = load_policy()
        executor = QlibCNExecutor(repo_root=ROOT, limits=child_limits(policy))
        checks = {item["id"]: item for item in executor.checks()}
        payload = {"policy": policy.revision(), "enforce": list(policy.enforce),
                   "memory_bytes": policy.memory_bytes, "max_concurrent": policy.max_concurrent,
                   "checks": {key: {"status": item["status"], "detail": item["detail"]}
                              for key, item in checks.items()}}
        (ROOT / "docs" / "spec" / "evidence" / "20260927-container-limits.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(checks["cn.container"]["status"], "ok", checks["cn.container"])


if __name__ == "__main__":
    unittest.main()
