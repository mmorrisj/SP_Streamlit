"""Pure metric functions used across eval components.

No DB or LLM dependencies here — keep this importable everywhere.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Iterable, Sequence


# ---------------------------------------------------------------------------
# Information retrieval
# ---------------------------------------------------------------------------
def recall_at_k(relevant: set, ranked: Sequence, k: int) -> float:
    """Fraction of relevant items appearing in the top-k of the ranking."""
    if not relevant:
        return float("nan")
    top = set(ranked[:k])
    return len(relevant & top) / len(relevant)


def hit_at_k(relevant: set, ranked: Sequence, k: int) -> float:
    """1.0 if any relevant item appears in the top-k, else 0.0."""
    if not relevant:
        return float("nan")
    return 1.0 if relevant & set(ranked[:k]) else 0.0


def reciprocal_rank(relevant: set, ranked: Sequence) -> float:
    for i, item in enumerate(ranked, start=1):
        if item in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(relevant: set, ranked: Sequence, k: int) -> float:
    """Binary-relevance nDCG@k."""
    if not relevant:
        return float("nan")
    dcg = sum(
        1.0 / math.log2(i + 1)
        for i, item in enumerate(ranked[:k], start=1)
        if item in relevant
    )
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
def precision_recall_f1(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": p, "recall": r, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def set_prf(gold: Iterable[set], pred: Iterable[set]) -> dict:
    """Micro-averaged precision/recall/F1 over paired label-sets
    (e.g. per-document category sets)."""
    tp = fp = fn = 0
    for g, p in zip(gold, pred):
        tp += len(g & p)
        fp += len(p - g)
        fn += len(g - p)
    return precision_recall_f1(tp, fp, fn)


def exact_match_rate(gold: Sequence, pred: Sequence) -> float:
    if not gold:
        return float("nan")
    return sum(1 for g, p in zip(gold, pred) if g == p) / len(gold)


def cohens_kappa(a: Sequence, b: Sequence) -> float:
    """Agreement between two label sequences, chance-corrected."""
    if len(a) != len(b) or not a:
        return float("nan")
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb.get(k, 0) for k in ca) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------
def cluster_purity(assignments: dict, gold_labels: dict) -> float:
    """assignments: item -> cluster_id; gold_labels: item -> gold class.
    Purity = weighted fraction of each cluster belonging to its majority class."""
    clusters: dict = {}
    for item, cid in assignments.items():
        if item in gold_labels:
            clusters.setdefault(cid, []).append(gold_labels[item])
    total = sum(len(v) for v in clusters.values())
    if not total:
        return float("nan")
    return sum(Counter(v).most_common(1)[0][1] for v in clusters.values()) / total


def pairwise_cluster_prf(assignments: dict, gold_labels: dict) -> dict:
    """Pairwise precision/recall/F1: over all item pairs, does the clustering
    agree with gold same-class/different-class judgments?"""
    items = [i for i in assignments if i in gold_labels]
    tp = fp = fn = 0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            same_pred = assignments[a] == assignments[b]
            same_gold = gold_labels[a] == gold_labels[b]
            if same_pred and same_gold:
                tp += 1
            elif same_pred and not same_gold:
                fp += 1
            elif same_gold and not same_pred:
                fn += 1
    return precision_recall_f1(tp, fp, fn)


# ---------------------------------------------------------------------------
# Vectors
# ---------------------------------------------------------------------------
def cosine(u: Sequence[float], v: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(u, v))
    nu = math.sqrt(sum(a * a for a in u))
    nv = math.sqrt(sum(b * b for b in v))
    return dot / (nu * nv) if nu and nv else 0.0


def summarize(values: Sequence[float]) -> dict:
    """Mean/median/min/max/n for a list of floats, NaNs dropped."""
    vals = [v for v in values if v == v]  # drop NaN
    if not vals:
        return {"n": 0}
    vals_sorted = sorted(vals)
    mid = len(vals_sorted) // 2
    median = (
        vals_sorted[mid]
        if len(vals_sorted) % 2
        else (vals_sorted[mid - 1] + vals_sorted[mid]) / 2
    )
    return {
        "n": len(vals),
        "mean": sum(vals) / len(vals),
        "median": median,
        "min": vals_sorted[0],
        "max": vals_sorted[-1],
    }
