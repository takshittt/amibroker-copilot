"""What the checker takes in and gives back."""

from dataclasses import dataclass

INTRADAY_TIMEFRAMES = ("1min", "3min", "5min", "10min", "15min", "30min", "hourly")
OTHER_TIMEFRAMES = ("daily", "weekly", "monthly")


@dataclass(frozen=True)
class Context:
    """What the checker needs to know besides the code."""

    timeframe: str
    market_id: str | None = None

    def __post_init__(self) -> None:
        if self.timeframe not in INTRADAY_TIMEFRAMES + OTHER_TIMEFRAMES:
            allowed = ", ".join(INTRADAY_TIMEFRAMES + OTHER_TIMEFRAMES)
            raise ValueError(f"unknown timeframe {self.timeframe!r}; use one of: {allowed}")

    @property
    def is_intraday(self) -> bool:
        return self.timeframe in INTRADAY_TIMEFRAMES


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str  # critical, warning or tip
    line: int
    message: str
    fix_hint: str


@dataclass(frozen=True)
class Check:
    """How one rule went: passed, failed, or skipped because the code did not parse."""

    rule: str
    outcome: str


@dataclass(frozen=True)
class CheckResult:
    # passed: no Critical and no Warning. failed: at least one of them.
    # checker_error: the checker itself broke, so the code is not checked.
    status: str
    findings: tuple[Finding, ...]
    checks: tuple[Check, ...]
    error: str | None = None
