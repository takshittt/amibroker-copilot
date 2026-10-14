import json

import pytest

from copilot.config import DEFAULT_EMBEDDING_DIMENSIONS, Settings
from copilot.embeddings import FakeEmbedder
from copilot.evals import Expectation, Task, main, render, run_evals
from copilot.pipeline.llm import ScriptedLLM
from copilot.pipeline.orchestrator import Deps

SETTINGS = Settings(
    strong_model="strong-model",
    cheap_model="cheap-model",
    strong_price_in=2.0,
    strong_price_out=8.0,
    cheap_price_in=0.1,
    cheap_price_out=0.4,
)
GOOD = (
    "SetTradeDelays(1, 1, 1, 1);\n"
    "Buy = Cross(MA(Close, 20), MA(Close, 50));\n"
    "Sell = Cross(MA(Close, 50), MA(Close, 20));\n"
)
INVENTED = GOOD + "x = TrailStop(1);\n"
BRIEF = {
    "kind": "strategy",
    "goal": "Crossover.",
    "direction": "long",
    "entry": "Buy on a moving average cross.",
    "exit": "Sell on the opposite cross.",
    "stops": [],
    "sizing": "",
    "time_rules": [],
    "other_requirements": [],
}


def generation(code):
    return {
        "code": code,
        "explanation_blocks": [],
        "requirements_covered": [
            {"id": f"R{n}", "start_line": 2, "end_line": 2} for n in (1, 2, 3)
        ],
        "notes": [],
    }


def task(ident, status="checked", request="Use MA and Cross for a crossover."):
    return Task(
        id=ident,
        market="nse_eq",
        timeframe="daily",
        difficulty="easy",
        request=request,
        expect=Expectation(status=status, retrieved=["MA", "RSI"], calls=["MA", "Cross", "ATR"]),
    )


@pytest.fixture
def deps(indexed, catalog):
    def _deps(generations, briefs):
        queue = {"generation": list(generations), "brief": list(briefs)}

        def answer(call):
            if call.schema_name == "rerank":
                return {"scores": []}
            return queue[call.schema_name].pop(0)

        return Deps(
            conn=indexed,
            catalog=catalog,
            llm=ScriptedLLM(answer),
            embedder=FakeEmbedder(DEFAULT_EMBEDDING_DIMENSIONS),
            settings=SETTINGS,
        )

    return _deps


def test_metrics_over_a_small_set(deps):
    tasks = [
        task("passes-first-time"),
        task("invents-then-fixes"),
        task("never-fixes"),
        task("should-ask", status="clarify"),
    ]
    generations = [
        generation(GOOD),
        generation(INVENTED),
        generation(GOOD),
        generation(INVENTED),
        generation(INVENTED),
        generation(INVENTED),
    ]
    briefs = [BRIEF, BRIEF, BRIEF, {**BRIEF, "direction": "unknown"}]
    seen = []
    report = run_evals(tasks, deps(generations, briefs), on_task=seen.append)

    assert [o.status for o in report.outcomes] == [
        "checked",
        "checked",
        "not_fully_checked",
        "clarify",
    ]
    assert [o.id for o in seen] == [t.id for t in tasks]
    metrics = report.metrics
    assert metrics["tasks"] == 4
    assert metrics["checker_pass_rate"] == pytest.approx(2 / 3)
    assert metrics["passed_first_attempt_rate"] == pytest.approx(1 / 3)
    assert metrics["invented_function_rate_first_attempt"] == pytest.approx(2 / 3)
    assert metrics["invented_function_rate_in_answer"] == pytest.approx(1 / 3)
    # MA was named in the request, so it was given to the model; RSI was not.
    assert metrics["retrieval_recall"] == pytest.approx(0.5)
    # The code calls MA and Cross but not ATR.
    assert metrics["expected_calls_recall"] == pytest.approx(2 / 3)
    assert metrics["clarify_when_expected_rate"] == 1.0
    assert metrics["errors"] == 0
    assert metrics["average_attempts"] == pytest.approx((1 + 2 + 3) / 3)
    assert metrics["tokens_in"] > 0
    assert metrics["cost_usd"] > 0
    assert report.kb_version >= 4
    assert report.models["strong"] == "strong-model"
    assert report.outcomes[2].problems


