"""Production composition root. Construction performs no engine execution."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from .application import WorkbenchService
from .adapters.attempt_import import AttemptResultImporter
from .adapters.executors import QlibCNExecutor, RDAgentExecutor
from .adapters.rdagent_status import RDAgentStatusProvider
from .adapters.storage.storage import LocalResultRepository
from .services.execution import ExecutionService
from .ports.research import ManagedAdmissionPort, AdmissionPreflightPort
from .research import ResearchSnapshots
from .adapters.legacy_analysis import LegacyAnalysisConfiguration

def default_analysis_configuration():
    return LegacyAnalysisConfiguration()

@dataclass(frozen=True)
class WorkbenchSettings:
    """Explicit directory settings; only from_environment reads process defaults."""
    storage_root: Path
    data_root: Path
    agent_root: str | None = None

    @classmethod
    def from_environment(cls, root: Path) -> "WorkbenchSettings":
        data_root = Path(os.environ.get("QWB_DATA_ROOT")
                         or (Path.home() / ".qlib" / "qlib_data")).expanduser()
        return cls(root, data_root, os.environ.get("QWB_RDAGENT_ROOT"))


def build_service(root: Path, with_executors: bool = True) -> WorkbenchService:
    """Existing CLI/public factory; environment values are resolved once here."""
    return build_workbench(WorkbenchSettings.from_environment(root), with_executors=with_executors)


def build_workbench(settings: WorkbenchSettings, *, with_executors: bool = True,
                    managed_admission: ManagedAdmissionPort | None = None,
                    managed_preflight: AdmissionPreflightPort | None = None) -> WorkbenchService:
    """Compose concrete adapters. No sample import, data download or engine start."""
    if (managed_admission is None) != (managed_preflight is None):
        raise ValueError("managed admission and preflight must be supplied together")
    if managed_admission is not None and not with_executors:
        raise ValueError("managed execution requires an execution service")
    root = settings.storage_root
    repository = LocalResultRepository(root)
    agent_root = settings.agent_root
    observer = RDAgentStatusProvider(agent_root) if agent_root else None
    execution = None
    if with_executors:
        from .execution_policy import agent_limits, child_limits, load_policy
        policy = load_policy()
        limits = {**child_limits(policy), **agent_limits(policy)}
        execution = ExecutionService(repository,
                                     executors=[QlibCNExecutor(limits=limits),
                                                RDAgentExecutor(limits=limits, budget_root=root / "agent_budget")],
                                     importer=AttemptResultImporter(repository), policy=policy,
                                     managed_admission=managed_admission,
                                     managed_preflight=managed_preflight)
    from .adapters.local_data_directory import LocalDataDirectory
    from .adapters.snapshot_analysis import SnapshotAnalysisDirectory
    data_root = settings.data_root
    registry = data_root / "_registry"
    directory = LocalDataDirectory(registry, data_root) if registry.is_dir() else None
    return WorkbenchService(repository, observer, ResearchSnapshots(root / "research"), execution,
                            directory, analysis_configuration=default_analysis_configuration(),
                            factor_data=SnapshotAnalysisDirectory(registry, data_root))
