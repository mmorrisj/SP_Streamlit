"""
Centralised helper for loading the sentence-transformers embedding model.

Works transparently in three deployment scenarios:
  1. Online (dev): downloads from HuggingFace Hub on first use, caches locally.
  2. Docker (compose): model cached at image build time in HF_HOME.
  3. Air-gapped: model directory mounted as a volume; TRANSFORMERS_OFFLINE=1.

Usage:
    from shared.utils.model_cache import load_embedding_model
    model = load_embedding_model()              # SentenceTransformer
    # or
    from shared.utils.model_cache import get_hf_embeddings
    embeddings = get_hf_embeddings()            # LangChain HuggingFaceEmbeddings
"""

import os
import logging

logger = logging.getLogger(__name__)

# Canonical model identifier used everywhere in the project.
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Directories checked (in order) when looking for a pre-cached model.
_CANDIDATE_CACHE_DIRS = [
    os.environ.get("SENTENCE_TRANSFORMERS_HOME"),
    os.environ.get("HF_HOME"),
    "/app/.cache/huggingface",      # airgap container mount point
    os.path.expanduser("~/.cache/huggingface"),
]


def _resolve_cache_folder() -> str | None:
    """Return the first cache directory that actually contains the model, or None."""
    # The HF hub cache stores models under hub/models--<org>--<name>/
    expected_subdir = os.path.join("hub", "models--sentence-transformers--all-MiniLM-L6-v2")

    for candidate in _CANDIDATE_CACHE_DIRS:
        if candidate and os.path.isdir(os.path.join(candidate, expected_subdir)):
            logger.debug("Model cache found at %s", candidate)
            return candidate

    return None


def load_embedding_model():
    """Return a ``SentenceTransformer`` instance with correct cache settings.

    Automatically resolves the local cache directory so the model works
    in online, Docker, and air-gapped environments without code changes.
    """
    from sentence_transformers import SentenceTransformer

    cache_folder = _resolve_cache_folder()
    if cache_folder:
        logger.info("Loading embedding model from cache: %s", cache_folder)
    else:
        logger.info("Loading embedding model (will download if not cached)")

    return SentenceTransformer(MODEL_NAME, cache_folder=cache_folder)


def get_hf_embeddings():
    """Return a LangChain ``HuggingFaceEmbeddings`` instance (lazy singleton).

    Suitable for RAG / vector-store usage where LangChain wrappers are expected.
    """
    import torch
    from langchain_huggingface import HuggingFaceEmbeddings

    device = "cuda" if torch.cuda.is_available() else "cpu"
    cache_folder = _resolve_cache_folder()

    return HuggingFaceEmbeddings(
        model_name=MODEL_NAME,
        model_kwargs={"device": device},
        cache_folder=cache_folder,
    )
