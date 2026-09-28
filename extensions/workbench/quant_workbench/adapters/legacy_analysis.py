"""Explicit migration adapter: current-profile lookup, NOT certified ARC11 resolution."""
from __future__ import annotations
from typing import Any

from pathlib import Path
from .. import factors as factor_layer, risk as risk_layer

class LegacyAnalysisConfiguration:
    def factor_snapshot_dir(self, dataset: dict[str, Any]):
        """Resolve the recorded snapshot for a dataset identity through the single config source."""
        from ..cn_market import default_profile_path, discover_project_root, load_profile
        label = (dataset or {}).get("snapshot_label")
        if not label:
            raise factor_layer.FactorError("factor dataset has no snapshot label recorded")
        root = discover_project_root()
        data_path = Path(load_profile(default_profile_path())["research"]["data_path"])
        base = data_path if data_path.is_absolute() else (root / data_path)
        return (base / label).resolve()

    def annualisation(self) -> tuple[int, str]:
        from ..cn_market import default_profile_path, load_profile
        try:
            value = int(load_profile(default_profile_path())["research"]["annualization"]
                        ["native_portfolio_days"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise risk_layer.RiskError(
                f"无法从配置读取年化交易日（{type(exc).__name__}）；按结果合同不得使用默认值") from exc
        return value, "config: configs/cn/profile.json"