def test_report_marks_results_that_are_not_as_expected(deps):
    report = run_evals(
        [task("fine"), task("asked-when-it-should-write")],
        deps([generation(GOOD)], [BRIEF, {**BRIEF, "entry": ""}]),
    )
    text = render(report)
    lines = {line.split()[0]: line for line in text.splitlines() if line and line[0].islower()}
    assert "not as expected" not in lines["fine"]
    assert "not as expected" in lines["asked-when-it-should-write"]
    assert "checker_pass_rate" in text


def test_measures_with_nothing_to_count_are_shown_as_not_applicable(deps):
    report = run_evals([task("only", status="clarify")], deps([], [{**BRIEF, "entry": ""}]))
    assert report.metrics["checker_pass_rate"] is None
    assert report.metrics["retrieval_recall"] is None
    assert "n/a" in render(report)


def test_command_prints_the_report_and_writes_json(deps, tmp_path, capsys):
    tasks_dir = tmp_path / "write"
    tasks_dir.mkdir()
    (tasks_dir / "sample.yaml").write_text(
        "id: sample\nmarket: nse_eq\ntimeframe: daily\ndifficulty: easy\n"
        "request: Use MA and Cross.\nexpect:\n  status: checked\n  retrieved: [MA]\n"
    )
    out = tmp_path / "report.json"
    code = main(
        ["write", str(tasks_dir), "--json", str(out)], deps=deps([generation(GOOD)], [BRIEF])
    )
    assert code == 0
    assert "sample" in capsys.readouterr().out
    saved = json.loads(out.read_text())
    assert saved["metrics"]["checker_pass_rate"] == 1.0
    assert saved["outcomes"][0]["id"] == "sample"


def test_command_reports_a_bad_task_file(deps, tmp_path, capsys):
    (tmp_path / "bad.yaml").write_text("id: bad\n")
    assert main(["write", str(tmp_path)], deps=deps([], [])) == 2
    assert "bad.yaml" in capsys.readouterr().err


# Review samples with the AI review switched on


def test_review_evals_with_the_model_score_the_ai_findings(indexed, catalog):
    from copilot.evals import Planted, ReviewSample, render_review, run_review_evals

    code = (
        "SetTradeDelays(1, 1, 1, 1);\nFast = EMA(Close, 9);\nSlow = EMA(Close, 21);\n"
        "Buy = Cross(Slow, Fast);\nSell = Cross(Fast, Slow);\n"
    )
    samples = [
        ReviewSample(
            "swapped", "nse_eq", "daily", code, (Planted("ai", line=4, description="swap"),)
        ),
        ReviewSample(
            "missed", "nse_eq", "daily", code, (Planted("ai", line=4, description="swap"),)
        ),
        ReviewSample(
            "clean", "nse_eq", "daily", code.replace("Slow, Fast);\nSell", "Fast, Slow);\nSell"), ()
        ),
    ]
    replies = [
        {
            "findings": [
                {"severity": "critical", "line": 4, "problem": "Swapped.", "fix": "Swap."}
            ],
            "summary": "",
        },
        {"findings": [], "summary": ""},
        {
            "findings": [{"severity": "tip", "line": 2, "problem": "Could be tidier.", "fix": "x"}],
            "summary": "",
        },
    ]
    deps = Deps(
        indexed, catalog, ScriptedLLM(replies), FakeEmbedder(DEFAULT_EMBEDDING_DIMENSIONS), SETTINGS
    )
    report = run_review_evals(samples, catalog, deps)
    assert report.with_ai
    assert report.metrics["ai_bugs_planted"] == 2
    assert report.metrics["ai_bugs_found"] == 1
    assert report.metrics["ai_recall"] == 0.5
    assert report.metrics["ai_findings_on_clean_samples"] == 1
    assert report.metrics["cost_usd"] > 0
    text = render_review(report)
    assert "checker and AI" in text
    assert "AI MISSED swap" in text
