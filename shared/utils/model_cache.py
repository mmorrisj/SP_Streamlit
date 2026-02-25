"""
Centralised helper for loading the sentence-transformers embedding model.

Works transparently in three deployment scenarios:
  1. Online (dev): downloads from HuggingFace Hub on first use, caches locally.
  2. Docker (compose): model cached at image build time in HF_HOME.
  3. Production: model directory mounted as a volume; TRANSFORMERS_OFFLINE=1.

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

# Subdirectory used by production-build.sh for a clean, symlink-free model copy.
_DIRECT_MODEL_SUBDIR = os.path.join("models", "all-MiniLM-L6-v2")

# HF Hub cache directory name (used when cache_dir is passed explicitly).
_HUB_CACHE_MODEL_DIR = "models--sentence-transformers--all-MiniLM-L6-v2"

# Directories checked (in order) when looking for a pre-cached model.
_CANDIDATE_CACHE_DIRS = [
    os.environ.get("SENTENCE_TRANSFORMERS_HOME"),
    os.environ.get("HF_HOME"),
    "/app/.cache/huggingface",      # production container mount point
    os.path.expanduser("~/.cache/huggingface"),
]

# Files that indicate a usable sentence-transformers model directory.
_ST_MARKER_FILES = ("modules.json", "config_sentence_transformers.json")


def _find_hub_snapshot(model_cache_dir: str) -> str | None:
    """Find a usable model snapshot inside an HF Hub cache directory.

    HF Hub stores models as:
      <cache_dir>/snapshots/<commit_hash>/<model_files>

    After symlink resolution (production transfers), the snapshot directory
    contains real files instead of symlinks to blobs/.  This function
    locates such a snapshot and returns its path.
    """
    snapshots_dir = os.path.join(model_cache_dir, "snapshots")
    if not os.path.isdir(snapshots_dir):
        return None
    try:
        for entry in os.listdir(snapshots_dir):
            snap_path = os.path.join(snapshots_dir, entry)
            if not os.path.isdir(snap_path):
                continue
            # Prefer a full sentence-transformers save (has modules.json)
            for marker in _ST_MARKER_FILES:
                if os.path.isfile(os.path.join(snap_path, marker)):
                    logger.debug("HF Hub snapshot found at %s", snap_path)
                    return snap_path
            # Accept a snapshot that at least has config.json (plain transformer)
            if os.path.isfile(os.path.join(snap_path, "config.json")):
                logger.debug("HF Hub snapshot (transformer-only) found at %s", snap_path)
                return snap_path
    except OSError:
        pass
    return None


def _resolve_model_path() -> str | None:
    """Return a direct path to a saved model directory, or None.

    Resolution order per candidate directory:
      1. Clean model.save() copy at ``models/all-MiniLM-L6-v2/`` (preferred).
      2. HF Hub cache snapshot at ``models--org--name/snapshots/<hash>/``.
      3. HF Hub cache snapshot at ``hub/models--org--name/snapshots/<hash>/``.

    The snapshot fallback is critical for production deployments where the
    package was built before the model.save() step was added, or where the
    HF Hub cache metadata (refs/blobs) is corrupted after transfer.
    """
    for candidate in _CANDIDATE_CACHE_DIRS:
        if not candidate:
            continue

        # Check 1: Direct model.save() copy (most robust)
        direct_path = os.path.join(candidate, _DIRECT_MODEL_SUBDIR)
        if os.path.isfile(os.path.join(direct_path, "modules.json")):
            logger.debug("Direct model found at %s", direct_path)
            return direct_path

        # Check 2: HF Hub snapshot — cache_dir layout (no hub/ prefix)
        snap = _find_hub_snapshot(os.path.join(candidate, _HUB_CACHE_MODEL_DIR))
        if snap:
            return snap

        # Check 3: HF Hub snapshot — HF_HOME layout (hub/ prefix)
        snap = _find_hub_snapshot(
            os.path.join(candidate, "hub", _HUB_CACHE_MODEL_DIR)
        )
        if snap:
            return snap

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


def _log_search_diagnostics() -> None:
    """Log all candidate paths and what was found (or not) for debugging."""
    logger.warning("Model '%s' not found locally. Paths checked:", MODEL_NAME)
    for candidate in _CANDIDATE_CACHE_DIRS:
        if not candidate:
            continue
        direct = os.path.join(candidate, _DIRECT_MODEL_SUBDIR)
        hub_direct = os.path.join(candidate, _HUB_CACHE_MODEL_DIR)
        hub_nested = os.path.join(candidate, "hub", _HUB_CACHE_MODEL_DIR)
        logger.warning(
            "  %s/models/all-MiniLM-L6-v2/ exists=%s  "
            "models--*/ exists=%s  hub/models--*/ exists=%s",
            candidate,
            os.path.isdir(direct),
            os.path.isdir(hub_direct),
            os.path.isdir(hub_nested),
        )
    logger.warning(
        "If production, ensure the hf_model/ directory is mounted at "
        "/app/.cache/huggingface and contains models/all-MiniLM-L6-v2/modules.json"
    )


def load_embedding_model():
    """Return a ``SentenceTransformer`` instance with correct cache settings.

    Automatically resolves the local cache directory so the model works
    in online, Docker, and production environments without code changes.

    Resolution order:
      1. Direct model save (production-build.sh ``model.save()`` copy — no symlinks)
      2. HF Hub cache snapshot (snapshots/<hash>/ inside the cache directory)
      3. HF Hub cache via SentenceTransformer cache_folder parameter
      4. Online download (if network available)
    """
    from sentence_transformers import SentenceTransformer

    # Prefer direct model path (most robust for production / transferred deploys)
    model_path = _resolve_model_path()
    if model_path:
        logger.info("Loading embedding model from local path: %s", model_path)
        return SentenceTransformer(model_path)

    # Fall back to HF Hub cache (let SentenceTransformer navigate the cache)
    cache_folder = _resolve_cache_folder()
    if cache_folder:
        logger.info("Loading embedding model from HF cache: %s", cache_folder)
    else:
        _log_search_diagnostics()
        logger.info("Loading embedding model (will download if not cached)")

    return SentenceTransformer(MODEL_NAME, cache_folder=cache_folder)


def get_hf_embeddings():
    """Return a LangChain ``HuggingFaceEmbeddings`` instance (lazy singleton).

    Suitable for RAG / vector-store usage where LangChain wrappers are expected.
    """
    import torch
    from langchain_huggingface import HuggingFaceEmbeddings

    device = "cuda" if torch.cuda.is_available() else "cpu"

    # Prefer direct model path (most robust for production / transferred deploys)
    model_path = _resolve_model_path()
    if model_path:
        logger.info("Loading HF embeddings from local path: %s", model_path)
        return HuggingFaceEmbeddings(
            model_name=model_path,
            model_kwargs={"device": device},
        )

    # Fall back to HF Hub cache
    cache_folder = _resolve_cache_folder()
    if not cache_folder:
        _log_search_diagnostics()

    return HuggingFaceEmbeddings(
        model_name=MODEL_NAME,
        model_kwargs={"device": device},
        cache_folder=cache_folder,
    )
