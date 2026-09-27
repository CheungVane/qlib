"""BaoStock pacing rule: sequential only, mandatory sleep, no concurrency knob.

The rule comes from the 2026-09-27 incident (6 processes -> IP blacklisted) and the
community reports recorded in docs/spec/DATA_SOURCES.md. These tests are offline: they
exercise the guard that runs *before* any network call.
"""

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "fetch_csi500_turnover.py"


class PacingGuardTests(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              capture_output=True, text=True, timeout=60)

    def test_sleep_below_the_floor_is_refused_before_any_network_use(self):
        for value in ("0", "0.1", "0.49", "-1"):
            with self.subTest(value=value):
                finished = self.run_script("--instruments", "/tmp/absent.txt",
                                           "--out", "/tmp/absent", "--sleep", value)
                self.assertEqual(finished.returncode, 2)
                self.assertIn("--sleep must be >=", finished.stderr)
                # it must fail on pacing, not on the missing universe or on a login attempt
                self.assertNotIn("login", finished.stderr.lower())
                self.assertNotIn("no such file", finished.stderr.lower())

    def test_help_has_no_concurrency_option(self):
        finished = self.run_script("--help")
        self.assertEqual(finished.returncode, 0)
        self.assertNotIn("--workers", finished.stdout)
        self.assertIn("--sleep", finished.stdout)
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("one symbol at a time in a single process", source)
        self.assertIn("sleeps between symbols", source)

    def test_script_does_not_import_concurrency_primitives(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("ProcessPoolExecutor", "ThreadPoolExecutor", "multiprocessing",
                          "--workers", "concurrent.futures"):
            self.assertNotIn(forbidden, source, f"{forbidden} must not appear in the fetcher")


if __name__ == "__main__":
    unittest.main()
