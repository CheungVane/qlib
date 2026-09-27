"""Sandbox roots for tests that hand a checkout path to an executor.

`discover_project_root()` refuses an explicit root that does not look like the checkout, so a
bare `tempfile.TemporaryDirectory()` is a hard error rather than a silent fallback. Tests still
mark their sandbox and check the round trip, so a stray `QWB_REPO_ROOT` cannot redirect a stub
attempt into the real working tree.
"""
from pathlib import Path

from quant_workbench.cn_market import discover_project_root


def isolated_repo_root(path) -> Path:
    """Mark `path` as a checkout-shaped sandbox and assert it resolves to itself."""
    root = Path(path)
    (root / "configs" / "cn").mkdir(parents=True, exist_ok=True)
    (root / "configs" / "cn" / "profile.json").write_text("{}\n", encoding="utf-8")
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    resolved = discover_project_root(root)
    if resolved != root.resolve():
        raise AssertionError(
            f"test sandbox is not isolated: {root} resolved to {resolved}; "
            "check QWB_REPO_ROOT and configs/cn/profile.json")
    return root
