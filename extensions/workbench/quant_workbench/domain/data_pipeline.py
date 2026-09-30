"""Per-source subdivision of an already frozen platform data plan."""
from dataclasses import dataclass
from .artifacts import ArtifactRef, require_id


@dataclass(frozen=True)
class SourceFetchPlan:
    data_plan_ref: ArtifactRef
    source_id: str
    capability_ref: ArtifactRef
    chunk_keys: tuple[str, ...]

    def __post_init__(self):
        self.data_plan_ref.require_type('data_plan')
        self.capability_ref.require_type('capability_record')
        require_id(self.source_id)
        if not isinstance(self.chunk_keys, tuple) or not self.chunk_keys:
            raise ValueError('source plan requires immutable chunk keys')
        if len(set(self.chunk_keys)) != len(self.chunk_keys):
            raise ValueError('duplicate source chunk')
        for key in self.chunk_keys:
            require_id(key)
