"""Run the sibling RD-Agent fork against the synthetic China market fixture.

This is an integration probe, not a production research launcher. It leaves the
RD-Agent tracked source and templates untouched.
"""

import argparse
import asyncio
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from prepare_cn_scenario import compile_agent, effective_segments, load_profile, profile_path


PROJECT = Path(__file__).resolve().parents[1]
AGENT = Path(os.environ.get("QWB_RDAGENT_ROOT") or PROJECT.parent / "RD-Agent").resolve()
# Where the platform keeps its own state (research snapshots, ledgers). The repository may be
# mounted read-only when this probe runs inside a container, so this must be explicit.
PLATFORM_ROOT = Path(os.environ.get("QWB_PLATFORM_ROOT") or PROJECT / ".data" / "workbench")
BASE_FEATURES = AGENT / "git_ignore_folder/qwb_base_features"
EVIDENCE = AGENT / "git_ignore_folder/qwb_factor_smoke.json"


def evidence_for(workspace, bundle, template, mode, metric_count):
    quality = json.loads((Path(workspace) / 'cn_quality.json').read_text())
    if quality['scenario_fingerprint'] != bundle['fingerprint']:
        raise RuntimeError('Result scenario does not match current configuration')
    return {'schema_version': 2, 'mode': mode, 'completed_at': datetime.now(timezone.utc).isoformat(),
            'metric_count': metric_count, 'dataset': 'synthetic_cn_current', 'template': template.name,
            'image': ENGINE_IMAGE, 'runtime': RUNTIME,
            'scenario_fingerprint': bundle['fingerprint'], 'quality': quality}


# The platform can run this probe inside a bounded container (whole attempt, one cgroup
# limit). The flags below only adapt paths and tool lookup; nothing about RD-Agent changes.
IN_CONTAINER = os.environ.get("QWB_RDAGENT_IN_CONTAINER") == "1"
ENGINE_IMAGE = os.environ.get("QWB_RDAGENT_IMAGE") or "qwb-rdagent-cpu:local"
RUNTIME = "container" if IN_CONTAINER else "host_process"


