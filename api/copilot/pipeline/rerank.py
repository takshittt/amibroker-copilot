"""Step 4: keep only the candidates most useful for this brief.

One call scores every candidate against the whole brief. If that call
fails, the search order is used instead: reranking improves the context
but the pipeline can run without it.
"""

from pydantic import BaseModel, ConfigDict

from copilot.config import Settings
from copilot.pipeline import prompts
from copilot.pipeline.brief import Brief
from copilot.pipeline.llm import LLM, LLMError, UsageMeter, ask
from copilot.pipeline.retrieve import Item

RERANK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"id": {"type": "integer"}, "score": {"type": "integer"}},
                "required": ["id", "score"],
            },
        }
    },
    "required": ["scores"],
}
_PREVIEW_CHARS = 600


class _Score(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    score: int


class _Scores(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scores: list[_Score]


def brief_text(brief: Brief) -> str:
    lines = [f"Market: {brief.market_id}", f"Timeframe: {brief.timeframe}", f"Kind: {brief.kind}"]
    lines.append(f"Goal: {brief.goal}")
    lines.extend(f"{ident}. {text}" for ident, text in brief.requirements)
    return "\n".join(lines)


def rerank(
    llm: LLM, meter: UsageMeter, settings: Settings, brief: Brief, candidates: list[Item]
) -> tuple[list[Item], str | None]:
    """Returns the kept candidates, best first, and a note if reranking failed."""
    keep = settings.rerank_keep
    if len(candidates) <= keep:
        return candidates, None

    notes = "\n\n".join(
        f"[{number}] {item.kind}: {item.title}\n{item.content[:_PREVIEW_CHARS]}"
        for number, item in enumerate(candidates, start=1)
    )
    try:
        scores = ask(
            llm,
            meter,
            model=settings.cheap_model or "",
            system=prompts.RERANK_SYSTEM,
            user=f"Brief:\n{brief_text(brief)}\n\nNotes:\n\n{notes}",
            schema_name="rerank",
            schema=RERANK_SCHEMA,
            parse=_Scores.model_validate,
            max_output_tokens=settings.max_output_tokens,
        )
    except LLMError as error:
        return candidates[:keep], f"Reranking failed ({error.kind}); the search order was used."

    by_id = {score.id: score.score for score in scores.scores}
    # A candidate the model left out counts as not useful. Ties keep the search order.
    order = sorted(range(len(candidates)), key=lambda index: (-by_id.get(index + 1, 0), index))
    return [candidates[index] for index in order[:keep]], None
