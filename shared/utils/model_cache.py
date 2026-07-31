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


def _get_device() -> str:
    """Return 'cuda', 'mps', or 'cpu' based on what's available."""
    import torch
    if torch.cuda.is_available():
        device = "cuda"
    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    logger.info("Embedding device selected: %s", device)
    return device

# Canonical model identifier used everywhere in the project.
# nomic-embed-text-v1.5: 768-dim, 8192-token context, Apache 2.0 license.
MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"

# Subdirectory used by production-build.sh for a clean, symlink-free model copy.
_DIRECT_MODEL_SUBDIR = os.path.join("models", "nomic-embed-text-v1.5")

# HF Hub cache directory name (used when cache_dir is passed explicitly).
_HUB_CACHE_MODEL_DIR = "models--nomic-ai--nomic-embed-text-v1.5"

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
      1. Clean model.save() copy at ``models/nomic-embed-text-v1.5/`` (preferred).
      2. HF Hub cache snapshot at ``models--nomic-ai--nomic-embed-text-v1.5/snapshots/<hash>/``.
      3. HF Hub cache snapshot at ``hub/models--nomic-ai--nomic-embed-text-v1.5/snapshots/<hash>/``.

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
            "  %s/models/nomic-embed-text-v1.5/ exists=%s  "
            "models--*/ exists=%s  hub/models--*/ exists=%s",
            candidate,
            os.path.isdir(direct),
            os.path.isdir(hub_direct),
            os.path.isdir(hub_nested),
        )
    logger.warning(
        "If production, ensure the hf_model/ directory is mounted at "
        "/app/.cache/huggingface and contains models/nomic-embed-text-v1.5/modules.json"
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

    device = _get_device()

    # Prefer direct model path (most robust for production / transferred deploys)
    model_path = _resolve_model_path()
    if model_path:
        logger.info("Loading embedding model from local path: %s", model_path)
        return SentenceTransformer(model_path, trust_remote_code=True, device=device)

    # Fall back to HF Hub cache (let SentenceTransformer navigate the cache)
    cache_folder = _resolve_cache_folder()
    if cache_folder:
        logger.info("Loading embedding model from HF cache: %s", cache_folder)
    else:
        _log_search_diagnostics()
        logger.info("Loading embedding model (will download if not cached)")

    return SentenceTransformer(MODEL_NAME, trust_remote_code=True, device=device, cache_folder=cache_folder)


class _NomicEmbeddings:
    """LangChain-compatible embeddings wrapper for nomic-embed-text-v1.5.

    Uses task-specific prompt prefixes:
      - ``document`` for indexing (embed_documents)
      - ``query``    for retrieval (embed_query)

    This matches nomic's recommended usage and measurably improves retrieval
    quality vs. using a single generic prompt for both directions.
    """

    def __init__(self, model):
        self._model = model

    # nomic task prefixes. Passed as literal `prompt=` strings (prepended to
    # each text) rather than `prompt_name=`, because the baked model ships an
    # empty prompts dict — a name lookup raises KeyError. The prefixes are part
    # of nomic-embed-text-v1.5's contract and must match between indexing and
    # query for retrieval to work.
    _DOC_PREFIX = "search_document: "
    _QUERY_PREFIX = "search_query: "

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._model.encode(
            texts,
            prompt=self._DOC_PREFIX,
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=len(texts) > 100,
        )
        return embeddings.tolist()

    def embed_query(self, text: str) -> list[float]:
        embedding = self._model.encode(
            text,
            prompt=self._QUERY_PREFIX,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embedding.tolist()


def get_hf_embeddings():
    """Return a LangChain-compatible embeddings instance (lazy singleton).

    Returns a ``_NomicEmbeddings`` wrapper around the loaded SentenceTransformer,
    suitable for RAG / vector-store usage where LangChain wrappers are expected.

    Uses task-aware prompt prefixes (search_document / search_query) as
    recommended by nomic-ai for optimal retrieval quality.
    """
    model = load_embedding_model()
    return _NomicEmbeddings(model)


def embed_for_storage(texts):
    """Embed texts destined for persistent storage (canonical_events /
    canonical_entities embedding_vector columns, or any stored vector that a
    prefixed ``search_query:`` embedding will later be compared against).

    ALWAYS use this instead of a raw ``model.encode(...)`` when writing
    vectors to the database: raw encodes carry no task prefix and are not
    normalized, which puts them in a different similarity space from both
    query embeddings and prefixed stored vectors — consolidation thresholds
    then behave inconsistently across rows (see evals/FINDINGS.md F8).

    Accepts a single string or an iterable of strings; returns a list of
    768-dim lists (one per input).
    """
    if isinstance(texts, str):
        texts = [texts]
    return get_hf_embeddings().embed_documents(list(texts))
