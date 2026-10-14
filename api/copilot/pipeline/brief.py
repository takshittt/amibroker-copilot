"""Step 1: the request becomes a structured brief.

The model fills the fields. Code, not the model, decides what counts as
missing, which questions to ask, and what is defaulted.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from copilot.checker import Context
from copilot.config import Settings
from copilot.kb.schema import Market
from copilot.pipeline import prompts
from copilot.pipeline.llm import LLM, UsageMeter, ask

_TEXT = {"type": "string"}
_LIST = {"type": "array", "items": {"type": "string"}}
BRIEF_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": ["strategy", "indicator", "exploration"]},
        "goal": _TEXT,
        "direction": {"type": "string", "enum": ["long", "short", "long_short", "unknown"]},
        "entry": _TEXT,
        "exit": _TEXT,
        "stops": _LIST,
        "sizing": _TEXT,
        "time_rules": _LIST,
        "other_requirements": _LIST,
    },
    "required": [
        "kind",
        "goal",
        "direction",
        "entry",
        "exit",
        "stops",
        "sizing",
        "time_rules",
        "other_requirements",
    ],
}

QUESTIONS = {
    "entry": "What should make it enter a trade?",
    "exit": "When should it close a trade?",
    "direction": "Should it trade long only, short only, or both?",
}
MAX_QUESTIONS = 2
DEFAULT_EXIT_RULE = "Close any open trade a little before the session ends"
DEFAULT_EXIT_NOTE = (
    "You gave no exit time, so the code closes open trades shortly before the session "
    "ends. Change the exit time in the parameters if you want another."
)


class _ModelBrief(BaseModel):
    """What the model returns. Nothing beyond the schema is accepted."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["strategy", "indicator", "exploration"]
    goal: str
    direction: Literal["long", "short", "long_short", "unknown"]
    entry: str
    exit: str
    stops: list[str]
    sizing: str
    time_rules: list[str]
    other_requirements: list[str]


class Brief(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Chosen by the user on the page, never by the model.
    market_id: str
    timeframe: str

    kind: Literal["strategy", "indicator", "exploration"]
    goal: str
    direction: Literal["long", "short", "long_short", "unknown"]
    entry: str
    exit: str
    stops: tuple[str, ...]
    sizing: str
    time_rules: tuple[str, ...]
    other_requirements: tuple[str, ...]
    # What the pipeline assumed on the user's behalf; shown with the answer.
    notes: tuple[str, ...] = ()

    @property
    def missing_critical(self) -> list[str]:
        """The fields without which no code is written, in the order asked."""
        if self.kind != "strategy":
            return []
        missing = []
        if not self.entry:
            missing.append("entry")
        # A stop or a time rule is a way out of a trade too.
        if not (self.exit or self.stops or self.time_rules):
            missing.append("exit")
        if self.direction == "unknown":
            missing.append("direction")
        return missing

    @property
    def questions(self) -> list[str]:
        return [QUESTIONS[name] for name in self.missing_critical][:MAX_QUESTIONS]

    @property
    def requirements(self) -> list[tuple[str, str]]:
        """Every requirement with an id (R1, R2, ...), for the model to account for."""
        texts: list[str] = []
        if self.kind == "strategy":
            direction = {"long": "long only", "short": "short only", "long_short": "long and short"}
            if self.direction in direction:
                texts.append(f"Direction: {direction[self.direction]}")
            if self.entry:
                texts.append(f"Entry: {self.entry}")
            if self.exit:
                texts.append(f"Exit: {self.exit}")
        else:
            texts.append(f"Goal: {self.goal}")
        texts.extend(f"Stop: {stop}" for stop in self.stops)
        if self.sizing:
            texts.append(f"Position size: {self.sizing}")
        texts.extend(f"Time rule: {rule}" for rule in self.time_rules)
        texts.extend(self.other_requirements)
        return [(f"R{number}", text) for number, text in enumerate(texts, start=1)]


def _clean(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in items if item.strip()))


def finish_brief(model_brief: _ModelBrief, market: Market, timeframe: str) -> Brief:
    """Adds what the user chose and applies the defaults the design allows."""
    time_rules = _clean(model_brief.time_rules)
    notes: tuple[str, ...] = ()
    intraday = Context(timeframe=timeframe).is_intraday
    if model_brief.kind == "strategy" and intraday and not market.never_closes and not time_rules:
        time_rules = (DEFAULT_EXIT_RULE,)
        notes = (DEFAULT_EXIT_NOTE,)
    return Brief(
        market_id=market.id,
        timeframe=timeframe,
        kind=model_brief.kind,
        goal=model_brief.goal.strip(),
        direction=model_brief.direction,
        entry=model_brief.entry.strip(),
        exit=model_brief.exit.strip(),
        stops=_clean(model_brief.stops),
        sizing=model_brief.sizing.strip(),
        time_rules=time_rules,
        other_requirements=_clean(model_brief.other_requirements),
        notes=notes,
    )


def wrap_block(tag: str, text: str) -> str:
    """Puts text someone else wrote inside a delimited block it cannot close early."""
    safe = text.replace(f"</{tag}", f"< /{tag}").replace(f"<{tag}", f"< {tag}")
    return f"<{tag}>\n{safe}\n</{tag}>"


def wrap_user_text(text: str) -> str:
    """The user's request, as data for the model."""
    return wrap_block("user_request", text)


def build_brief(
    llm: LLM,
    meter: UsageMeter,
    settings: Settings,
    text: str,
    market: Market,
    timeframe: str,
    previous_code: str = "",
) -> Brief:
    current = ""
    if previous_code:
        current = (
            "The trader already has the code below, and the request may be a change to it. "
            "Describe the strategy as it should be after the change.\n\n"
            f"{wrap_block('pasted_code', previous_code)}\n\n"
        )
    user = (
        f"Market: {market.name}\nTimeframe: {timeframe}\n\n{current}{wrap_user_text(text)}\n\n"
        "Write the brief for this request."
    )
    model_brief = ask(
        llm,
        meter,
        model=settings.cheap_model or "",
        system=prompts.BRIEF_SYSTEM,
        user=user,
        schema_name="brief",
        schema=BRIEF_SCHEMA,
        parse=_ModelBrief.model_validate,
        max_output_tokens=settings.max_output_tokens,
    )
    return finish_brief(model_brief, market, timeframe)
