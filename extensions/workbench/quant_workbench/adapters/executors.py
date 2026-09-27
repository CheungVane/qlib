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
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..cn_market import (
    CN_SYNTHETIC_DATASET_ID, CN_SYNTHETIC_SOURCE_INSTANCE, discover_project_root, load_profile,
    rdagent_snapshot_path,
)
from ..execution import InvalidExecutionRequest
from ..execution_policy import container_flags
from ..source_safety import Sanitizer

PREFLIGHT_TTL_SECONDS = 15.0
LOG_BYTE_CAP = 200_000
COMPILE_TIMEOUT = 180
ENGINE_IMAGE = "qwb-qlib-cpu:local"
RDAGENT_ENGINE_IMAGE = "qwb-rdagent-cpu:local"
QWB_RDAGENT_IMAGE = RDAGENT_ENGINE_IMAGE  # legacy alias; QWB_RDAGENT_IMAGE overrides it
CONTAINER_NAME_PREFIX = "qwb"
CONTAINER_RUN_DIR = "/qwb/run"
CONTAINER_DATA_DIR = "/qwb/data"
CONTAINER_SOURCE_DIR = "/qwb/src"
CONTAINER_AGENT_DIR = "/qwb/agent"
CONTAINER_REPO_DIR = "/qwb/repo"
CONTAINER_HOOK_DIR = "/qwb/hooks"
CONTAINER_PLATFORM_DIR = "/qwb/platform"
CONTAINER_HOME_QLIB = "/root/.qlib"
AGENT_BUDGET_HOOK_DIR = Path(__file__).resolve().parents[2] / "hooks" / "agent_budget"


def container_name(executor_id: str, attempt_id: str) -> str:
    """Deterministic container name so cancel can clean up without extra persistence."""
    slug = "".join(ch if ch.isalnum() or ch in "-." else "-" for ch in f"{executor_id}-{attempt_id}")
    return f"{CONTAINER_NAME_PREFIX}-{slug[:48]}"


def container_command(*, name: str, image: str, workdir: str, mounts, inner: list[str],
                      limits: dict[str, Any] | None = None,
                      env: dict[str, str] | None = None) -> list[str]:
    """`docker run` invocation that carries the policy limits into the container.

    Mounts keep the same absolute paths inside and outside so the compiled engine config
    needs no rewriting; `--rm` plus a named container makes cleanup deterministic.
    """
    command = ["docker", "run", "--rm", "--init", "--name", name,
               *container_flags(limits or {})]
    for key, value in (env or {}).items():
        command += ["-e", f"{key}={value}"]
    for source, target, mode in mounts:
        command += ["-v", f"{source}:{target}:{mode}"]
    command += ["-w", str(workdir), image, *inner]
    return command


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def find_repo_root(explicit: str | Path | None = None) -> Path:
    """Single implementation lives in cn_market (config layer, no engine imports)."""
    return discover_project_root(explicit)


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


