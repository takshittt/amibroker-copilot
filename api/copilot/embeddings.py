"""Turning text into vectors for the meaning-based search.

The indexer and the search take an Embedder, so tests run with the fake
one and never call OpenAI.
"""

import hashlib
import math
import random
from typing import Any, Protocol

from copilot.config import ConfigError, Settings

_BATCH = 100


class Embedder(Protocol):
    model: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Returns one vector of `dimensions` numbers for each text, in order."""
        ...


class FakeEmbedder:
    """Repeatable vectors made from a hash of the text. For tests and offline work.

    The same text always gives the same vector, but similar texts do not
    give similar vectors, so searching by meaning is not meaningful with it.
    """

    def __init__(self, dimensions: int, model: str = "fake"):
        self.model = model
        self.dimensions = dimensions
        self.texts_embedded = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts_embedded += len(texts)
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        source = random.Random(seed)  # noqa: S311 (not for security)
        values = [source.gauss(0, 1) for _ in range(self.dimensions)]
        length = math.sqrt(sum(value * value for value in values))
        return [value / length for value in values]


class OpenAIEmbedder:
    """Embeddings from the OpenAI API. `client` is an `openai.OpenAI` object."""

    def __init__(self, client: Any, model: str, dimensions: int):
        self.client = client
        self.model = model
        self.dimensions = dimensions

    @classmethod
    def from_settings(cls, settings: Settings) -> "OpenAIEmbedder":
        if not settings.openai_api_key:
            raise ConfigError("OPENAI_API_KEY is not set")
        from openai import OpenAI  # imported here so nothing else loads the SDK

        client = OpenAI(api_key=settings.openai_api_key)
        return cls(client, settings.embedding_model, settings.embedding_dimensions)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _BATCH):
            batch = texts[start : start + _BATCH]
            response = self.client.embeddings.create(
                model=self.model, input=batch, dimensions=self.dimensions
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend(list(item.embedding) for item in ordered)
        return vectors


def vector_literal(vector: list[float]) -> str:
    """Formats a vector the way pgvector reads it: [0.1,0.2,...]."""
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"
