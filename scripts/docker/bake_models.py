#!/usr/bin/env python3
"""
Bake HuggingFace models into the Docker image at build time.

- Embedding: nomic-ai/nomic-embed-text-v1.5 (768-dim, 8192-token context),
  revision-pinned to prevent unexpected custom code updates on rebuild.
  Requires trust_remote_code=True (custom NomicBert pooling code).
- Reranker: cross-encoder/ms-marco-MiniLM-L-6-v2 (~90MB).

Also patches nomic config.json `auto_map` to reference local module paths
so transformers >=4.45 doesn't try to fetch remote code at runtime
(critical for airgapped environments where TRANSFORMERS_OFFLINE=1).
"""
import json
import os
import shutil

from sentence_transformers import CrossEncoder, SentenceTransformer

CACHE_ROOT = "/app/.cache/huggingface"
NOMIC_REVISION = "e5cf08aadaa33385f5990def41f7a23405aec398"

# 1. Embedding model
emb_path = f"{CACHE_ROOT}/models/nomic-embed-text-v1.5"
emb = SentenceTransformer(
    "nomic-ai/nomic-embed-text-v1.5",
    trust_remote_code=True,
    revision=NOMIC_REVISION,
)
os.makedirs(emb_path, exist_ok=True)
emb.save(emb_path)
assert os.path.isfile(os.path.join(emb_path, "modules.json")), "Embedding model save failed"
print(f"Embedding model baked in at {emb_path}")

# 2. Reranker model
reranker_path = f"{CACHE_ROOT}/models/ms-marco-MiniLM-L-6-v2"
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", max_length=512)
os.makedirs(reranker_path, exist_ok=True)
reranker.save(reranker_path)
assert os.path.isfile(os.path.join(reranker_path, "config.json")), "Reranker model save failed"
print(f"Reranker model baked in at {reranker_path}")

# 3. Copy modeling module from HF hub cache into saved model dir BEFORE purge,
# so trust_remote_code resolves locally at runtime.
modeling_dst = os.path.join(emb_path, "modeling_hf_nomic_bert.py")
if os.path.isfile(modeling_dst):
    print("Modeling module already present")
else:
    found = False
    for root, _dirs, files in os.walk(CACHE_ROOT):
        if "modeling_hf_nomic_bert.py" in files:
            shutil.copy2(os.path.join(root, "modeling_hf_nomic_bert.py"), modeling_dst)
            print(f"Copied modeling module to {modeling_dst}")
            found = True
            break
    if not found:
        print("WARNING: modeling_hf_nomic_bert.py not found anywhere in cache")

# 4. Purge HF hub cache (model files now live at the paths above)
shutil.rmtree(f"{CACHE_ROOT}/hub", ignore_errors=True)
print("HF hub cache purged")

# 5. Patch nomic config.json: rewrite auto_map to local module references
cfg_path = os.path.join(emb_path, "config.json")
with open(cfg_path) as f:
    cfg = json.load(f)
if "auto_map" in cfg:
    cfg["auto_map"] = {
        "AutoConfig": "configuration_hf_nomic_bert.NomicBertConfig",
        "AutoModel": "modeling_hf_nomic_bert.NomicBertModel",
    }
    with open(cfg_path, "w") as f:
        json.dump(cfg, f, indent=2)
    print("Patched nomic config.json auto_map for offline loading")

# 6. Verify the saved model loads REAL weights (not random init).
# nomic-embed-text-v1.5 ships trust_remote_code modeling code for the
# transformers 4.x API. An incompatible transformers (e.g. 5.x) silently fails
# to map the checkpoint and random-initializes the weights, which makes every
# embedding noise and breaks all retrieval. Two independent loads of the saved
# model must produce the same vector for the same text; if they don't, weights
# aren't loading and the build must FAIL rather than ship garbage embeddings.
import numpy as _np

_probe = "embedding weight-load verification probe"
_a = SentenceTransformer(emb_path, trust_remote_code=True).encode([_probe], normalize_embeddings=True)[0]
_b = SentenceTransformer(emb_path, trust_remote_code=True).encode([_probe], normalize_embeddings=True)[0]
_cos = float(_np.dot(_a, _b) / (_np.linalg.norm(_a) * _np.linalg.norm(_b)))
print(f"Embedding weight-load determinism: cos={_cos:.4f}")
if _cos < 0.99:
    raise SystemExit(
        f"FATAL: nomic weights did not load deterministically (cos={_cos:.3f}). "
        "transformers/sentence-transformers are incompatible with the nomic "
        "trust_remote_code model — fix the version pins before shipping."
    )
print("Embedding model weight loading verified — embeddings are real.")
