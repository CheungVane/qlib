"""Python startup hook: enforce the platform's agent call budget when it is configured.

The executor prepends this directory to PYTHONPATH only for Agent attempts and sets
QWB_AGENT_BUDGET_FILE; every other Python process is untouched. `sitecustomize` is a
standard interpreter extension point, so nothing in RD-Agent's own source tree changes.
"""
import os

if os.environ.get("QWB_AGENT_BUDGET_FILE"):
    try:
        from qwb_agent_budget import install_litellm_hook
        install_litellm_hook()
    except Exception:  # never break the child interpreter because budgeting failed to load
        if os.environ.get("QWB_AGENT_BUDGET_STRICT") == "1":
            raise
