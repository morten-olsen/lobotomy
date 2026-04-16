"""Embedding model loading and text encoding."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def load_model(model_name: str = "all-MiniLM-L6-v2"):
    """Load a sentence-transformers model. Cached across calls."""
    # Suppress noisy library logging
    for name in ("sentence_transformers", "transformers", "torch", "huggingface_hub"):
        logging.getLogger(name).setLevel(logging.WARNING)

    # Avoid tokenizer parallelism warnings in subprocess contexts
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def embed_texts(texts: list[str], model_name: str = "all-MiniLM-L6-v2") -> NDArray[np.float32]:
    """Embed a batch of texts. Returns array of shape (n, dim)."""
    if not texts:
        return np.empty((0, 0), dtype=np.float32)
    model = load_model(model_name)
    embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    return embeddings.astype(np.float32)


def embed_query(query: str, model_name: str = "all-MiniLM-L6-v2") -> NDArray[np.float32]:
    """Embed a single query string. Returns 1-D vector."""
    model = load_model(model_name)
    embedding = model.encode(query, show_progress_bar=False, convert_to_numpy=True)
    return embedding.astype(np.float32)


def get_dimension(model_name: str = "all-MiniLM-L6-v2") -> int:
    """Return the embedding dimension for the given model."""
    model = load_model(model_name)
    return model.get_embedding_dimension()
