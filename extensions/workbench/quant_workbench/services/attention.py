"""Attention projections from recorded attempts; never starts work."""
from __future__ import annotations
from typing import Any

from ..ports import AttemptRepository
from .. import factors as factor_layer

class AttentionService:
    def __init__(self, repository: AttemptRepository, execution_enabled: bool):
        self.repository = repository
        self.execution_service = True if execution_enabled else None

    def attention(self, limit: int = 20) -> dict[str, Any]:
        """What the operator should look at next, from state we actually have."""
        items: list[dict[str, Any]] = []
        if self.execution_service is not None:
            for row in self.repository.list_attempts(limit=100)["items"]:
                outcome = row.get("outcome") or {}
                imported = outcome.get("result_import") if isinstance(outcome, dict) else None
                attempt = row["attempt_id"][:8]
                if row["status"] in ("failed", "interrupted"):
                    items.append({"kind": "execution_failed", "severity": "high",
                                  "title": f"执行{ '失败' if row['status']=='failed' else '中断'}：{row['label']}",
                                  "detail": row.get("error_message") or row.get("error_code") or "原因未记录",
                                  "target": {"view": "agent", "history": "attempts"}, "ref": attempt})
                elif row["status"] == "running" and row.get("cancel_requested_at"):
                    items.append({"kind": "cancel_pending", "severity": "medium",
                                  "title": f"取消请求中：{row['label']}",
                                  "detail": "等待执行器确认进程结束；未确认前状态仍是运行中",
                                  "target": {"view": "agent", "history": "attempts"}, "ref": attempt})
                elif row["status"] == "succeeded" and isinstance(imported, dict) and \
                        imported.get("status") in ("failed", "manual_import_required"):
                    items.append({"kind": "result_not_imported", "severity": "medium",
                                  "title": f"结果未入库：{row['label']}",
                                  "detail": imported.get("reason") or "需要显式导入或可信离线导出",
                                  "target": {"view": "agent", "history": "attempts"}, "ref": attempt})
                elif row["status"] == "succeeded" and row.get("probe"):
                    items.append({"kind": "probe_result", "severity": "low",
                                  "title": f"探针结果：{row['label']}",
                                  "detail": "集成探针只验证链路，不代表研究成果",
                                  "target": {"view": "agent", "history": "attempts"}, "ref": attempt})
        counts = {"high": 0, "medium": 0, "low": 0}
        for item in items:
            counts[item["severity"]] = counts.get(item["severity"], 0) + 1
        return {"items": items[:limit], "total": len(items), "counts": counts,
                "scope": "来自已记录的执行与结果状态；未接入项（数据新鲜度、实时行情）不在此列",
                "generated_at": factor_layer.utc_now()}
