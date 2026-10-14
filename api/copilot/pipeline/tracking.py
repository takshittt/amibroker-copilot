"""The trace of one pipeline run: attempts, tokens, cost and time.

Shared by Write, Review and Fix-from-error. Stage 7 writes the record to
the `runs` table.
"""

import time
from dataclasses import dataclass, field

from copilot.config import Settings
from copilot.embeddings import Embedder
from copilot.kb import Catalog
from copilot.pipeline.llm import UsageMeter


@dataclass(frozen=True)
class AttemptRecord:
    number: int
    failed_rules: tuple[str, ...]
    problem_count: int


@dataclass(frozen=True)
class RunRecord:
    """The trace of one run. Stage 7 writes it to the `runs` table."""

    attempts: int = 0
    history: tuple[AttemptRecord, ...] = ()
    calls: dict = field(default_factory=dict)
    tokens_in: dict = field(default_factory=dict)
    tokens_out: dict = field(default_factory=dict)
    cost_usd: float | None = None
    latency_ms: int = 0
    model_versions: dict = field(default_factory=dict)
    kb_version: int = 0
    retrieved: tuple[tuple[str, str], ...] = ()  # (kind, ref) of every item given to the model
    notes: tuple[str, ...] = ()


def cost(meter: UsageMeter, settings: Settings) -> float | None:
    """Dollars spent on model calls, or None when a price is not configured."""
    prices = {
        settings.strong_model: (settings.strong_price_in, settings.strong_price_out),
        settings.cheap_model: (settings.cheap_price_in, settings.cheap_price_out),
    }
    total = 0.0
    for model in meter.calls:
        price_in, price_out = prices.get(model, (None, None))
        if price_in is None or price_out is None:
            return None
        total += meter.tokens_in.get(model, 0) * price_in / 1_000_000
        total += meter.tokens_out.get(model, 0) * price_out / 1_000_000
    return round(total, 6)


class Tracker:
    """Collects what happens during one run and turns it into a RunRecord."""

    def __init__(self, settings: Settings, catalog: Catalog, embedder: Embedder):
        self.settings = settings
        self.meter = UsageMeter()
        self.history: list[AttemptRecord] = []
        self.notes: list[str] = []
        self.given: dict[tuple[str, str], None] = {}
        self._catalog = catalog
        self._embedder = embedder
        self._started = time.monotonic()

    def attempt(self, failed_rules: tuple[str, ...], problem_count: int) -> None:
        self.history.append(AttemptRecord(len(self.history) + 1, failed_rules, problem_count))

    def record(self) -> RunRecord:
        settings = self.settings
        return RunRecord(
            attempts=len(self.history),
            history=tuple(self.history),
            calls=dict(self.meter.calls),
            tokens_in=dict(self.meter.tokens_in),
            tokens_out=dict(self.meter.tokens_out),
            cost_usd=cost(self.meter, settings),
            latency_ms=int((time.monotonic() - self._started) * 1000),
            model_versions={
                "strong": settings.strong_model,
                "cheap": settings.cheap_model,
                "embedding": self._embedder.model,
            },
            kb_version=self._catalog.kb_version,
            retrieved=tuple(self.given),
            notes=tuple(self.notes),
        )
