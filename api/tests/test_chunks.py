from pathlib import Path

import pytest

from copilot.chunks import Chunk, build_chunks, signature
from copilot.kb import Notes, load_catalog, load_notes
from copilot.kb.schema import ConceptNote, ErrorNote, ExampleRecord

KB_DIR = Path(__file__).resolve().parents[2] / "kb"


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(KB_DIR)


@pytest.fixture(scope="module")
def chunks(catalog):
    return build_chunks(catalog, load_notes(KB_DIR))


def by_key(chunks):
    return {(chunk.kind, chunk.ref): chunk for chunk in chunks}


def test_signature_shows_optional_and_variadic_arguments(catalog):
    assert signature(catalog.function("MA")) == "MA(array, periods)"
    assert signature(catalog.function("RSI")) == "RSI([periods])"
    assert signature(catalog.function("TimeNum")) == "TimeNum()"
    assert signature(catalog.function("StrFormat")) == "StrFormat(formatstr, ...)"


def test_function_chunk(chunks, catalog):
    chunk = by_key(chunks)[("function", "ApplyStop")]
    assert chunk.title == "ApplyStop"
    assert chunk.content.startswith("ApplyStop(type, mode, amount, [exitatstop]")
    assert catalog.function("ApplyStop").description in chunk.content
    assert chunk.tags == ("stops",)
    assert chunk.meta["doc_url"].endswith("/applystop.html")


def test_only_described_functions_get_a_chunk(chunks, catalog):
    described = {f.name for f in catalog.functions.values() if f.description}
    assert {c.ref for c in chunks if c.kind == "function"} == described
    assert ("function", "GfxArc") not in by_key(chunks)


def test_mistake_chunk_carries_its_rule(chunks):
    chunk = by_key(chunks)[("mistake", "look-ahead-ref")]
    assert "rule-lookahead_ref" in chunk.tags
    assert chunk.meta == {"checker_rule": "lookahead_ref", "timeframe": "daily"}
    assert "Wrong:" in chunk.content
    assert "Right:" in chunk.content
    assert "Ref(Close, 1)" in chunk.content


def test_keys_are_unique(chunks):
    assert len(by_key(chunks)) == len(chunks)


def test_hash_changes_with_title_or_content_only():
    base = Chunk("concept", "a", "Title", "Body", ("x",), {"k": 1})
    assert base.content_hash == Chunk("concept", "a", "Title", "Body", ("y",), {}).content_hash
    assert base.content_hash != Chunk("concept", "a", "Title", "Body!", ("x",)).content_hash
    assert base.content_hash != Chunk("concept", "a", "Title 2", "Body", ("x",)).content_hash
    assert base.text == "Title\nBody"


def test_concepts_examples_and_errors_become_chunks(catalog):
    notes = Notes(
        concepts={"arrays": ConceptNote(id="arrays", title="Arrays", content="Whole arrays.")},
        examples={
            "ma-cross": ExampleRecord(
                id="ma-cross",
                title="MA cross",
                timeframe="daily",
                market="nse_eq",
                description="Buys on a cross.",
                code="Buy = 1;\n",
                tags=["crossover"],
            )
        },
        errors={
            "error-29": ErrorNote(
                id="error-29", code=29, title="No value", explanation="Never set.", fix="Set it."
            )
        },
    )
    found = by_key([chunk for chunk in build_chunks(catalog, notes) if chunk.kind != "function"])
    assert found[("concept", "arrays")].content == "Whole arrays."
    example = found[("example", "ma-cross")]
    assert example.content == "Buys on a cross.\n\nBuy = 1;"
    assert example.meta == {"timeframe": "daily", "market": "nse_eq"}
    error = found[("error", "error-29")]
    assert error.content == "Never set.\n\nFix: Set it."
    assert error.meta == {"code": 29}
