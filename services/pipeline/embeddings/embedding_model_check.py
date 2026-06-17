"""Check whether the nomic model loads real weights (deterministically).

If two fresh loads of the model produce different vectors for the same text,
the weights are NOT loading (random init) — every embedding is garbage and
re-embedding is futile until model loading is fixed (usually a torch/
transformers/einops compatibility problem with nomic's trust_remote_code).
"""
from __future__ import annotations
import math


def _cos(a, b):
    d = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(y*y for y in b))
    return d/(na*nb) if na and nb else 0.0


def main():
    import torch
    print("torch:", torch.__version__, "cuda:", torch.cuda.is_available())
    from shared.utils.model_cache import load_embedding_model
    t = "China major infrastructure projects in the Middle East and North Africa"
    print("\n--- load #1 ---")
    m1 = load_embedding_model()
    v1 = m1.encode([t], normalize_embeddings=True)[0].tolist()
    print("\n--- load #2 ---")
    m2 = load_embedding_model()
    v2 = m2.encode([t], normalize_embeddings=True)[0].tolist()
    # same instance, encode twice (forward-pass determinism)
    v1b = m1.encode([t], normalize_embeddings=True)[0].tolist()
    print("\ncos(load1, load1-again):", round(_cos(v1, v1b), 4), "  (forward determinism; expect ~1.0)")
    print("cos(load1, load2):     ", round(_cos(v1, v2), 4), "  (weight-load determinism; <0.99 => RANDOM WEIGHTS)")
    if _cos(v1, v2) < 0.99:
        print("\n=> BROKEN: weights are NOT loading (random init). Embeddings are garbage.")
        print("   Fix model loading (torch/transformers/einops vs nomic trust_remote_code), not the data.")
    else:
        print("\n=> Model loads consistently; weights are real. Look elsewhere.")


if __name__ == "__main__":
    main()