def assert_budget_hook_installed(backend_module) -> None:
    """Fail closed when the platform asked for call budgeting but the hook did not take.

    The hook wraps `litellm.completion`; if RD-Agent ever calls a different client, the ledger
    would stay empty and the platform would still report `calls_enforced=true`. Refusing to run
    is the only honest option.
    """
    if not os.environ.get("QWB_AGENT_BUDGET_FILE"):
        return
    completion = getattr(backend_module, "completion", None)
    if not getattr(completion, "__qwb_budget_wrapped__", False):
        raise RuntimeError(
            "agent call budget is configured but the litellm hook is not installed on the "
            "backend this probe uses; refusing to run uncounted")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("baseline", "loop"), default="baseline")
    args = parser.parse_args()
    if Path.cwd().resolve() != AGENT.resolve():
        parser.error(f"run from the RD-Agent checkout: {AGENT}")
    bundle = load_profile(profile_path())
    template = compile_agent(bundle)
    if not (BASE_FEATURES / "base_factors.json").is_file():
        BASE_FEATURES.mkdir(parents=True, exist_ok=True)
        (BASE_FEATURES / "base_factors.json").write_text('{"CLOSE":"$close"}\n')
    if not (AGENT / ".env").is_file():
        parser.error("RD-Agent .env is missing")
    if not IN_CONTAINER and shutil.which("timeout") is None:
        coreutils_bin = Path("/opt/homebrew/opt/coreutils/libexec/gnubin")
        if (coreutils_bin / "timeout").is_file():
            os.environ["PATH"] = f"{coreutils_bin}:{os.environ.get('PATH', '')}"
        else:
            parser.error("GNU timeout is required (brew install coreutils)")

    from dotenv import load_dotenv

    load_dotenv(AGENT / ".env")
    # Upstream runner cache keys contain task descriptions, not execution scenarios.
    # A changed fee/calendar profile must never reuse an old baseline result.
    os.environ['RD_AGENT_CACHE_WITH_PICKLE'] = 'false'
    os.environ["QLIB_FACTOR_EVOLVING_N"] = str(bundle['research']['agent']['evolving_n'])
    os.environ["FACTOR_COSTEER_MAX_LOOP"] = str(bundle['research']['agent']['coder_max_loop'])
    for segment, bounds in effective_segments(bundle).items():
        for bound, value in zip(('START', 'END'), bounds):
            os.environ[f'QLIB_FACTOR_{segment.upper()}_{bound}'] = value
    # Inside the bounded container the interpreter that runs this probe is also the one the
    # factor code must use (the image carries Qlib and the RD-Agent dependencies).
    factor_bin = (os.environ.get("PATH", "") if IN_CONTAINER
                  else f"{AGENT / '.venv/bin'}:{os.environ.get('PATH', '')}")
    os.environ["FACTOR_COSTEER_PYTHON_BIN"] = sys.executable if IN_CONTAINER else str(AGENT / ".venv/bin/python")
    sys.path.insert(0, str(AGENT))

    from rdagent.utils.env import LocalConf, LocalEnv
    from rdagent.core.conf import RD_AGENT_SETTINGS
    RD_AGENT_SETTINGS.cache_with_pickle = False
    import rdagent.scenarios.qlib.experiment.factor_experiment as factor_experiment
    from rdagent.scenarios.qlib.experiment.workspace import QlibFBWorkspace
    # The backend module is what actually calls the LLM; verify the budget hook reached it.
    import rdagent.oai.backend.litellm as rdagent_llm_backend
    assert_budget_hook_installed(rdagent_llm_backend)

    # RD-Agent's Mac factor path assumes Conda. Evaluate the generated code with the
    # interpreter of this probe: the host RD-Agent venv, or the container that carries Qlib
    # and the RD-Agent dependencies.
    factor_experiment.get_factor_env = lambda: LocalEnv(
        conf=LocalConf(default_entry="python main.py", bin_path=factor_bin))
    original_init = QlibFBWorkspace.__init__

    def init_from_cn_template(self, template_folder_path, *extra, **kwargs):
        return original_init(self, template_folder_path=template, *extra, **kwargs)

    QlibFBWorkspace.__init__ = init_from_cn_template

    if IN_CONTAINER:
        # This probe already runs inside the bounded container, so the workspace must not
        # connect to a nested Docker engine (``MODEL_COSTEER_ENV_TYPE=docker`` in .env). The
        # stand-in keeps upstream's execute() logic — only the execution environment changes.
        import rdagent.scenarios.qlib.experiment.workspace as workspace_module

        class _ContainerLocalEnv:
            def __init__(self, *args, **kwargs):
                self._env = LocalEnv(conf=LocalConf(default_entry="python main.py",
                                                    bin_path=factor_bin))

            def prepare(self, *args, **kwargs):
                return self._env.prepare(*args, **kwargs)

            def check_output(self, **kwargs):
                return self._env.check_output(**kwargs)

        workspace_module.QTDockerEnv = _ContainerLocalEnv

    if args.mode == "baseline":
        from rdagent.scenarios.qlib.developer.factor_runner import QlibFactorRunner
        from rdagent.scenarios.qlib.experiment.factor_experiment import QlibFactorExperiment, QlibFactorScenario

        experiment = QlibFactorExperiment(sub_tasks=[])
        experiment.base_features = {"CLOSE": "$close"}
        result = QlibFactorRunner(QlibFactorScenario()).develop(experiment)
        metric_count = len(result.result) if result.result is not None else 0
        if metric_count == 0:
            raise RuntimeError("RD-Agent baseline produced no metrics")
        evidence = evidence_for(result.experiment_workspace.workspace_path, bundle, template, 'baseline', metric_count)
        EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(evidence, ensure_ascii=False))
    else:
        import rdagent.components.workflow.rd_loop as rd_loop
        from rdagent.app.qlib_rd_loop.factor import FactorRDLoop, FACTOR_PROP_SETTING

        # The exact CLOSE expression was checked by the container baseline.
        # Upstream's validator assumes a separate Conda environment and a
        # historical instrument absent from this small fixture.
        rd_loop.validate_qlib_features = lambda expressions: expressions == ["$close"]
        loop = FactorRDLoop(FACTOR_PROP_SETTING)
        loop._init_base_features(str(BASE_FEATURES))
        asyncio.run(loop.run(loop_n=1))
        if not loop.trace.hist:
            raise RuntimeError("RD-Agent produced no recorded experiment")
        experiment, feedback = loop.trace.hist[-1]
        if experiment.result is None or len(experiment.result) == 0:
            raise RuntimeError("Loop ended without backtest metrics; inspect coding/execution feedback")
        workspace = experiment.experiment_workspace.workspace_path
        if not (workspace / "combined_factors_df.parquet").is_file() or not (workspace / "ret.parquet").is_file():
            raise RuntimeError("Loop ended without factor and backtest artifacts")
        import pandas as pd

        factors = pd.read_parquet(workspace / "combined_factors_df.parquet")
        returns = pd.read_parquet(workspace / "ret.parquet")
        if factors.empty or returns.empty:
            raise RuntimeError("Factor or backtest artifact is empty")
        evidence = evidence_for(workspace, bundle, template, 'loop', len(experiment.result))
        evidence.update(factor_count=factors.shape[1], factor_rows=len(factors), return_rows=len(returns))
        (EVIDENCE.parent / "qwb_factor_loop.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(evidence))


if __name__ == "__main__":
    prior_sessions = {p.name for p in (AGENT / "log").glob("*") if p.is_dir()}
    try:
        main()
    finally:
        if Path.cwd().resolve() == AGENT.resolve():
            from export_rdagent_research import export
            try:
                exported = export(AGENT, PLATFORM_ROOT / 'research', PLATFORM_ROOT, True,
                                  {p.name for p in (AGENT / 'log').glob('*') if p.is_dir()} - prior_sessions)
                print(json.dumps({'research_sessions_synced': exported}))
            except Exception as exc:
                # An observation failure must not hide the original execution failure.
                print('Research snapshot sync failed: ' + type(exc).__name__, file=sys.stderr)
