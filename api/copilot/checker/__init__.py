"""The AFL checker: deterministic, no AI and no network."""

from copilot.checker.engine import check
from copilot.checker.findings import Check, CheckResult, Context, Finding

__all__ = ["Check", "CheckResult", "Context", "Finding", "check"]
