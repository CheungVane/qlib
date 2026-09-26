"""Subprocess executors for the local research entries.

The workbench process never imports Qlib or RD-Agent. Every attempt runs in its own
process, working directory and log/exit-evidence channel; preconditions are checked
before any process is created (EXEC03/EXEC06).
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..cn_market import load_profile
from ..execution import InvalidExecutionRequest
from ..source_safety import Sanitizer

PREFLIGHT_TTL_SECONDS = 15.0
LOG_BYTE_CAP = 200_000
COMPILE_TIMEOUT = 180
QWB_RDAGENT_IMAGE = "qwb-qlib-cpu:local"
# Dataset identity for the current synthetic CN scenario; a real data directory will
# replace this constant (see docs/spec/CN_A_SHARE_AUDIT.md and the DATA01-05 gap).
CN_SYNTHETIC_DATASET_ID = "cn-current-synthetic"
CN_SYNTHETIC_SOURCE_INSTANCE = "qlib-cn-attempt"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def find_repo_root(explicit: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("QWB_REPO_ROOT"):
        candidates.append(Path(os.environ["QWB_REPO_ROOT"]))
    here = Path(__file__).resolve()
    candidates.extend(here.parents)
    candidates.append(Path.cwd())
    for candidate in candidates:
        try:
            if (candidate / "configs/cn/profile.json").is_file() and (candidate / "scripts").is_dir():
                return candidate.resolve()
        except OSError:
            continue
    return here.parents[2].resolve()


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_int(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _count_lines(path: Path, cap: int = 200_000) -> int:
    lines = 0
    with path.open("rb") as stream:
        for _ in stream:
            lines += 1
            if lines >= cap:
                break
    return lines


def _run(cmd: list[str], timeout: float = 5) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            values[key.strip()] = value.strip().strip('"\'')
    return values


class SubprocessExecutor:
    """Shared lifecycle: isolated workspace, exit marker, process-group cancel."""

    executor_id = "subprocess"
    kinds: tuple[str, ...] = ()

    def __init__(self, repo_root: str | Path | None = None, source_root: str | Path | None = None):
        self.repo_root = find_repo_root(repo_root)
        self.source_root = Path(source_root).expanduser().resolve() if source_root else self.repo_root
        self.sanitizer = Sanitizer(self.source_root)
        self._preflight: dict[str, Any] | None = None
        self._preflight_at = 0.0
        self._processes: dict[str, subprocess.Popen] = {}

    # -- hooks -----------------------------------------------------------
    def checks(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def describe(self, kind: str) -> dict[str, Any]:
        raise NotImplementedError

    def command(self, attempt_id: str, kind: str, params: dict[str, Any], run_dir: Path) -> list[str]:
        raise NotImplementedError

    def cwd(self, kind: str, run_dir: Path) -> Path:
        return self.repo_root

    def environment(self, kind: str) -> dict[str, str]:
        return {**os.environ, "PYTHONUNBUFFERED": "1"}

    def config_fingerprint(self) -> str | None:
        return None

    def import_candidate(self, attempt: dict[str, Any]) -> dict[str, Any] | None:
        """EXEC12 hook: return the engine-produced artifact to publish, or None."""
        return None

    def workspace(self, attempt_id: str, kind: str, params: dict[str, Any]) -> Path:
        return self.repo_root / ".data" / "attempts" / attempt_id

    def prepare_extra(self, attempt_id: str, kind: str, params: dict[str, Any], run_dir: Path) -> dict[str, Any]:
        return {}

    def validate_params(self, kind: str, params: dict[str, Any]) -> dict[str, Any]:
        rules = {rule["name"]: rule for rule in self.describe(kind).get("params", [])}
        unknown = sorted(set(params) - set(rules))
        if unknown:
            raise InvalidExecutionRequest(f"unknown parameters for {kind}: {', '.join(unknown)}")
        normalized: dict[str, Any] = {}
        for name, rule in rules.items():
            value = params.get(name, rule.get("default"))
            if value is None:
                if rule.get("required"):
                    raise InvalidExecutionRequest(f"parameter '{name}' is required")
                continue
            if rule.get("type") == "string" and not isinstance(value, str):
                raise InvalidExecutionRequest(f"parameter '{name}' must be a string")
            if rule.get("choices") and value not in rule["choices"]:
                raise InvalidExecutionRequest(f"parameter '{name}' must be one of {rule['choices']}")
            normalized[name] = value
        return normalized

    # -- lifecycle -------------------------------------------------------
    def preflight(self, refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if not refresh and self._preflight is not None and now - self._preflight_at < PREFLIGHT_TTL_SECONDS:
            return self._preflight
        checks = self.checks()
        available, reasons = {}, {}
        for kind in self.kinds:
            failed = [check["id"] for check in checks
                      if check.get("status") != "ok" and kind in (check.get("required_for") or [])]
            available[kind] = not failed
            reasons[kind] = failed
        payload = {"checks": checks, "available": available, "reasons": reasons, "checked_at": _now()}
        self._preflight, self._preflight_at = payload, now
        return payload

    def prepare(self, attempt_id: str, kind: str, params: dict[str, Any]) -> dict[str, Any]:
        normalized = self.validate_params(kind, params)
        run_dir = self.workspace(attempt_id, kind, normalized)
        run_dir.mkdir(parents=True, exist_ok=True)
        probe = run_dir / ".writable"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            raise InvalidExecutionRequest(f"attempt workspace is not writable: {exc}") from exc
        log_path = run_dir / "attempt.log"
        extra = self.prepare_extra(attempt_id, kind, normalized, run_dir)
        return {
            "attempt_id": attempt_id,
            "kind": kind,
            "params": normalized,
            "workspace": str(run_dir),
            "log_path": str(log_path),
            "exit_marker": str(run_dir / "exit_code"),
            "command": self.command(attempt_id, kind, normalized, run_dir),
            "cwd": str(self.cwd(kind, run_dir)),
            "env": self.environment(kind),
            "config_fingerprint": self.config_fingerprint(),
            **extra,
        }

    def start(self, attempt_id: str, prepared: dict[str, Any]) -> dict[str, Any]:
        run_dir = Path(prepared["workspace"])
        log_path = Path(prepared["log_path"])
        marker = Path(prepared["exit_marker"])
        log_path.touch(exist_ok=True)
        wrapper = (
            "umask 022\n"
            f"{shlex.join(prepared['command'])} >> {shlex.quote(str(log_path))} 2>&1\n"
            "code=$?\n"
            f"printf '%s' \"$code\" > {shlex.quote(str(marker))}\n"
            "exit \"$code\"\n"
        )
        process = subprocess.Popen(
            ["/bin/sh", "-c", wrapper], cwd=prepared["cwd"], env=prepared["env"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        self._processes[attempt_id] = process
        (run_dir / "pid").write_text(str(process.pid), encoding="utf-8")
        return {"pid": process.pid, "workspace": str(run_dir), "log_path": str(log_path)}

    def poll(self, attempt: dict[str, Any]) -> dict[str, Any]:
        attempt_id = attempt["attempt_id"]
        run_dir = Path(attempt.get("workspace") or "")
        code = _read_int(run_dir / "exit_code")
        handle = self._processes.get(attempt_id)
        if code is None and handle is not None:
            returncode = handle.poll()
            if returncode is not None:
                code = _read_int(run_dir / "exit_code")
                self._processes.pop(attempt_id, None)
                if code is None:
                    return {"state": "interrupted", "exit_code": None,
                            "error_code": "process_lost_without_exit_evidence",
                            "error_message": f"process exited with {returncode} but wrote no exit marker",
                            "ended_at": _now(), "evidence": {"exit_marker": False, "returncode": returncode}}
        if code is not None:
            self._processes.pop(attempt_id, None)
            state = "succeeded" if code == 0 else "failed"
            return {"state": state, "exit_code": code, "ended_at": _now(),
                    "error_code": None if code == 0 else "nonzero_exit",
                    "error_message": None if code == 0 else f"process exited with code {code}",
                    "evidence": {"exit_marker": True, "returncode": code}}
        if _pid_alive(attempt.get("pid")):
            return {"state": "running"}
        self._processes.pop(attempt_id, None)
        return {"state": "interrupted", "exit_code": None,
                "error_code": "process_lost_without_exit_evidence",
                "error_message": "no exit marker and the recorded process is gone",
                "ended_at": _now(), "evidence": {"exit_marker": False}}

    def cancel(self, attempt: dict[str, Any]) -> dict[str, Any]:
        attempt_id = attempt["attempt_id"]
        run_dir = Path(attempt.get("workspace") or "")
        marker = run_dir / "exit_code"
        handle = self._processes.get(attempt_id)
        if handle is not None:
            handle.poll()
        code = _read_int(marker)
        if code is not None:
            self._processes.pop(attempt_id, None)
            return {"confirmed": False, "state": "succeeded" if code == 0 else "failed", "exit_code": code,
                    "reason": "process_already_finished", "evidence": {"exit_marker": True}}
        pid = attempt.get("pid")
        if not _pid_alive(pid):
            self._processes.pop(attempt_id, None)
            return {"confirmed": True, "state": "cancelled", "exit_code": None,
                    "reason": "process_already_gone", "evidence": {"observed": "pid_not_alive"}}
        signals: list[str] = []
        for sig, grace in ((signal.SIGTERM, 10.0), (signal.SIGKILL, 5.0)):
            try:
                os.killpg(os.getpgid(pid), sig)
                signals.append(sig.name)
            except ProcessLookupError:
                break
            except PermissionError:
                return {"confirmed": False, "state": "running", "reason": "signal_permission_denied",
                        "evidence": {"signals": signals}}
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline:
                if _read_int(marker) is not None or not _pid_alive(pid):
                    break
                time.sleep(0.2)
            if _read_int(marker) is not None or not _pid_alive(pid):
                break
        if handle is not None:
            handle.poll()
        code = _read_int(marker)
        if code is None and _pid_alive(pid):
            return {"confirmed": False, "state": "running", "reason": "process_still_running",
                    "evidence": {"signals": signals}}
        self._processes.pop(attempt_id, None)
        return {"confirmed": True, "state": "cancelled", "exit_code": code, "reason": "process_end_confirmed",
                "evidence": {"signals": signals, "exit_marker": code is not None}}

    def outcome(self, attempt: dict[str, Any]) -> dict[str, Any]:
        return {}

    def log_tail(self, attempt: dict[str, Any], lines: int) -> dict[str, Any]:
        raw_path = attempt.get("log_path")
        path = Path(raw_path) if raw_path else None
        if path is None or not path.is_file():
            return {"available": False, "reason": "log_not_found", "lines": []}
        size = path.stat().st_size
        with path.open("rb") as stream:
            if size > LOG_BYTE_CAP:
                stream.seek(size - LOG_BYTE_CAP)
                data = stream.read()
                truncated = True
            else:
                data = stream.read()
                truncated = False
        raw_lines = data.decode("utf-8", errors="replace").splitlines()
        if truncated and raw_lines:
            raw_lines = raw_lines[1:]
        if len(raw_lines) > lines:
            raw_lines = raw_lines[-lines:]
            truncated = True
        return {"available": True, "lines": [self.sanitizer.text(line, 2000) for line in raw_lines],
                "total_bytes": size, "truncated": truncated}


class QlibCNExecutor(SubprocessExecutor):
    executor_id = "qlib_subprocess"
    kinds = ("qlib.cn_synthetic_backtest",)
    KIND = "qlib.cn_synthetic_backtest"

    def __init__(self, repo_root: str | Path | None = None, profile_path: str | Path | None = None):
        super().__init__(repo_root)
        self.profile_path = (Path(profile_path).expanduser().resolve() if profile_path
                             else self.repo_root / "configs/cn/profile.json")
        self._bundle: dict[str, Any] | None = None
        self._bundle_error: str | None = None

    def bundle(self, refresh: bool = False) -> dict[str, Any]:
        if refresh:
            self._bundle, self._bundle_error = None, None
        if self._bundle is None and self._bundle_error is None:
            try:
                self._bundle = load_profile(self.profile_path)
            except Exception as exc:
                self._bundle_error = f"{type(exc).__name__}: {exc}"
        if self._bundle_error is not None:
            raise InvalidExecutionRequest(f"CN profile is not usable: {self._bundle_error}")
        return self._bundle

    def describe(self, kind: str) -> dict[str, Any]:
        return {
            "label": "Qlib CN 合成行情训练+回测",
            "description": "按 configs/cn/profile.json 编译独立工作目录，用 Qlib 自身环境运行；结果需显式导入结果库。",
            "probe": False,
            "data_nature": "synthetic_current_rules_counterfactual",
            "params": [{"name": "note", "type": "string", "required": False,
                        "description": "可选备注，仅随 Attempt 保存"}],
        }

    def workspace(self, attempt_id: str, kind: str, params: dict[str, Any]) -> Path:
        fingerprint = (self.config_fingerprint() or "unknown")[:10]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        return self.repo_root / ".data" / "cn_runs" / f"{stamp}-{fingerprint}-{attempt_id[:8]}"

    def config_fingerprint(self) -> str | None:
        try:
            return self.bundle()["fingerprint"]
        except Exception:
            return None

    def checks(self) -> list[dict[str, Any]]:
        required = [self.KIND]
        checks: list[dict[str, Any]] = []

        def add(check_id: str, status: str, detail: str, required_for: list[str] | None = None) -> None:
            checks.append({"id": check_id, "status": status, "detail": detail,
                           "required_for": required if required_for is None else required_for})

        try:
            bundle = self.bundle(refresh=True)
        except Exception as exc:
            add("cn.profile", "missing", str(exc)[:300])
            return checks
        add("cn.profile", "ok",
            f"fingerprint {bundle['fingerprint'][:12]}; synthetic={bundle['research']['synthetic']}; "
            f"rules as_of {bundle['rules']['as_of']}")
        data_dir = self.repo_root / bundle["research"]["data_path"] / bundle["fingerprint"][:12]
        if (data_dir / "instruments").is_dir() and (data_dir / "features").is_dir():
            add("cn.data_snapshot", "ok", f"materialised snapshot {data_dir.name} matches the profile fingerprint")
        else:
            add("cn.data_snapshot", "missing",
                "run scripts/make_cn_current_data.py to materialise this fingerprint before executing")
        coverage = bundle["calendar"].get("coverage") or []
        test_end = bundle["research"]["segments"]["test"][1]
        if len(coverage) == 2 and coverage[0] <= test_end <= coverage[1]:
            add("cn.calendar", "ok", f"calendar {bundle['calendar']['id']} covers {coverage[0]}..{coverage[1]}")
        else:
            add("cn.calendar", "missing", f"calendar does not cover the test segment end {test_end}")
        fees = bundle["rules"]["fees"]
        account = bundle["account"]
        add("cn.fee_scenario", "ok",
            f"commission {account['commission_both']}/side, min {account['minimum_commission']}, "
            f"stamp_sell {fees['stamp_sell']}, transfer {fees['transfer_both']}, "
            f"slippage {bundle['research']['execution']['slippage_bps']}bps")
        python = self.repo_root / ".venv/bin/python"
        qrun = self.repo_root / ".venv/bin/qrun"
        if python.is_file() and qrun.is_file():
            add("cn.engine_env", "ok", "Qlib virtualenv provides python and qrun")
        else:
            add("cn.engine_env", "missing", "run scripts/run_cn_demo.sh once to build the Qlib virtualenv")
        run_root = self.repo_root / ".data" / "cn_runs"
        try:
            run_root.mkdir(parents=True, exist_ok=True)
            writable = os.access(run_root, os.W_OK)
        except OSError:
            writable = False
        add("cn.attempt_workspace", "ok" if writable else "missing",
            f"per-attempt workspace under {run_root.name} is "
            f"{'writable' if writable else 'not writable'}")
        return checks

    def environment(self, kind: str) -> dict[str, str]:
        env = {**super().environment(kind), "QWB_REPO_ROOT": str(self.repo_root),
               "MLFLOW_DISABLE_AGENT_HINT": "1"}
        sdk = Path("/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk")
        if os.uname().sysname == "Darwin" and (sdk / "usr/include/stdlib.h").is_file():
            env["SDKROOT"] = str(sdk)
        return env

    def cwd(self, kind: str, run_dir: Path) -> Path:
        return run_dir

    def command(self, attempt_id: str, kind: str, params: dict[str, Any], run_dir: Path) -> list[str]:
        return [str(self.repo_root / ".venv/bin/qrun"), str(run_dir / "workflow.yaml")]

    def prepare_extra(self, attempt_id: str, kind: str, params: dict[str, Any], run_dir: Path) -> dict[str, Any]:
        compile_script = self.repo_root / "scripts" / "prepare_cn_scenario.py"
        python = self.repo_root / ".venv/bin/python"
        result = _run([str(python), str(compile_script), "--target", "qlib", "--profile", str(self.profile_path),
                       "--out-dir", str(run_dir)], timeout=COMPILE_TIMEOUT)
        if result is None or result.returncode != 0:
            detail = (result.stderr if result else "compiler did not start").strip().splitlines()
            raise InvalidExecutionRequest(
                "CN scenario compile failed: " + (detail[-1] if detail else "unknown error"))
        workflow = run_dir / "workflow.yaml"
        if not workflow.is_file():
            raise InvalidExecutionRequest("CN scenario compile produced no workflow.yaml")
        return {"workflow": str(workflow)}

    def outcome(self, attempt: dict[str, Any]) -> dict[str, Any]:
        run_dir = Path(attempt["workspace"])
        outcome: dict[str, Any] = {
            "result_import": "manual_import_required",
            "data_nature": "synthetic_current_rules_counterfactual",
            "artifacts": {"workspace": run_dir.name},
            "notes": ["执行成功不代表研究有效；结果进入结果库仍需显式导入并声明行情性质。"],
        }
        quality_path = run_dir / "quality.json"
        if quality_path.is_file():
            try:
                quality = json.loads(quality_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                quality = None
            if isinstance(quality, dict):
                summary = {key: quality.get(key) for key in
                           ("status", "valid_ic_days", "constant_prediction_days", "trade_days", "reasons")}
                summary["scenario_matches_config"] = (
                    bool(attempt.get("config_fingerprint"))
                    and quality.get("scenario_fingerprint") == attempt.get("config_fingerprint"))
                outcome["quality"] = summary
                outcome["artifacts"]["quality"] = "quality.json"
        fees = run_dir / "fees.jsonl"
        if fees.is_file():
            outcome["artifacts"]["fee_ledger"] = {"file": "fees.jsonl", "bytes": fees.stat().st_size,
                                                  "lines": _count_lines(fees)}
        tracking = run_dir / "mlflow.db"
        if tracking.is_file():
            outcome["artifacts"]["mlflow_tracking"] = {"file": "mlflow.db", "bytes": tracking.stat().st_size}
            # Qlib writes one directory per run under the attempt workspace; listing the
            # attempt's own output is not a read of the source experiment database.
            run_ids = sorted({path.name for path in (run_dir / "mlruns").glob("*/*")
                              if path.is_dir() and len(path.name) == 32
                              and all(char in "0123456789abcdef" for char in path.name)})[:20]
            if run_ids:
                outcome["artifacts"]["mlflow_runs"] = run_ids
            outcome["import_hint"] = {
                "tool": "qwb import-qlib",
                "external_ids": run_ids,
                "note": ("本入口的执行结果会由平台自动导入（EXEC12）；手工重试使用 "
                         "`qwb import-attempt <attempt_id>`，不再暴露跟踪库路径。"),
            }
        return outcome

    def import_candidate(self, attempt: dict[str, Any]) -> dict[str, Any] | None:
        """EXEC12: the engine's own MLflow run in the attempt workspace is the import input."""
        run_dir = Path(attempt.get("workspace") or "")
        tracking = run_dir / "mlflow.db"
        run_ids = ((attempt.get("outcome") or {}).get("artifacts") or {}).get("mlflow_runs") or []
        if not tracking.is_file() or not run_ids:
            return None
        effective_path = run_dir / "effective.json"
        synthetic = True
        if effective_path.is_file():
            try:
                synthetic = bool(json.loads(effective_path.read_text(encoding="utf-8"))["research"]["synthetic"])
            except (OSError, ValueError, KeyError, TypeError):
                synthetic = True
        return {
            "importer": "qlib_mlflow",
            "source_instance_id": CN_SYNTHETIC_SOURCE_INSTANCE,
            "external_id": run_ids[-1],
            "tracking_uri": f"sqlite:///{tracking}",
            "dataset_id": CN_SYNTHETIC_DATASET_ID,
            "dataset_version": None,
            "synthetic": synthetic,
            "trust_local_artifacts": True,
            "config_path": str(effective_path) if effective_path.is_file() else None,
            "require_cn_scenario_evidence": True,
        }


