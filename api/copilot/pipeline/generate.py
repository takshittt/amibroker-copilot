"""Step 5: write the AFL from the brief and the retrieved items."""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator

from copilot.config import Settings
from copilot.pipeline import prompts
from copilot.pipeline.brief import Brief, wrap_block, wrap_user_text
from copilot.pipeline.llm import LLM, UsageMeter, ask
from copilot.pipeline.rerank import brief_text
from copilot.pipeline.retrieve import Item

_LINES = {
    "start_line": {"type": "integer"},
    "end_line": {"type": "integer"},
}
GENERATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "code": {"type": "string"},
        "explanation_blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {**_LINES, "text": {"type": "string"}},
                "required": ["start_line", "end_line", "text"],
            },
        },
        "requirements_covered": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"id": {"type": "string"}, **_LINES},
                "required": ["id", "start_line", "end_line"],
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["code", "explanation_blocks", "requirements_covered", "notes"],
}


class ExplanationBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    text: str


class CoveredRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class Generation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str
    explanation_blocks: tuple[ExplanationBlock, ...]
    requirements_covered: tuple[CoveredRequirement, ...]
    notes: tuple[str, ...]

    @field_validator("code")
    @classmethod
    def _code_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("code must not be empty")
        return value.replace("\r\n", "\n")

    @property
    def line_count(self) -> int:
        return len(self.code.rstrip("\n").split("\n"))


@dataclass(frozen=True)
class Feedback:
    """What the last attempt wrote and what was wrong with it."""

    code: str
    problems: tuple[str, ...]


def numbered(code: str) -> str:
    lines = code.rstrip("\n").split("\n")
    return "\n".join(f"{number:>3}  {line}" for number, line in enumerate(lines, start=1))


def build_prompt(
    brief: Brief,
    text: str,
    items: list[Item],
    function_names: list[str],
    feedback: Feedback | None,
    previous_code: str = "",
) -> str:
    parts = [f"Brief:\n{brief_text(brief)}", wrap_user_text(text)]
    if previous_code:
        parts.append(
            "This request changes the trader's current code, below. Make the change asked "
            "for and keep everything else as it is.\n\n"
            + wrap_block("pasted_code", numbered(previous_code))
        )

    notes = [f"### {item.kind}: {item.title}\n{item.content}" for item in items]
    parts.append("Reference notes:\n\n" + "\n\n".join(notes))
    parts.append(
        "Function names you may use (those above have details; the rest are standard "
        "AmiBroker functions):\n" + ", ".join(function_names)
    )
    requirements = "\n".join(f"{ident}. {requirement}" for ident, requirement in brief.requirements)
    parts.append("Requirements to account for in requirements_covered, by id:\n" + requirements)
    if feedback is not None:
        problems = "\n".join(f"- {problem}" for problem in feedback.problems)
        parts.append(
            f"{prompts.REVISE_NOTE}\n\nPrevious code, with line numbers:\n"
            f"{numbered(feedback.code)}\n\nProblems:\n{problems}"
        )
    return "\n\n".join(parts)


def generate(
    llm: LLM,
    meter: UsageMeter,
    settings: Settings,
    brief: Brief,
    text: str,
    items: list[Item],
    function_names: list[str],
    feedback: Feedback | None = None,
    previous_code: str = "",
) -> Generation:
    return ask(
        llm,
        meter,
        model=settings.strong_model or "",
        system=prompts.GENERATE_SYSTEM,
        user=build_prompt(brief, text, items, function_names, feedback, previous_code),
        schema_name="generation",
        schema=GENERATION_SCHEMA,
        parse=Generation.model_validate,
        max_output_tokens=settings.max_output_tokens,
    )
