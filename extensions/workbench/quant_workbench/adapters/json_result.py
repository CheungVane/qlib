"""Engine-neutral JSON result importer."""

import json
from pathlib import Path
from typing import Any

from ..model import validate_package


class JsonResultImporter:
    adapter_version = "generic_json_v1"

    def load(self, path: str | Path) -> dict[str, Any]:
        return validate_package(json.loads(Path(path).read_text(encoding="utf-8")))
