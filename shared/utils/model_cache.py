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

# Subdirectory used by airgap-build.sh for a clean, symlink-free model copy.
_DIRECT_MODEL_SUBDIR = os.path.join("models", "all-MiniLM-L6-v2")

# HF Hub cache directory name (used when cache_dir is passed explicitly).
_HUB_CACHE_MODEL_DIR = "models--sentence-transformers--all-MiniLM-L6-v2"

# Directories checked (in order) when looking for a pre-cached model.
_CANDIDATE_CACHE_DIRS = [
    os.environ.get("SENTENCE_TRANSFORMERS_HOME"),
    os.environ.get("HF_HOME"),
    "/app/.cache/huggingface",      # airgap container mount point
    os.path.expanduser("~/.cache/huggingface"),
]


def _resolve_model_path() -> str | None:
    """Return a direct path to a saved model directory, or None.

    Checks for a clean model.save() copy created by airgap-build.sh.
    This is the most robust path for air-gapped deployments because
    it contains no symlinks and doesn't depend on HF Hub cache structure.
    """
    for candidate in _CANDIDATE_CACHE_DIRS:
        if not candidate:
            continue
        direct_path = os.path.join(candidate, _DIRECT_MODEL_SUBDIR)
        if os.path.isfile(os.path.join(direct_path, "modules.json")):
            logger.debug("Direct model found at %s", direct_path)
            return direct_path
    return None


def _resolve_cache_folder() -> str | None:
    """Return the cache_dir to pass to SentenceTransformer/HuggingFaceEmbeddings.

    When cache_dir is passed explicitly to huggingface_hub, models are stored
    directly under cache_dir/models--<org>--<name>/ (no ``hub/`` subdirectory).
    When HF_HOME is used implicitly, models are under HF_HOME/hub/models--<org>--<name>/.

    This function checks for both layouts and returns the correct root.
    """
    for candidate in _CANDIDATE_CACHE_DIRS:
        if not candidate:
            continue
        # Layout 1: cache_dir style (models--org--name/ directly under candidate)
        if os.path.isdir(os.path.join(candidate, _HUB_CACHE_MODEL_DIR)):
            logger.debug("Model cache (direct layout) found at %s", candidate)
            return candidate
        # Layout 2: HF_HOME style (hub/models--org--name/ under candidate)
        hub_path = os.path.join(candidate, "hub")
        if os.path.isdir(os.path.join(hub_path, _HUB_CACHE_MODEL_DIR)):
            logger.debug("Model cache (HF_HOME layout) found at %s", hub_path)
            return hub_path

    return None


def load_embedding_model():
    """Return a ``SentenceTransformer`` instance with correct cache settings.

    Automatically resolves the local cache directory so the model works
    in online, Docker, and air-gapped environments without code changes.

    Resolution order:
      1. Direct model save (airgap-build.sh ``model.save()`` copy — no symlinks)
      2. HF Hub cache (either cache_dir or HF_HOME layout)
      3. Online download (if network available)
    """
    from sentence_transformers import SentenceTransformer

    # Prefer direct model path (most robust for air-gapped / transferred deploys)
    model_path = _resolve_model_path()
    if model_path:
        logger.info("Loading embedding model from direct path: %s", model_path)
        return SentenceTransformer(model_path)

    # Fall back to HF Hub cache
    cache_folder = _resolve_cache_folder()
    if cache_folder:
        logger.info("Loading embedding model from HF cache: %s", cache_folder)
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

    # Prefer direct model path (most robust for air-gapped / transferred deploys)
    model_path = _resolve_model_path()
    if model_path:
        logger.info("Loading HF embeddings from direct path: %s", model_path)
        return HuggingFaceEmbeddings(
            model_name=model_path,
            model_kwargs={"device": device},
        )

    # Fall back to HF Hub cache
    cache_folder = _resolve_cache_folder()

    return HuggingFaceEmbeddings(
        model_name=MODEL_NAME,
        model_kwargs={"device": device},
        cache_folder=cache_folder,
    )