class RDAgentExecutor(SubprocessExecutor):
    executor_id = "rdagent_subprocess"
    kinds = ("rdagent.factor.baseline", "rdagent.factor.loop")
    BASELINE = "rdagent.factor.baseline"
    LOOP = "rdagent.factor.loop"

    def __init__(self, repo_root: str | Path | None = None, agent_root: str | Path | None = None,
                 profile_path: str | Path | None = None):
        super().__init__(repo_root)
        self.agent_root = Path(agent_root or os.environ.get("QWB_RDAGENT_ROOT")
                               or self.repo_root.parent / "RD-Agent").expanduser().resolve()
        self.sanitizer = Sanitizer(self.agent_root)
        self.profile_path = (Path(profile_path).expanduser().resolve() if profile_path
                             else self.repo_root / "configs/cn/profile.json")
        self._bundle: dict[str, Any] | None = None
        self._bundle_error: str | None = None

    def bundle(self, refresh: bool = False) -> dict[str, Any]:
        if refresh:
            self._bundle, self._bundle_error = None, None
        if self._bundle is None and self._bundle_error is None:
            try:
                self._bundle = load_profile(self.profile_path)
            except Exception as exc:
                self._bundle_error = f"{type(exc).__name__}: {exc}"
        if self._bundle_error is not None:
            raise InvalidExecutionRequest(f"CN profile is not usable: {self._bundle_error}")
        return self._bundle

    def config_fingerprint(self) -> str | None:
        try:
            return self.bundle()["fingerprint"]
        except Exception:
            return None

    def import_unavailable_reason(self, attempt: dict[str, Any]) -> str:
        # RD-Agent output is a research snapshot: it enters the result library through the
        # trusted offline export, never as an automatic backtest import (EXEC12).
        return "rdagent_research_snapshot_required"

    def describe(self, kind: str) -> dict[str, Any]:
        mode = "loop" if kind == self.LOOP else "baseline"
        label = ("RD-Agent 单轮因子循环（集成探针）" if mode == "loop"
                 else "RD-Agent 因子基线（集成探针）")
        return {
            "label": label,
            "description": ("在 RD-Agent fork 内运行单轮因子演化循环并同步研究快照；使用本地 .env 的聊天与 embedding 配置。"
                            if mode == "loop" else
                            "在 RD-Agent fork 内运行因子基线回测（本地环境，不发聊天请求），并同步研究快照。"),
            "probe": True,
            "data_nature": "synthetic_probe",
            "params": [{"name": "mode", "type": "string", "required": False, "default": mode,
                        "choices": ["baseline", "loop"], "description": "RD-Agent 运行模式，默认与入口一致"},
                       {"name": "note", "type": "string", "required": False,
                        "description": "可选备注，仅随 Attempt 保存"}],
        }

    def workspace(self, attempt_id: str, kind: str, params: dict[str, Any]) -> Path:
        return self.agent_root / "git_ignore_folder" / "qwb_attempts" / attempt_id

    def environment(self, kind: str) -> dict[str, str]:
        env = {**super().environment(kind), "QWB_REPO_ROOT": str(self.repo_root),
               "QWB_RDAGENT_ROOT": str(self.agent_root)}
        coreutils = Path("/opt/homebrew/opt/coreutils/libexec/gnubin")
        if os.uname().sysname == "Darwin" and (coreutils / "timeout").is_file():
            env["PATH"] = f"{coreutils}:{env.get('PATH', '')}"
        return env

    def cwd(self, kind: str, run_dir: Path) -> Path:
        return self.agent_root

    def command(self, attempt_id: str, kind: str, params: dict[str, Any], run_dir: Path) -> list[str]:
        mode = params.get("mode") or ("loop" if kind == self.LOOP else "baseline")
        return [str(self.agent_root / ".venv/bin/python"),
                str(self.repo_root / "scripts" / "run_rdagent_factor_smoke.py"), "--mode", mode]

    def _docker_runtime(self) -> str | None:
        if shutil.which("docker") is None:
            return None
        result = _run(["docker", "info", "--format", "{{.OSType}}/{{.Architecture}}"], timeout=5)
        return result.stdout.strip() if result and result.returncode == 0 else None

    def _image_present(self, image: str) -> bool:
        result = _run(["docker", "image", "inspect", image, "--format", "{{.Id}}"], timeout=10)
        return bool(result and result.returncode == 0 and result.stdout.strip())

    def _resources(self) -> tuple[int | None, int | None]:
        result = _run(["docker", "info", "--format", "{{.NCPU}} {{.MemTotal}}"], timeout=5)
        if result is None or result.returncode != 0:
            return None, None
        try:
            cpu, memory = result.stdout.split()
            return int(cpu), int(memory)
        except (ValueError, TypeError):
            return None, None

    def _ollama_model(self, model: str, base: str) -> bool:
        from urllib.parse import urlsplit
        from urllib.request import urlopen
        parsed = urlsplit(base)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            return False
        try:
            with urlopen(base.rstrip("/") + "/api/tags", timeout=1) as response:
                payload = json.load(response).get("models", [])
        except (OSError, ValueError):
            return False
        return any(item.get("name", "").split(":", 1)[0] == model for item in payload)

    def checks(self) -> list[dict[str, Any]]:
        both = [self.BASELINE, self.LOOP]
        checks: list[dict[str, Any]] = []

        def add(check_id: str, status: str, detail: str, required_for: list[str] | None = None) -> None:
            checks.append({"id": check_id, "status": status, "detail": detail,
                           "required_for": both if required_for is None else required_for})

        try:
            bundle = self.bundle(refresh=True)
        except Exception as exc:
            add("rdagent.profile", "missing", str(exc)[:300])
            return checks
        fingerprint = bundle["fingerprint"]
        if (self.agent_root / ".git").exists():
            add("rdagent.checkout", "ok", f"checkout {self.agent_root.name}")
        else:
            add("rdagent.checkout", "missing", "RD-Agent checkout not found (set QWB_RDAGENT_ROOT)")
        python = self.agent_root / ".venv/bin/python"
        add("rdagent.venv", "ok" if python.is_file() else "missing",
            "RD-Agent virtualenv present" if python.is_file() else "RD-Agent .venv/bin/python is missing")
        config = _read_env_file(self.agent_root / ".env")
        chat_model = config.get("CHAT_MODEL")
        chat_key = bool(config.get("DEEPSEEK_API_KEY") or config.get("OPENAI_API_KEY"))
        if chat_model and chat_key:
            add("rdagent.chat", "ok", f"chat model {chat_model} configured (provider reachability not probed)",
                required_for=[self.LOOP])
        else:
            add("rdagent.chat", "missing", "CHAT_MODEL and an API key are required for the agent loop",
                required_for=[self.LOOP])
        embedding_model = config.get("EMBEDDING_MODEL") or ""
        if embedding_model.startswith("ollama/"):
            name = embedding_model.removeprefix("ollama/")
            ready = self._ollama_model(name, config.get("OLLAMA_API_BASE", ""))
            add("rdagent.embedding", "ok" if ready else "missing",
                f"local Ollama embedding {name} {'reachable' if ready else 'is not serving this model'}",
                required_for=[self.LOOP])
        elif embedding_model:
            add("rdagent.embedding", "ok" if chat_key else "missing",
                f"embedding {embedding_model} configured (reachability not probed)",
                required_for=[self.LOOP])
        else:
            add("rdagent.embedding", "missing", "EMBEDDING_MODEL is not configured", required_for=[self.LOOP])
        runtime = self._docker_runtime()
        if runtime and runtime.startswith("linux/"):
            add("rdagent.docker", "ok", f"Linux Docker engine {runtime}")
        else:
            add("rdagent.docker", "missing",
                f"Linux Docker engine not reachable (observed {runtime or 'none'}); run scripts/start_research_runtime.sh")
        image = os.environ.get("QWB_RDAGENT_IMAGE", QWB_RDAGENT_IMAGE)
        add("rdagent.image", "ok" if self._image_present(image) else "missing",
            f"container image {image} {'present' if self._image_present(image) else 'not built'}")
        cpu, memory = self._resources()
        enough = cpu is not None and memory is not None and cpu >= 2 and memory >= 4 * 1024 ** 3
        add("rdagent.resources", "ok" if enough else "missing",
            f"docker resources cpu={cpu} mem={round((memory or 0) / 1024 ** 3, 1)}GiB (need >=2 cpu, >=4GiB)")
        snapshot = Path.home() / ".qlib/qlib_data/qwb_cn_current" / fingerprint[:12]
        if (snapshot / "instruments").is_dir() and (snapshot / "features").is_dir():
            add("rdagent.data_snapshot", "ok", f"container snapshot {snapshot.name} matches the profile fingerprint")
        else:
            add("rdagent.data_snapshot", "missing",
                "materialise the CN snapshot for this fingerprint (scripts/prepare_rdagent_demo_data.py) first")
        template = self.agent_root / "git_ignore_folder" / f"qwb_cn_factor_template_{fingerprint[:12]}"
        if not template.is_dir():
            add("rdagent.template", "unknown",
                "fingerprint template not generated yet; it will be compiled at prepare time", required_for=[])
        else:
            try:
                effective = json.loads((template / "effective.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                effective = {}
            if effective.get("fingerprint") == fingerprint:
                add("rdagent.template", "ok", f"template {template.name} matches the profile fingerprint")
            else:
                add("rdagent.template", "missing",
                    f"template {template.name} does not match the current fingerprint; delete it to recompile")
        return checks

    def outcome(self, attempt: dict[str, Any]) -> dict[str, Any]:
        mode = attempt.get("params", {}).get("mode") or ("loop" if attempt["kind"] == self.LOOP else "baseline")
        filename = "qwb_factor_loop.json" if mode == "loop" else "qwb_factor_smoke.json"
        outcome: dict[str, Any] = {
            "result_import": "manual_import_required",
            "probe": True,
            "mode": mode,
            "artifacts": {"workspace": Path(attempt["workspace"]).name},
            "notes": ["集成探针结果不等于研究结论；研究快照需经可信离线导出后进入结果库。"],
        }
        evidence_path = self.agent_root / "git_ignore_folder" / filename
        if evidence_path.is_file():
            try:
                evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                evidence = None
            if isinstance(evidence, dict):
                summary = {key: evidence[key] for key in
                           ("mode", "dataset", "metric_count", "factor_count", "factor_rows", "return_rows")
                           if key in evidence}
                summary["scenario_matches_config"] = (
                    bool(attempt.get("config_fingerprint"))
                    and evidence.get("scenario_fingerprint") == attempt.get("config_fingerprint"))
                quality = evidence.get("quality")
                if isinstance(quality, dict):
                    summary["quality"] = {key: quality.get(key) for key in
                                          ("status", "valid_ic_days", "constant_prediction_days", "trade_days")}
                outcome["evidence"] = summary
                outcome["artifacts"]["evidence"] = filename
        log_path = attempt.get("log_path")
        if log_path and Path(log_path).is_file():
            try:
                tail = Path(log_path).read_text(encoding="utf-8", errors="replace")[-LOG_BYTE_CAP:]
            except OSError:
                tail = ""
            sessions: list[str] = []
            for line in tail.splitlines():
                marker = '"research_sessions_synced"'
                if marker in line:
                    try:
                        payload = json.loads(line[line.index("{"):])
                        sessions = [str(item) for item in payload.get("research_sessions_synced", [])][:20]
                    except (ValueError, TypeError, AttributeError):
                        sessions = []
            if sessions:
                outcome["research_sessions_synced"] = sessions
        return outcome
