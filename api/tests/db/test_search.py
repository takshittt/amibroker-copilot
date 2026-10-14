import pytest

from copilot.chunks import build_chunks
from copilot.config import DEFAULT_EMBEDDING_DIMENSIONS
from copilot.embeddings import FakeEmbedder
from copilot.search import Hit, keyword_search, vector_search


@pytest.fixture
def embedder():
    return FakeEmbedder(DEFAULT_EMBEDDING_DIMENSIONS)


def refs(hits):
    return [hit.ref for hit in hits]


# Keyword search


def test_trailing_stop_finds_apply_stop(indexed):
    hits = keyword_search(indexed, "trailing stop", kinds=["function"])
    assert hits[0].ref == "ApplyStop"
    assert isinstance(hits[0], Hit)
    assert hits[0].kind == "function"
    assert hits[0].meta["doc_url"].endswith("/applystop.html")
    assert hits[0].score > 0


def test_trailing_stop_finds_apply_stop_among_every_kind(indexed):
    assert "ApplyStop" in refs(keyword_search(indexed, "trailing stop"))


def test_exact_function_name_comes_first_among_functions(indexed):
    assert refs(keyword_search(indexed, "ApplyStop", kinds=["function"]))[0] == "ApplyStop"
    assert refs(keyword_search(indexed, "timenum", kinds=["function"]))[0] == "TimeNum"


def test_function_and_the_notes_named_after_it_lead_a_search_for_its_name(indexed):
    # A note with the name in its title is as good a match as the function itself.
    top = refs(keyword_search(indexed, "ApplyStop", limit=3))
    assert {"ApplyStop", "stops-with-applystop"} <= set(top)


def test_word_forms_match(indexed):
    # "crosses" and "averages" are found through "cross" and "average".
    assert "Cross" in refs(keyword_search(indexed, "crosses", kinds=["function"]))
    hits = keyword_search(indexed, "moving averages", kinds=["function"], limit=50)
    assert {"MA", "EMA", "WMA"} <= set(refs(hits))


def test_any_word_is_enough_and_more_words_rank_higher(indexed):
    hits = keyword_search(indexed, "exponential moving average zebra", kinds=["function"])
    # No chunk has "zebra", and the three with all the other words lead.
    assert set(refs(hits)[:3]) == {"EMA", "DEMA", "TEMA"}


def test_exact_name_beats_a_note_that_mentions_it_often(indexed):
    # hardcoded-session-times mentions TimeNum four times, but only in its body.
    found = refs(keyword_search(indexed, "TimeNum"))
    assert found[0] == "TimeNum"
    assert found.index("TimeNum") < found.index("hardcoded-session-times")


def test_kinds_limit_what_is_searched(indexed):
    mistakes = keyword_search(indexed, "ExRem arrows", kinds=["mistake"])
    assert mistakes[0].ref == "signals-without-exrem"
    assert {hit.kind for hit in mistakes} == {"mistake"}
    assert "rule-exrem" in mistakes[0].tags
    assert mistakes[0].meta["checker_rule"] == "exrem"


def test_limit_is_respected(indexed):
    assert len(keyword_search(indexed, "the array of bars", limit=5)) == 5


@pytest.mark.parametrize("query", ["", "   ", "!!! ???", "zzzqqqxxx"])
def test_queries_with_nothing_to_find(indexed, query):
    assert keyword_search(indexed, query) == []


@pytest.mark.parametrize(
    "query", ["stop'; drop table kb_chunks; --", "a & b | !c", "(trailing) <-> stop:*", "_N"]
)
def test_awkward_queries_are_searched_as_plain_words(indexed, query):
    with indexed.transaction():  # so a failure here cannot spoil the shared connection
        keyword_search(indexed, query)
    assert indexed.execute("select count(*) as n from kb_chunks").fetchone()["n"] > 0


def test_results_are_in_a_stable_order(indexed):
    assert refs(keyword_search(indexed, "stop")) == refs(keyword_search(indexed, "stop"))


# Vector search


def test_vector_search_returns_the_chunk_whose_text_was_embedded(indexed, catalog, notes, embedder):
    chunk = next(c for c in build_chunks(catalog, notes) if c.ref == "ApplyStop")
    (vector,) = embedder.embed([chunk.text])
    hits = vector_search(indexed, vector, limit=3)
    assert hits[0].ref == "ApplyStop"
    assert hits[0].score == pytest.approx(1.0)
    assert hits[1].score < 0.5


def test_vector_search_respects_kinds_and_limit(indexed, embedder):
    (vector,) = embedder.embed(["anything"])
    hits = vector_search(indexed, vector, limit=4, kinds=["mistake"])
    assert len(hits) == 4
    assert {hit.kind for hit in hits} == {"mistake"}
    assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)


def test_vector_search_with_nothing_of_that_kind(indexed, embedder):
    (vector,) = embedder.embed(["anything"])
    assert vector_search(indexed, vector, kinds=["no-such-kind"]) == []


@pytest.mark.parametrize("kind", ["mistake", "concept", "example", "error", "function"])
def test_filtered_vector_search_always_fills_the_limit(indexed, embedder, kind):
    # An approximate index applies the filter after picking its candidates
    # and can come back short or empty. Many different query vectors, so a
    # search that is only sometimes short is still caught.
    vectors = embedder.embed([f"query number {number}" for number in range(40)])
    for vector in vectors:
        hits = vector_search(indexed, vector, limit=5, kinds=[kind])
        assert len(hits) == 5
        assert {hit.kind for hit in hits} == {kind}


def test_vector_search_gives_the_true_nearest_chunks(indexed, catalog, notes, embedder):
    chunks = build_chunks(catalog, notes)
    texts = [chunk.text for chunk in chunks]
    stored = embedder.embed(texts)
    (query,) = embedder.embed(["which chunks are closest to this"])

    def similarity(vector):
        return sum(a * b for a, b in zip(query, vector, strict=True))

    ranked = sorted(zip(chunks, stored, strict=True), key=lambda pair: -similarity(pair[1]))
    expected = [(chunk.kind, chunk.ref) for chunk, _ in ranked[:10]]
    found = [(hit.kind, hit.ref) for hit in vector_search(indexed, query, limit=10)]
    assert found == expected


def test_there_is_no_approximate_index_on_the_embeddings(indexed):
    rows = indexed.execute(
        "select indexname from pg_indexes where tablename = 'kb_chunks' and indexdef ilike %s",
        ("%hnsw%",),
    ).fetchall()
    assert rows == []
