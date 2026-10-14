"""An offline demonstration of the API, for building and testing the website
without an OpenAI key. Never for production.

    OFFLINE_DEMO=1 uv run python -m copilot.api.offline

It runs the real API (the real checker, database, Redis, quota and
stream) with a scripted model in place of OpenAI and made-up vectors in
place of embeddings. It starts only with OFFLINE_DEMO=1, listens only on
127.0.0.1, and says in every answer that the answer is scripted.
"""

import os
import re
import sys
import time

import redis
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from copilot.api.app import Services, create_app
from copilot.config import ConfigError, load_settings
from copilot.db.kb import load_catalog_from_db
from copilot.embeddings import FakeEmbedder
from copilot.pipeline.llm import ScriptedCall, ScriptedLLM

OFFLINE_NOTE = (
    "Offline demo: this answer was written by a script, not by the AI model. "
    "The checks on it are real."
)
HOST = "127.0.0.1"
PORT = int(os.environ.get("OFFLINE_PORT", "8000"))

WRITE_CODE = """\
_SECTION_BEGIN("MA crossover");

FastLen = Param("Fast average", 20, 5, 100, 1);
SlowLen = Param("Slow average", 50, 10, 300, 1);

SetTradeDelays(1, 1, 1, 1);
SetPositionSize(10, spsPercentOfEquity);

Fast = MA(Close, FastLen);
Slow = MA(Close, SlowLen);

Buy = Cross(Fast, Slow);
Sell = Cross(Slow, Fast);
BuyPrice = Open;
SellPrice = Open;

Buy = ExRem(Buy, Sell);
Sell = ExRem(Sell, Buy);

Plot(Close, "Close", colorDefault, styleCandle);
Plot(Fast, "Fast", colorGreen, styleLine);
Plot(Slow, "Slow", colorRed, styleLine);
PlotShapes(Buy * shapeUpArrow, colorGreen, 0, Low);
PlotShapes(Sell * shapeDownArrow, colorRed, 0, High);

_SECTION_END();
"""

EXPLANATION = [
    (3, 4, "The two average lengths are parameters, so you can change them without editing code."),
    (6, 7, "Trades fill at the next bar's open, and each trade uses 10% of the account."),
    (9, 10, "The fast and slow simple moving averages of the close."),
    (12, 15, "Buy when the fast average crosses above the slow one; sell on the cross back down."),
    (17, 18, "ExRem keeps the first signal of each run, so the chart shows one arrow per trade."),
    (20, 24, "Price as candles, both averages, and an arrow on each entry and exit."),
]


def _lines(code: str) -> int:
    return len(code.rstrip("\n").split("\n"))


def _answer(call: ScriptedCall) -> dict:
    """A fixed answer for each step. Slow enough that the progress steps show."""
    time.sleep(0.6)
    if call.schema_name == "brief":
        wants_more = "?" in call.user or len(call.user) < 200
        return {
            "kind": "strategy",
            "goal": "A moving-average crossover strategy.",
            "direction": "unknown" if wants_more and "long" not in call.user.lower() else "long",
            "entry": "Buy when the fast average crosses above the slow average.",
            "exit": "Sell when the fast average crosses back below.",
            "stops": [],
            "sizing": "",
            "time_rules": [],
            "other_requirements": [],
        }
    if call.schema_name == "rerank":
        return {"scores": []}
    if call.schema_name == "generation":
        ids = re.findall(r"^(R\d+)\. ", call.user, re.MULTILINE)
        return {
            "code": WRITE_CODE,
            "explanation_blocks": [
                {"start_line": a, "end_line": b, "text": text} for a, b, text in EXPLANATION
            ],
            "requirements_covered": [
                {"id": ident, "start_line": 12, "end_line": 13} for ident in dict.fromkeys(ids)
            ],
            "notes": [OFFLINE_NOTE],
        }
    if call.schema_name == "review":
        line = next((n for n, text in _numbered(call.user) if re.search(r"Cross\(", text)), 1)
        return {
            "findings": [
                {
                    "severity": "warning",
                    "line": line,
                    "problem": "Check that the two arguments of Cross are in the order you mean: "
                    "it is true when the first line rises above the second.",
                    "fix": "Swap them if this signal should fire on the cross downwards.",
                }
            ],
            "summary": OFFLINE_NOTE,
        }
    if call.schema_name == "rewrite":
        return {
            "code": WRITE_CODE,
            "changes": [{"line": 12, "text": "Replaced the signals with a checked crossover."}],
            "notes": [OFFLINE_NOTE],
        }
    raise AssertionError(f"no scripted answer for {call.schema_name}")


def _numbered(prompt: str) -> list[tuple[int, str]]:
    block = prompt.split("<pasted_code>", 1)[-1].split("</pasted_code>", 1)[0]
    found = []
    for line in block.splitlines():
        match = re.match(r"^\s*(\d+)  (.*)$", line)
        if match:
            found.append((int(match.group(1)), match.group(2)))
    return found


def create_offline_app():
    if os.environ.get("OFFLINE_DEMO") != "1":
        raise ConfigError("The offline demo starts only with OFFLINE_DEMO=1.")
    settings = load_settings()
    for name, value in (("DATABASE_URL", settings.database_url), ("REDIS_URL", settings.redis_url)):
        if not value:
            raise ConfigError(f"{name} must be set")
    settings = settings.__class__(
        **{
            **settings.__dict__,
            "strong_model": "offline-script",
            "cheap_model": "offline-script",
        }
    )
    pool = ConnectionPool(settings.database_url, kwargs={"row_factory": dict_row}, open=True)
    with pool.connection() as conn:
        catalog = load_catalog_from_db(conn)
    services = Services(
        settings=settings,
        pool=pool,
        redis=redis.Redis.from_url(settings.redis_url),
        catalog=catalog,
        llm=ScriptedLLM(_answer),
        embedder=FakeEmbedder(settings.embedding_dimensions),
    )
    return create_app(services)


def main() -> int:
    try:
        app = create_offline_app()
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 2
    import uvicorn

    print(f"Offline demo API on http://{HOST}:{PORT}. Answers are scripted.", file=sys.stderr)
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
