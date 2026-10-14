import math
from types import SimpleNamespace

import pytest

from copilot.config import ConfigError, Settings
from copilot.embeddings import FakeEmbedder, OpenAIEmbedder, vector_literal


def test_fake_embedder_is_repeatable_and_sized():
    embedder = FakeEmbedder(dimensions=16)
    first, second, other = embedder.embed(["trailing stop", "trailing stop", "moving average"])
    assert first == second
    assert first != other
    assert len(first) == 16
    assert math.isclose(sum(value * value for value in first), 1.0)
    assert embedder.texts_embedded == 3


class StubClient:
    """Stands in for openai.OpenAI; records the calls it gets."""

    def __init__(self):
        self.calls = []
        self.embeddings = self

    def create(self, model, input, dimensions):  # noqa: A002 (the SDK's parameter name)
        self.calls.append((model, list(input), dimensions))
        data = [
            SimpleNamespace(index=position, embedding=[float(len(text)), 0.0])
            for position, text in enumerate(input)
        ]
        # The API does not promise the order, so hand it back reversed.
        return SimpleNamespace(data=list(reversed(data)))


def test_openai_embedder_passes_model_and_size_and_keeps_order():
    client = StubClient()
    embedder = OpenAIEmbedder(client, model="text-embedding-3-small", dimensions=2)
    assert embedder.embed(["a", "bbb", "cc"]) == [[1.0, 0.0], [3.0, 0.0], [2.0, 0.0]]
    assert client.calls == [("text-embedding-3-small", ["a", "bbb", "cc"], 2)]


def test_openai_embedder_sends_long_lists_in_batches():
    client = StubClient()
    embedder = OpenAIEmbedder(client, model="m", dimensions=2)
    texts = [f"text {number}" for number in range(250)]
    vectors = embedder.embed(texts)
    assert [len(call[1]) for call in client.calls] == [100, 100, 50]
    assert vectors == [[float(len(text)), 0.0] for text in texts]


def test_openai_embedder_with_nothing_to_embed_makes_no_call():
    client = StubClient()
    assert OpenAIEmbedder(client, model="m", dimensions=2).embed([]) == []
    assert client.calls == []


def test_openai_embedder_needs_a_key():
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        OpenAIEmbedder.from_settings(Settings())


def test_vector_literal():
    assert vector_literal([0.5, -1, 2]) == "[0.5,-1.0,2.0]"
