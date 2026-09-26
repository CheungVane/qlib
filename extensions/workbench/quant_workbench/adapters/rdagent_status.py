"""Read-only RD-Agent checkout observation; never imports or executes RD-Agent."""

from __future__ import annotations

import shutil
import subprocess
import sys
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import urlopen


class RDAgentStatusProvider:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def _config(self) -> dict[str, str]:
        env_file = self.root / ".env"
        if not env_file.is_file():
            return {}
        allowed = {"BACKEND", "CHAT_MODEL", "DEEPSEEK_API_BASE", "DEEPSEEK_API_KEY",
                   "EMBEDDING_MODEL", "LITELLM_PROXY_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_BASE"}
        config: dict[str, str] = {}
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key in allowed:
                config[key] = value.strip().strip('"\'')
        return config

    def _git(self, *args: str) -> str | None:
        try:
            result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True,
                                    text=True, timeout=3, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    @staticmethod
    def _ollama_ready(model: str, base: str) -> bool:
        parsed = urlsplit(base)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            return False
        try:
            with urlopen(base.rstrip("/") + "/api/tags", timeout=1) as response:
                models = json.load(response).get("models", [])
        except (OSError, ValueError):
            return False
        return any(item.get("name", "").split(":", 1)[0] == model for item in models)

    @staticmethod
    def _docker_runtime() -> str | None:
        if shutil.which("docker") is None:
            return None
        try:
            result = subprocess.run(["docker", "info", "--format", "{{.OSType}}/{{.Architecture}}"],
                                    capture_output=True, text=True, timeout=3, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def _trace_summaries(self) -> list[dict[str, Any]]:
        candidates: list[tuple[str, Path]] = []
        cli_root = self.root / "log"
        if cli_root.is_dir():
            candidates += [("cli", path) for path in cli_root.iterdir()
                           if path.is_dir() and not path.is_symlink() and any(path.iterdir())]
        server_root = self.root / "git_ignore_folder" / "traces"
        if server_root.is_dir():
            for scenario in server_root.iterdir():
                if scenario.is_dir() and not scenario.is_symlink():
                    candidates += [("server", path) for path in scenario.iterdir()
                                   if path.is_dir() and not path.is_symlink()]
        candidates.sort(key=lambda pair: pair[1].stat().st_mtime, reverse=True)
        result = []
        for source, path in candidates[:20]:
            result.append({"id": path.name, "source": source,
                           "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()})
        return result

    def _probe_evidence(self, mode: str) -> dict[str, Any] | None:
        filename = "qwb_factor_smoke.json" if mode == "baseline" else "qwb_factor_loop.json"
        path = self.root / "git_ignore_folder" / filename
        try:
            evidence = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(evidence, dict):
            return None
        template = evidence.get('template', '')
        if (not isinstance(template, str) or Path(template).name != template
                or not template.startswith('qwb_cn_factor_template')):
            return None
        if (evidence.get("schema_version") not in (1, 2) or evidence.get("mode") != mode
                or evidence.get("dataset") not in ("synthetic_cn_demo", "synthetic_cn_current")
                or not isinstance(evidence.get("metric_count"), int)
                or evidence["metric_count"] <= 0
                or not (self.root / "git_ignore_folder" / template).is_dir()):
            return None
        summary = {"metric_count": evidence["metric_count"], "completed_at": evidence.get("completed_at")}
        if evidence['schema_version'] == 2:
            try:
                effective = json.loads((self.root / 'git_ignore_folder' / template / 'effective.json').read_text())
                fingerprint = evidence['scenario_fingerprint']
                quality = evidence['quality']
                if (len(fingerprint) != 64 or effective['fingerprint'] != fingerprint
                        or quality['scenario_fingerprint'] != fingerprint):
                    return None
                summary['scenario_fingerprint'] = fingerprint
                summary['quality'] = {key: quality[key] for key in
                                      ('status', 'valid_ic_days', 'constant_prediction_days', 'trade_days')}
            except (OSError, ValueError, KeyError, TypeError):
                return None
        if mode == "loop":
            for key in ("factor_count", "factor_rows", "return_rows"):
                if not isinstance(evidence.get(key), int) or evidence[key] <= 0:
                    return None
                summary[key] = evidence[key]
        return summary

    def status(self) -> dict[str, Any]:
        if not (self.root / ".git").exists():
            return {"availability": "not_connected", "reason": "RD-Agent checkout 未配置或不存在",
                    "chat": {"configured": False}, "embedding": {"configured": False},
                    "execution": {"available": False, "reasons": ["checkout_missing"]}, "traces": []}
        config = self._config()
        chat_model = config.get("CHAT_MODEL") or None
        chat_key = bool(config.get("DEEPSEEK_API_KEY") or config.get("OPENAI_API_KEY"))
        embedding_model = config.get("EMBEDDING_MODEL") or None
        if embedding_model and embedding_model.startswith("ollama/"):
            embedding_ready = self._ollama_ready(
                embedding_model.removeprefix("ollama/"), config.get("OLLAMA_API_BASE", ""))
            embedding_source = "local_ollama"
        elif embedding_model and embedding_model.startswith("litellm_proxy/"):
            embedding_ready = bool(config.get("LITELLM_PROXY_API_KEY"))
            embedding_source = "litellm_proxy"
        else:
            embedding_ready = bool(embedding_model and config.get("OPENAI_API_KEY"))
            embedding_source = "other" if embedding_model else None
        linux = sys.platform.startswith("linux")
        docker_runtime = self._docker_runtime()
        linux_container = bool(docker_runtime and docker_runtime.startswith("linux/"))
        baseline = self._probe_evidence("baseline")
        agent_loop = self._probe_evidence("loop")
        if baseline and agent_loop and baseline.get('scenario_fingerprint') != agent_loop.get('scenario_fingerprint'):
            agent_loop = None
        reasons = []
        if not chat_model or not chat_key:
            reasons.append("chat_not_configured")
        if not embedding_ready:
            reasons.append("embedding_service_unavailable" if embedding_model and embedding_source == "local_ollama"
                           else "embedding_not_configured")
        if not linux and not linux_container:
            reasons.append("native_runtime_unverified")
        if not linux_container:
            reasons.append("docker_not_available")
        if baseline is None:
            reasons.extend(("factor_image_unverified", "factor_scenario_not_aligned"))
        # The workbench has no RD-Agent executor yet. Keep execution unavailable even
        # when the external checkout's prerequisites are satisfied.
        reasons.append("executor_not_integrated")
        head = self._git("rev-parse", "--short", "HEAD")
        upstream = self._git("rev-parse", "--short", "upstream/main")
        return {
            "availability": "available",
            "checkout": {"name": self.root.name, "head": head, "upstream_head": upstream,
                         "upstream_tracking": self._git("remote", "get-url", "upstream") is not None},
            "chat": {"configured": bool(chat_model and chat_key), "provider": "DeepSeek" if chat_model and
                     chat_model.startswith("deepseek/") else "other", "model": chat_model},
            "embedding": {"configured": embedding_ready, "model": embedding_model, "source": embedding_source},
            "runtime": {"linux_container_available": linux_container, "docker_server": docker_runtime},
            "baseline": {"verified": baseline is not None, **(baseline or {})},
            "agent_loop": {"verified": agent_loop is not None, **(agent_loop or {})},
            "execution": {"available": False, "reasons": reasons},
            "traces": self._trace_summaries(),
        }