def _read_marker(path: Path) -> tuple[str | None, int | None]:
    """Return (resource_limit, exit_code). The wrapper writes the literal string on a
    resource-limit kill because the numeric code may never be produced."""
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None, None
    if value == "resource_limit":
        return "resource_limit", None
    try:
        return None, int(value)
    except ValueError:
        return None, None


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

    def __init__(self, repo_root: str | Path | None = None, source_root: str | Path | None = None,
                 limits: dict[str, Any] | None = None):
        self.repo_root = find_repo_root(repo_root)
        self.source_root = Path(source_root).expanduser().resolve() if source_root else self.repo_root
        # Resource limits the policy asked us to enforce on the child process.
        self.limits = dict(limits or {})
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

    # -- container route (EXEC13) ----------------------------------------
    def containerized(self) -> bool:
        """True when this executor runs the attempt inside a container."""
        return False

    def container_route(self, attempt_id: str, kind: str, params: dict[str, Any],
                        run_dir: Path) -> dict[str, Any] | None:
        """Hook: return the container spec for this attempt, or None for a host process."""
        return None

    def engine_image(self) -> str:
        return os.environ.get("QWB_ENGINE_IMAGE") or ENGINE_IMAGE

    def docker_runtime(self) -> str | None:
        if shutil.which("docker") is None:
            return None
        result = _run(["docker", "info", "--format", "{{.OSType}}/{{.Architecture}}"], timeout=5)
        return result.stdout.strip() if result and result.returncode == 0 else None

    def image_present(self, image: str) -> bool:
        result = _run(["docker", "image", "inspect", image, "--format", "{{.Id}}"], timeout=10)
        return bool(result and result.returncode == 0 and result.stdout.strip())

    def image_id(self, image: str) -> str | None:
        result = _run(["docker", "image", "inspect", image, "--format", "{{.Id}}"], timeout=10)
        return result.stdout.strip() if result and result.returncode == 0 else None

    def pool_memory(self) -> int | None:
        result = _run(["docker", "info", "--format", "{{.MemTotal}}"], timeout=5)
        if result is None or result.returncode != 0:
            return None
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None

    def pool_cpu_count(self) -> int | None:
        result = _run(["docker", "info", "--format", "{{.NCPU}}"], timeout=5)
        if result is None or result.returncode != 0:
            return None
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None

    def _remove_container(self, name: str) -> None:
        """Best-effort cleanup: killing the docker client alone can leave the container up."""
        if not self.containerized() or shutil.which("docker") is None:
            return
        try:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            pass

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
        payload = {
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
        route = self.container_route(attempt_id, kind, normalized, run_dir)
        if route:
            payload["container"] = route
        return payload

    def start(self, attempt_id: str, prepared: dict[str, Any]) -> dict[str, Any]:
        run_dir = Path(prepared["workspace"])
        log_path = Path(prepared["log_path"])
        marker = Path(prepared["exit_marker"])
        log_path.touch(exist_ok=True)
        preamble = "umask 022\n"
        cpu_limit = (self.limits.get("cpu_seconds") or (None,))[0]
        # A containerized attempt carries RLIMIT_CPU through `docker run --ulimit cpu=`, so the
        # host-side `ulimit -t` must not be applied to the docker client itself.
        if cpu_limit and not prepared.get("container"):
            # POSIX sh: ulimit -t is RLIMIT_CPU in seconds — verified to kill runaway children.
            preamble += f"ulimit -t {int(cpu_limit)}\n"
            # A CPU-limit kill may prevent the numeric marker from being written; trap the
            # catchable signal so the platform can classify the end instead of guessing.
            preamble += (f"trap 'printf %s resource_limit > {shlex.quote(str(marker))}; exit 152' "
                         "XCPU\n")
        wrapper = (
            preamble
            +
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
        return {"pid": process.pid, "workspace": str(run_dir), "log_path": str(log_path),
                "limits": dict(self.limits)}

    def poll(self, attempt: dict[str, Any]) -> dict[str, Any]:
        attempt_id = attempt["attempt_id"]
        run_dir = Path(attempt.get("workspace") or "")
        code = _read_int(run_dir / "exit_code")
        handle = self._processes.get(attempt_id)
        if code == 152:  # 128 + SIGXCPU(24): the child itself was stopped by the CPU limit
            finished = self._processes.pop(attempt_id, None)
            if finished is not None:
                finished.poll()  # reap, so a completed attempt does not linger as a warning
            return {"state": "failed", "exit_code": 152, "error_code": "resource_limit",
                    "error_message": "terminated by the enforced CPU limit",
                    "ended_at": _now(), "evidence": {"exit_marker": True, "exit_code": 152}}
        if code == 137 and (self.limits.get("memory_bytes") or self.limits.get("cpu_seconds")):
            # 128 + SIGKILL: inside a container this is the cgroup OOM kill or the hard
            # RLIMIT_CPU kill (the soft SIGXCPU handler may not survive to write a marker).
            # Both are enforced resource limits, so they must not read as "nonzero_exit".
            finished = self._processes.pop(attempt_id, None)
            if finished is not None:
                finished.poll()
            return {"state": "failed", "exit_code": 137, "error_code": "resource_limit",
                    "error_message": "terminated by an enforced resource limit",
                    "ended_at": _now(),
                    "evidence": {"exit_marker": True, "exit_code": 137,
                                 "containerized": bool(self.containerized()),
                                 "limits": {name: values[0] for name, values in self.limits.items()}}}
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
        marker_kind, _ = _read_marker(run_dir / "exit_code")
        if marker_kind == "resource_limit":
            return {"state": "failed", "exit_code": None, "error_code": "resource_limit",
                    "error_message": "terminated by the enforced CPU limit",
                    "ended_at": _now(), "evidence": {"exit_marker": True, "kind": marker_kind}}
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
        # Even a confirmed host-process end is not enough for a containerized attempt: the
        # container is a separate object in the VM, so ask Docker to remove it by its
        # deterministic name (best effort; useless if the container never started).
        self._remove_container(container_name(self.executor_id, attempt_id))
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

    def __init__(self, repo_root: str | Path | None = None, profile_path: str | Path | None = None,
                 limits: dict[str, Any] | None = None):
        super().__init__(repo_root, limits=limits)
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
            "description": "按 configs/cn/profile.json 编译独立工作目录，在受限容器内用 Qlib 运行"
                           "（内存=cgroup 硬上限，CPU=RLIMIT_CPU）；成功后平台自动发布结果并写回执。",
            "probe": False,
            "data_nature": "synthetic_current_rules_counterfactual",
            # EXEC12: the platform publishes this entry's result automatically.
            "result_destination": "auto_import",
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
        # EXEC13: the attempt runs in a container so the memory cap is a cgroup limit. The
        # image (not the checkout's .venv) is the engine runtime and its ID is the version
        # evidence recorded with the attempt.
        image = self.engine_image()
        runtime = self.docker_runtime()
        if runtime is None:
            add("cn.container", "missing",
                "Docker engine is not reachable; start it with scripts/start_research_runtime.sh")
        elif not runtime.startswith("linux/"):
            add("cn.container", "missing",
                f"Docker engine runs {runtime} containers; the Qlib image needs linux/")
        elif not self.image_present(image):
            add("cn.container", "missing",
                f"container image {image} is not built; run scripts/build_rdagent_cpu_image.sh")
        else:
            image_id = self.image_id(image) or "unknown-id"
            limit = (self.limits.get("memory_bytes") or (None,))[0]
            pool = self.pool_memory()
            if limit and pool and pool < limit:
                add("cn.container", "missing",
                    f"image {image} ({image_id[:19]}) but pool memory {pool} < enforced limit {limit}")
            else:
                add("cn.container", "ok",
                    f"image {image} ({image_id[:19]}); pool memory "
                    f"{round((pool or 0) / 1024 ** 3, 1)}GiB, enforced limit "
                    f"{round((limit or 0) / 1024 ** 3, 1) if limit else 'none'}GiB")
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

    def containerized(self) -> bool:
        return True

    def container_route(self, attempt_id: str, kind: str, params: dict[str, Any],
                        run_dir: Path) -> dict[str, Any] | None:
        """Fixed container paths; the compiled workflow is rewritten to match them.

        Same-path bind mounts are not reliable on this host (colima serves them
        intermittently), so the container only ever sees paths we hand it explicitly.
        """
        bundle = self.bundle()
        data_dir = (self.repo_root / bundle["research"]["data_path"]).resolve()
        source_root = (self.repo_root / "extensions" / "workbench").resolve()
        mounts: list[tuple[str, str, str]] = [
            (str(run_dir), CONTAINER_RUN_DIR, "rw"),
            (str(data_dir), CONTAINER_DATA_DIR, "ro"),
            (str(source_root), CONTAINER_SOURCE_DIR, "ro"),
        ]
        image = self.engine_image()
        return {"name": container_name(self.executor_id, attempt_id), "image": image,
                "image_id": self.image_id(image), "workdir": CONTAINER_RUN_DIR,
                "mounts": mounts, "data_dir": str(data_dir),
                "paths": {str(data_dir): CONTAINER_DATA_DIR, str(run_dir): CONTAINER_RUN_DIR,
                          str(source_root): CONTAINER_SOURCE_DIR}}

    def command(self, attempt_id: str, kind: str, params: dict[str, Any], run_dir: Path) -> list[str]:
        route = self.container_route(attempt_id, kind, params, run_dir) or {}
        return container_command(
            name=route.get("name") or container_name(self.executor_id, attempt_id),
            image=route.get("image") or self.engine_image(),
            workdir=route.get("workdir") or CONTAINER_RUN_DIR,
            mounts=route.get("mounts") or [(str(run_dir), CONTAINER_RUN_DIR, "rw")],
            inner=["qrun", f"{CONTAINER_RUN_DIR}/workflow.yaml"],
            limits=self.limits,
            # The mounted checkout must win over the copy baked into the image, otherwise the
            # container would run stale platform code from build time.
            env={"PYTHONPATH": CONTAINER_SOURCE_DIR},
        )

    def prepare_extra(self, attempt_id: str, kind: str, params: dict[str, Any], run_dir: Path) -> dict[str, Any]:
        compile_script = self.repo_root / "scripts" / "prepare_cn_scenario.py"
        result = _run([sys.executable, str(compile_script), "--target", "qlib", "--profile", str(self.profile_path),
                       "--out-dir", str(run_dir)], timeout=COMPILE_TIMEOUT)
        if result is None or result.returncode != 0:
            detail = (result.stderr if result else "compiler did not start").strip().splitlines()
            raise InvalidExecutionRequest(
                "CN scenario compile failed: " + (detail[-1] if detail else "unknown error"))
        workflow = run_dir / "workflow.yaml"
        if not workflow.is_file():
            raise InvalidExecutionRequest("CN scenario compile produced no workflow.yaml")
        self._rewrite_for_container(attempt_id, kind, params, run_dir)
        return {"workflow": str(workflow)}

    def _rewrite_for_container(self, attempt_id: str, kind: str,
                               params: dict[str, Any], run_dir: Path) -> None:
        """Point the compiled workflow at the container's mount paths.

        Fail-closed: any remaining host-absolute path means the mapping is incomplete, and
        running such a workflow would silently read the wrong (or no) data.
        """
        route = self.container_route(attempt_id, kind, params, run_dir) or {}
        mapping: dict[str, str] = route.get("paths") or {}
        if not mapping:
            return
        workflow = run_dir / "workflow.yaml"
        text = workflow.read_text(encoding="utf-8")
        for host, inside in sorted(mapping.items(), key=lambda item: -len(item[0])):
            text = text.replace(host, inside)
        leftovers = sorted({token for token in ("/Users/", str(Path.home())) if token in text})
        if leftovers:
            detail = [line.strip() for line in text.splitlines() if leftovers[0] in line][:3]
            raise InvalidExecutionRequest(
                "compiled workflow still points at host paths "
                f"({', '.join(leftovers)}): {' | '.join(detail)}")
        workflow.write_text(text, encoding="utf-8")

    def _normalize_container_paths(self, run_dir: Path) -> dict[str, Any] | None:
        """Map the container's own mount paths back to this host directory.

        MLflow records the artifact location it sees, which inside the container is
        `/qwb/run/...`; the platform reads the attempt workspace on the host, so the recorded
        prefix must be normalized or the result import cannot find the files. Only path
        strings change — metrics, parameters and artifact bytes are untouched.
        """
        record: dict[str, Any] = {"from": CONTAINER_RUN_DIR, "to": str(run_dir),
                                  "db_rows": 0, "meta_files": 0}
        database = run_dir / "mlflow.db"
        if database.is_file():
            connection = sqlite3.connect(database)
            try:
                for table, column in (("experiments", "artifact_location"),
                                      ("runs", "artifact_uri")):
                    cursor = connection.execute(
                        f"update {table} set {column} = replace({column}, ?, ?) "
                        f"where {column} like ?",
                        (CONTAINER_RUN_DIR, str(run_dir), CONTAINER_RUN_DIR + "%"))
                    record["db_rows"] += cursor.rowcount
                connection.commit()
            finally:
                connection.close()
        for meta in (run_dir / "mlruns").rglob("meta.yaml"):
            try:
                text = meta.read_text(encoding="utf-8")
            except OSError:
                continue
            if CONTAINER_RUN_DIR in text:
                meta.write_text(text.replace(CONTAINER_RUN_DIR, str(run_dir)), encoding="utf-8")
                record["meta_files"] += 1
        if not record["db_rows"] and not record["meta_files"]:
            return None
        return record

    def outcome(self, attempt: dict[str, Any]) -> dict[str, Any]:
        run_dir = Path(attempt["workspace"])
        outcome: dict[str, Any] = {
            "result_import": "manual_import_required",
            "data_nature": "synthetic_current_rules_counterfactual",
            "artifacts": {"workspace": run_dir.name},
            "notes": ["执行成功不代表研究有效；结果进入结果库仍需显式导入并声明行情性质。"],
        }
        normalized = self._normalize_container_paths(run_dir)
        if normalized:
            outcome["container_paths_normalized"] = normalized
        route = self.container_route(attempt["attempt_id"], attempt["kind"],
                                     attempt.get("params") or {}, run_dir)
        if route:
            # Engine version evidence: the image ID pins what actually ran (the checkout's
            # .venv is no longer the runtime, so "current environment" must not be implied).
            outcome["engine"] = {
                "engine": "qlib", "runtime": "container", "image": route["image"],
                "image_id": route["image_id"],
                "limits": {name: values[0] for name, values in self.limits.items()},
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
        dataset_path = run_dir / "dataset.json"
        synthetic = True
        dataset_id, dataset_version = CN_SYNTHETIC_DATASET_ID, None
        if effective_path.is_file():
            try:
                synthetic = bool(json.loads(effective_path.read_text(encoding="utf-8"))["research"]["synthetic"])
            except (OSError, ValueError, KeyError, TypeError):
                synthetic = True
        if dataset_path.is_file():
            try:
                registered = json.loads(dataset_path.read_text(encoding="utf-8"))
                dataset_id = registered.get("dataset_id") or dataset_id
                dataset_version = registered.get("dataset_version")
            except (OSError, ValueError, TypeError):
                dataset_version = None
        return {
            "importer": "qlib_mlflow",
            "source_instance_id": CN_SYNTHETIC_SOURCE_INSTANCE,
            "external_id": run_ids[-1],
            "tracking_uri": f"sqlite:///{tracking}",
            "dataset_id": dataset_id,
            "dataset_version": dataset_version,
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
                 profile_path: str | Path | None = None, limits: dict[str, Any] | None = None,
                 budget_root: str | Path | None = None):
        super().__init__(repo_root, limits=limits)
        self.agent_root = Path(agent_root or os.environ.get("QWB_RDAGENT_ROOT")
                               or self.repo_root.parent / "RD-Agent").expanduser().resolve()
        self.sanitizer = Sanitizer(self.agent_root)
        self.profile_path = (Path(profile_path).expanduser().resolve() if profile_path
                             else self.repo_root / "configs/cn/profile.json")
        # The execution-time call ledger lives outside the checkout, next to the platform
        # database; the child only writes this file, never the platform database.
        self.budget_root = (Path(budget_root).expanduser().resolve() if budget_root
                            else self.repo_root / ".data" / "workbench" / "agent_budget")
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
            "description": ("在受限容器内运行单轮因子演化循环并同步研究快照；驱动与因子代码同一容器，"
                            "内存=cgroup 硬上限、CPU=RLIMIT_CPU、LLM 调用按政策计数；使用本地 .env 的聊天与 embedding 配置。"
                            if mode == "loop" else
                            "在受限容器内运行因子基线回测（不发聊天请求）并同步研究快照；内存/CPU 由容器强制。"),
            "probe": True,
            "data_nature": "synthetic_probe",
            # EXEC12: research snapshots enter the result library through the trusted export.
            "result_destination": "manual_export_required",
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
        if self.agent_call_enforcement() and not self.containerized():
            # Decoupled hook: sitecustomize wraps litellm.completion inside RD-Agent's own
            # interpreter, so no upstream source changes are needed.
            env["PYTHONPATH"] = os.pathsep.join(
                [str(AGENT_BUDGET_HOOK_DIR), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
            env["QWB_AGENT_BUDGET_FILE"] = str(self.call_ledger_path())
            env["QWB_AGENT_BUDGET_LIMIT"] = str(self.call_limit())
            env["QWB_AGENT_BUDGET_STRICT"] = "1"
        return env

    def agent_call_enforcement(self) -> bool:
        return True

    def call_limit(self) -> int:
        return int((self.limits.get("agent_max_calls") or (0,))[0] or 0)

    def call_ledger_path(self) -> Path:
        scope = str((self.limits.get("agent_scope") or ("policy_revision",))[0] or "policy_revision")
        revision = str((self.limits.get("policy_revision") or ("unversioned",))[0] or "unversioned")
        safe = "".join(char if char.isalnum() or char in "-._" else "-" for char in revision)
        return self.budget_root / f"{safe}-{scope}.json"

    def seed_call_ledger(self, *, attempts_seen: int = 0) -> dict[str, Any]:
        """Top the ledger up from the durable count before an Agent attempt starts.

        Imported lazily so the platform package never imports the hook at module load.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "qwb_agent_budget", AGENT_BUDGET_HOOK_DIR / "qwb_agent_budget.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module.seed(path=self.call_ledger_path(), limit=self.call_limit(),
                           used=attempts_seen, scope=str((self.limits.get("agent_scope")
                                                          or ("policy_revision",))[0]))

    def agent_budget_report(self, attempt: dict[str, Any]) -> dict[str, Any] | None:
        """EXEC13: what the execution-time ledger says about this scope, for reconciliation."""
        if not self.agent_call_enforcement():
            return None
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "qwb_agent_budget", AGENT_BUDGET_HOOK_DIR / "qwb_agent_budget.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        state = module.read_state(self.call_ledger_path())
        events = [event for event in state.get("events", [])
                  if event.get("attempt_id") == attempt.get("attempt_id")]
        attempt_used = sum(int(event.get("units") or 0) for event in events)
        if not state.get("used") and not attempt_used:
            return None
        return {"kind": "calls", "used": int(state.get("used") or 0), "limit": self.call_limit(),
                "scope": str((self.limits.get("agent_scope") or ("policy_revision",))[0]),
                "attempt_used": attempt_used,
                "status": "budget_exhausted" if state.get("blocked_at") else "within_budget",
                "blocked_by_this_attempt": state.get("blocked_attempt") == attempt.get("attempt_id"),
                "blocked_at": state.get("blocked_at")}

    def cwd(self, kind: str, run_dir: Path) -> Path:
        return self.agent_root

    def containerized(self) -> bool:
        return True

    def image(self) -> str:
        return os.environ.get("QWB_RDAGENT_IMAGE") or RDAGENT_ENGINE_IMAGE

    def container_route(self, attempt_id: str, kind: str, params: dict[str, Any],
                        run_dir: Path) -> dict[str, Any] | None:
        """One bounded container carries the whole attempt: driver + factor code.

        The checkout is mounted rw because RD-Agent owns its git-ignored work directories; the
        repository, the Qlib snapshot and the budget hook are read-only. `~/.qlib` is mounted
        at the container's own home so the compiled template's `~` path resolves unchanged.
        """
        home_qlib = Path.home() / ".qlib"
        source_root = (self.repo_root / "extensions" / "workbench").resolve()
        platform_root = self.budget_root.parent
        mounts: list[tuple[str, str, str]] = [
            (str(self.agent_root), CONTAINER_AGENT_DIR, "rw"),
            (str(self.repo_root), CONTAINER_REPO_DIR, "ro"),
            (str(AGENT_BUDGET_HOOK_DIR), CONTAINER_HOOK_DIR, "ro"),
            (str(platform_root), CONTAINER_PLATFORM_DIR, "rw"),
        ]
        if home_qlib.is_dir():
            mounts.append((str(home_qlib), CONTAINER_HOME_QLIB, "ro"))
        return {"name": container_name(self.executor_id, attempt_id), "image": self.image(),
                "image_id": self.image_id(self.image()), "workdir": CONTAINER_AGENT_DIR,
                "mounts": mounts, "source_root": str(source_root)}

    def container_environment(self, attempt_id: str | None = None) -> dict[str, str]:
        """Env for the container: platform wiring plus a host-reachable Ollama base."""
        env = {
            "QWB_REPO_ROOT": CONTAINER_REPO_DIR,
            "QWB_RDAGENT_ROOT": CONTAINER_AGENT_DIR,
            "QWB_RDAGENT_IN_CONTAINER": "1",
            "QWB_PLATFORM_ROOT": CONTAINER_PLATFORM_DIR,
            "QWB_AGENT_BUDGET_FILE": f"{CONTAINER_PLATFORM_DIR}/{self.budget_root.name}/"
                                     f"{self.call_ledger_path().name}",
            "QWB_AGENT_BUDGET_LIMIT": str(self.call_limit()),
            "QWB_AGENT_BUDGET_STRICT": "1",
            # Attribution: the ledger records which attempt spent each call.
            "QWB_ATTEMPT_ID": str(attempt_id or ""),
            "PYTHONPATH": f"{CONTAINER_HOOK_DIR}:{CONTAINER_REPO_DIR}/extensions/workbench",
        }
        configured = _read_env_file(self.agent_root / ".env")
        base = configured.get("OLLAMA_API_BASE") or ""
        if base:
            # The embedding server runs on the macOS host, not inside the VM.
            parsed = urlsplit(base)
            if parsed.hostname in {"127.0.0.1", "localhost", "0.0.0.0"}:
                base = urlunsplit(parsed._replace(netloc=f"host.lima.internal:{parsed.port or 11434}"))
        env["OLLAMA_API_BASE"] = base or "http://host.lima.internal:11434"
        return env

    def command(self, attempt_id: str, kind: str, params: dict[str, Any], run_dir: Path) -> list[str]:
        mode = params.get("mode") or ("loop" if kind == self.LOOP else "baseline")
        route = self.container_route(attempt_id, kind, params, run_dir) or {}
        return container_command(
            name=route.get("name") or container_name(self.executor_id, attempt_id),
            image=route.get("image") or self.image(),
            workdir=CONTAINER_AGENT_DIR,
            mounts=route.get("mounts") or [(str(self.agent_root), CONTAINER_AGENT_DIR, "rw")],
            inner=["python", f"{CONTAINER_REPO_DIR}/scripts/run_rdagent_factor_smoke.py",
                   "--mode", mode],
            limits=self.limits,
            env=self.container_environment(attempt_id),
        )

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
        # EXEC13: the whole attempt (driver + factor code) runs in one container, so the policy
        # memory/CPU limits are real cgroup/RLIMIT limits rather than declarations.
        image = self.image()
        runtime = self.docker_runtime()
        limit = (self.limits.get("memory_bytes") or (None,))[0]
        if runtime is None or not runtime.startswith("linux/"):
            add("rdagent.limits", "missing",
                f"the RD-Agent attempt runs in a container, but the Docker engine is not a "
                f"reachable linux/ engine (observed {runtime or 'none'}); run "
                f"scripts/start_research_runtime.sh")
        elif not self.image_present(image):
            add("rdagent.limits", "missing",
                f"RD-Agent container image {image} is not built; run "
                f"scripts/build_rdagent_runner_image.sh")
        else:
            add("rdagent.limits", "ok",
                f"attempt runs in {image} with --memory={round((limit or 0) / 1024 ** 3, 1) if limit else 'none'}GiB "
                f"and --ulimit cpu={self.limits.get('cpu_seconds', (None,))[0] or 'none'}")
        hook = AGENT_BUDGET_HOOK_DIR / "sitecustomize.py"
        helper = AGENT_BUDGET_HOOK_DIR / "qwb_agent_budget.py"
        ledger_dir = self.call_ledger_path().parent
        if not (hook.is_file() and helper.is_file()):
            add("rdagent.call_budget", "missing",
                f"agent call-budget hook is incomplete under {AGENT_BUDGET_HOOK_DIR.name}/")
        elif not self.call_limit():
            add("rdagent.call_budget", "missing", "policy has no agent_max_calls value to enforce")
        else:
            try:
                ledger_dir.mkdir(parents=True, exist_ok=True)
                writable = os.access(ledger_dir, os.W_OK)
            except OSError:
                writable = False
            add("rdagent.call_budget", "ok" if writable else "missing",
                f"litellm hook + file ledger ({self.call_ledger_path().name}, limit "
                f"{self.call_limit()})" if writable else
                f"agent call ledger is not writable: {ledger_dir}")
        runtime = self.docker_runtime()
        if runtime and runtime.startswith("linux/"):
            add("rdagent.docker", "ok", f"Linux Docker engine {runtime}")
        else:
            add("rdagent.docker", "missing",
                f"Linux Docker engine not reachable (observed {runtime or 'none'}); run scripts/start_research_runtime.sh")
        add("rdagent.image", "ok" if self.image_present(image) else "missing",
            f"container image {image} {'present' if self.image_present(image) else 'not built'}")
        cpu, memory = self.pool_cpu_count(), self.pool_memory()
        enough = cpu is not None and memory is not None and cpu >= 2 and memory >= 4 * 1024 ** 3
        add("rdagent.resources", "ok" if enough else "missing",
            f"docker resources cpu={cpu} mem={round((memory or 0) / 1024 ** 3, 1)}GiB (need >=2 cpu, >=4GiB)")
        snapshot = rdagent_snapshot_path(fingerprint)
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
            "engine": {"engine": "rdagent", "runtime": "container", "image": self.image(),
                       "image_id": self.image_id(self.image()),
                       "limits": {name: values[0] for name, values in self.limits.items()}},
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
