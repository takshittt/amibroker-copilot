"""Turns the knowledge base into the pieces of text that retrieval searches."""

import hashlib
from dataclasses import dataclass, field

from copilot.kb import Catalog, Notes
from copilot.kb.schema import FunctionRecord


@dataclass(frozen=True)
class Chunk:
    kind: str  # function, concept, example, mistake or error
    ref: str  # the function name or the note's id
    title: str
    content: str
    tags: tuple[str, ...] = ()
    meta: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        """What is embedded and hashed."""
        return f"{self.title}\n{self.content}"

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def signature(function: FunctionRecord) -> str:
    """`ApplyStop(type, mode, amount, [exitatstop], ...)`: optional ones in brackets."""
    parts = [f"[{p.name}]" if p.optional else p.name for p in function.params]
    if function.variadic:
        parts.append("...")
    return f"{function.name}({', '.join(parts)})"


def build_chunks(catalog: Catalog, notes: Notes) -> list[Chunk]:
    """One chunk for each described function and for each note.

    A function with no description has nothing to search for, so it gets
    no chunk. It is still in the function list and found by exact lookup.
    """
    chunks: list[Chunk] = []
    for function in catalog.functions.values():
        if not function.description:
            continue
        chunks.append(
            Chunk(
                kind="function",
                ref=function.name,
                title=function.name,
                content=f"{signature(function)}\n{function.description}",
                tags=(function.category,),
                meta={
                    "category": function.category,
                    "returns": function.returns,
                    "doc_url": function.doc_url,
                },
            )
        )
    for mistake in notes.mistakes.values():
        rule_tags = (f"rule-{mistake.checker_rule}",) if mistake.checker_rule else ()
        chunks.append(
            Chunk(
                kind="mistake",
                ref=mistake.id,
                title=mistake.title,
                content=(
                    f"{mistake.explanation.strip()}\n\nWrong:\n{mistake.bad_example.strip()}"
                    f"\n\nRight:\n{mistake.good_example.strip()}"
                ),
                tags=tuple(mistake.tags) + rule_tags,
                meta={"checker_rule": mistake.checker_rule, "timeframe": mistake.timeframe},
            )
        )
    for concept in notes.concepts.values():
        chunks.append(
            Chunk("concept", concept.id, concept.title, concept.content, tuple(concept.tags))
        )
    for example in notes.examples.values():
        chunks.append(
            Chunk(
                kind="example",
                ref=example.id,
                title=example.title,
                content=f"{example.description.strip()}\n\n{example.code.strip()}",
                tags=tuple(example.tags),
                meta={"timeframe": example.timeframe, "market": example.market},
            )
        )
    for error in notes.errors.values():
        chunks.append(
            Chunk(
                kind="error",
                ref=error.id,
                title=error.title,
                content=f"{error.explanation.strip()}\n\nFix: {error.fix.strip()}",
                tags=tuple(error.tags),
                meta={"code": error.code},
            )
        )
    return chunks
