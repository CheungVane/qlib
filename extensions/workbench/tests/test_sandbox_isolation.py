"""Regression: executor tests must never write into the real checkout.

The 2026-09-27 leftovers `<repo>/runs/<attempt>-stub_sleep` came from policy tests that passed
a bare temp directory to `StubExecutor`; `discover_project_root()` then fell through to the
installed checkout. The residue was deleted, the fallback removed, and these tests keep both
halves honest.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from quant_workbench.adapters.executors import SubprocessExecutor
from quant_workbench.cn_market import ProjectRootNotFound, discover_project_root

try:  # works under both `unittest discover -s tests` and `-m unittest tests.*`
    from tests.sandbox import isolated_repo_root
except ImportError:
    from sandbox import isolated_repo_root  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[3]


class SandboxIsolationTests(unittest.TestCase):
    def test_marked_sandbox_keeps_executor_workspaces_inside_it(self):
        with tempfile.TemporaryDirectory() as folder:
            sandbox = isolated_repo_root(folder)
            executor = SubprocessExecutor(repo_root=sandbox, source_root=sandbox)
            self.assertEqual(Path(executor.repo_root), sandbox.resolve())
            workspace = executor.workspace("attempt-1", "stub.sleep", {})
            self.assertTrue(workspace.is_relative_to(sandbox.resolve()), workspace)

    def test_unmarked_explicit_root_is_refused_instead_of_falling_back(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ProjectRootNotFound) as raised:
                discover_project_root(folder)
            message = str(raised.exception)
            self.assertIn(folder, message)
            self.assertIn(str(ROOT), message)

    def test_real_checkout_is_still_accepted_and_runs_stays_ignored(self):
        self.assertEqual(discover_project_root(ROOT), ROOT.resolve())
        ignored = subprocess.run(["git", "check-ignore", "-q", "runs/attempt-stub_sleep/pid"],
                                 cwd=ROOT, check=False)
        self.assertEqual(ignored.returncode, 0, "runs/ must stay ignored as a safety net")


if __name__ == "__main__":
    unittest.main()
