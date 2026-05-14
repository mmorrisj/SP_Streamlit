"""
Targeted post-processing to split over-aggregated canonical events.

Detects canonical events whose daily_event_mentions span across temporal gaps
wider than --min-gap-days (default 30) and proposes a temporal split. LLM
validates each proposed split before any database changes are applied.

This is a one-off cleanup tool to remediate mega-events that accumulated when
daily clustering and Stage 1B matching pulled unrelated months of news into a
single canonical_event (e.g., a 17-month "Sharm El Sheikh Ceasefire" that
subsumes Biden-era talks and 2026 Iran nuclear negotiations).

PIPELINE CONTEXT:
  - Standard pipeline: ingestion -> clustering -> consolidation -> merge
  - This script: post-merge cleanup for events that grew across temporal gaps
  - Not invoked automatically by run_ingestion_pipeline.py

DOWNSTREAM SIDE EFFECTS:
  After this script splits events, several downstream artifacts become stale and
  must be regenerated. Recommended sequence after a non-dry-run:

    # 1. Re-score materiality on new events + reset originals
    sp-pipeline python services/pipeline/events/score_canonical_event_materiality.py --rescore

    # 2. Regenerate daily/weekly/monthly summaries (they aggregate by canonical_event)
    # 3. Re-score summary materiality
    # 4. Regenerate bilateral summaries (materiality histograms depend on event scores)
    sp-pipeline python services/run_ingestion_pipeline.py \\
        --start-date <range_start> --end-date <range_end> \\
        --skip-ingestion --skip-embeddings --skip-clustering --skip-cluster-deconflict \\
        --skip-consolidate --skip-canonical-deconflict --skip-merge \\
        --skip-daily-entity-extraction --skip-entity-clustering --skip-entity-deconflict \\
        --skip-entity-consolidate --skip-canonical-entity-deconflict --skip-entity-merge \\
        --skip-entity-descriptions --skip-entity-cooccurrence --skip-entity-relationships \\
        --rescore-event-materiality --rescore-summary-materiality \\
        --regenerate-bilateral-summaries

  On split, this script sets material_score=NULL, consolidated_description=NULL,
  key_facts=NULL, entities_mentioned=NULL on the ORIGINAL event (so re-scoring
  picks it up) and creates new events with these fields NULL by default.

Usage:
    # Preview the top 50 largest mega-events and what would split
    python services/pipeline/events/split_overaggregated_events.py --dry-run

    # Apply splits to top 50 mega-events across all countries
    python services/pipeline/events/split_overaggregated_events.py

    # Process only Iran's top 20
    python services/pipeline/events/split_overaggregated_events.py --country Iran --top-n 20

    # More aggressive gap threshold
    python services/pipeline/events/split_overaggregated_events.py --min-gap-days 14

    # Skip LLM (algorithmic only)
    python services/pipeline/events/split_overaggregated_events.py --no-llm-validate
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import argparse
import json
import re
import uuid
from datetime import date, timedelta
from typing import List, Dict, Optional

import numpy as np
from sqlalchemy import text

from shared.database.database import get_session
from shared.utils.utils import gai


def load_embedding_model():
    from shared.utils.model_cache import load_embedding_model as _load
    return _load()


def identify_candidates(session, min_span_days: int, top_n: int,
                        country: Optional[str] = None,
                        order_by: str = "articles"):
    """Return canonical_events spanning longer than min_span_days, ordered by the
    chosen ranking (articles | span)."""
    sql = """
        SELECT id, canonical_name, initiating_country,
               first_mention_date, last_mention_date,
               total_articles, total_mention_days,
               (last_mention_date - first_mention_date) AS span_days,
               primary_recipients, primary_categories,
               material_score, llm_validated
        FROM canonical_events
        WHERE (last_mention_date - first_mention_date) > :min_span
    """
    params = {"min_span": min_span_days}
    if country:
        sql += " AND initiating_country = :c"
        params["c"] = country
    if order_by == "span":
        sql += " ORDER BY (last_mention_date - first_mention_date) DESC NULLS LAST LIMIT :top_n"
    else:
        sql += " ORDER BY total_articles DESC NULLS LAST LIMIT :top_n"
    params["top_n"] = top_n
    return session.execute(text(sql), params).fetchall()


def load_mentions(session, event_id):
    """Return all daily_event_mentions for an event, ordered by date."""
    return session.execute(text("""
        SELECT id, mention_date, article_count, consolidated_headline,
               source_names, doc_ids
        FROM daily_event_mentions WHERE canonical_event_id = :id
        ORDER BY mention_date
    """), {"id": event_id}).fetchall()


def force_bin_block(block, window_days: int):
    """Slice a single block of mentions into temporal windows of `window_days`."""
    if not block:
        return []
    first_date = block[0][1]
    sub_blocks = [[]]
    window_end = first_date + timedelta(days=window_days)
    for m in block:
        if m[1] >= window_end:
            sub_blocks.append([])
            window_end = m[1] + timedelta(days=window_days)
        sub_blocks[-1].append(m)
    return [b for b in sub_blocks if b]


def partition_into_blocks(mentions, min_gap_days: int,
                          drift_threshold: Optional[float] = None,
                          min_block_size: int = 3,
                          embedding_model=None,
                          force_bin_min_span: int = 180,
                          force_bin_window_days: int = 90):
    """Split a sorted list of daily_event_mentions into temporal blocks.

    Splits happen when either:
      - A gap >= min_gap_days between consecutive mention dates (temporal gap), OR
      - A new headline's cosine similarity to the running centroid of the current
        block drops below drift_threshold (semantic drift)

    A post-pass merges blocks smaller than min_block_size back into their previous
    neighbor to prevent single-outlier headlines from fragmenting an otherwise
    coherent block.

    If drift_threshold is None or embedding_model is None, drift detection is
    disabled (gap-only splitting).
    """
    if not mentions:
        return []

    use_drift = drift_threshold is not None and embedding_model is not None

    if use_drift:
        # Batch encode all headlines (fallback to canonical_name proxy when null)
        headlines = [m[3] or "" for m in mentions]
        embeddings = np.asarray(
            embedding_model.encode(headlines, normalize_embeddings=True),
            dtype=np.float32,
        )
    else:
        embeddings = None

    blocks = [[mentions[0]]]
    block_indices = [[0]]  # parallel list to retrieve embeddings per block
    if use_drift:
        centroid = embeddings[0].copy()
        # Track for diagnostics: lowest similarity observed vs running centroid
        min_sim_observed = 1.0
        min_sim_at = None
    else:
        centroid = None

    for i in range(1, len(mentions)):
        prev = mentions[i - 1]
        curr = mentions[i]
        gap_days = (curr[1] - prev[1]).days

        gap_split = gap_days >= min_gap_days
        drift_split = False
        if use_drift and len(blocks[-1]) >= min_block_size:
            sim = float(np.dot(centroid, embeddings[i]))
            if sim < min_sim_observed:
                min_sim_observed = sim
                min_sim_at = (curr[1], curr[3])
            if sim < drift_threshold:
                drift_split = True

        if gap_split or drift_split:
            blocks.append([curr])
            block_indices.append([i])
            if use_drift:
                centroid = embeddings[i].copy()
        else:
            blocks[-1].append(curr)
            block_indices[-1].append(i)
            if use_drift:
                # Running mean of normalized vectors; re-normalize
                n = len(blocks[-1])
                centroid = ((n - 1) * centroid + embeddings[i]) / n
                norm = float(np.linalg.norm(centroid))
                if norm > 1e-9:
                    centroid = centroid / norm

    # Post-pass: merge tiny blocks (< min_block_size) into the previous block.
    # Tiny first block gets merged forward instead.
    if len(blocks) > 1:
        merged = [blocks[0]]
        for b in blocks[1:]:
            if len(b) < min_block_size:
                merged[-1].extend(b)
            else:
                merged.append(b)
        # If the first block is too small, absorb it into block 2
        if len(merged) > 1 and len(merged[0]) < min_block_size:
            merged[1] = merged[0] + merged[1]
            merged = merged[1:]
        blocks = merged

    # Force-bin: any single block still spanning > force_bin_min_span days gets
    # sliced into fixed temporal windows. The LLM then decides which adjacent
    # windows truly represent the same event vs separate ones.
    force_binned = 0
    if force_bin_min_span and force_bin_window_days:
        new_blocks = []
        for b in blocks:
            if not b:
                continue
            block_span = (b[-1][1] - b[0][1]).days
            if block_span > force_bin_min_span:
                sub = force_bin_block(b, force_bin_window_days)
                if len(sub) > 1:
                    force_binned += 1
                new_blocks.extend(sub)
            else:
                new_blocks.append(b)
        blocks = new_blocks

    diagnostics = {"force_binned_blocks": force_binned}
    if use_drift:
        diagnostics["min_sim_observed"] = round(min_sim_observed, 3)
        diagnostics["min_sim_at_date"] = min_sim_at[0] if min_sim_at else None
        diagnostics["min_sim_at_headline"] = min_sim_at[1] if min_sim_at else None

    return blocks, diagnostics


def summarize_block(block):
    """Compact dict describing a temporal block for LLM input."""
    return {
        "date_range": f"{block[0][1]} to {block[-1][1]}",
        "mention_days": len(block),
        "total_articles": int(sum(r[2] for r in block)),
        "sample_headlines": [r[3] for r in block[:4] if r[3]],
    }


def llm_validate_split(canonical_name: str, blocks, verbose: bool = True) -> Dict:
    """Ask the LLM whether the temporal blocks represent the same event or separate ones."""
    block_summaries = [summarize_block(b) for b in blocks]
    enumerated = [{"block": i, **s} for i, s in enumerate(block_summaries)]

    sys_prompt = (
        "You are an analyst reviewing news events for over-aggregation.\n"
        "A single canonical event has been partitioned into temporal blocks based on long gaps "
        "in news coverage. Decide whether each block represents the SAME real-world event as the "
        "others, or whether they are SEPARATE events that should each get their own canonical event.\n\n"
        "Apply this principle: temporally-separated news cycles about ostensibly similar topics "
        "(e.g., different ceasefire negotiations, different summit iterations) are SEPARATE events. "
        "But recurring annual cycles of one durable campaign (e.g., annual Hajj pilgrimage, annual "
        "Quds Day) MAY be the same event series — use your judgment based on the headlines.\n"
    )

    user_prompt = f"""Original canonical event name: "{canonical_name}"

This event has daily mentions partitioned into {len(blocks)} temporal blocks separated by long gaps:

{json.dumps(enumerated, indent=2, default=str)}

Return your decision as JSON in this exact shape (placeholder values shown in angle brackets are illustrative — REPLACE THEM with concrete, specific event names you generate from the headlines):
{{
  "should_split": true/false,
  "reasoning": "<1-2 sentence rationale>",
  "rename_original_to": null,
  "splits": [
    {{"block": 0, "keep_with_original": true, "proposed_name": null}},
    {{"block": 1, "keep_with_original": false, "proposed_name": "<specific real-world event name derived from headlines in block 1>"}},
    {{"block": 2, "keep_with_original": false, "proposed_name": "<specific real-world event name derived from headlines in block 2; may be same as block 1's name if they describe the same event>"}}
  ]
}}

Rules:
- If should_split=false, omit the splits array (no changes will be applied).
- If should_split=true, every block index must appear in splits.
- One or more contiguous blocks should have keep_with_original=true (they remain with the original event).
- Other blocks should have keep_with_original=false. Multiple blocks may share the SAME proposed_name to indicate they describe the same separate event (they will be merged into a single new canonical event).
- Use the same proposed_name across adjacent blocks only when they truly represent one ongoing event that just happens to span a long time window. Use distinct names when the blocks describe distinct events.
- IMPORTANT: If the kept block(s) describe an event that does NOT match the original canonical_name (e.g., the original was named for a 2025 event but the kept block is from 2024), set "rename_original_to" to a more accurate name. Otherwise leave it null.
"""
    try:
        response = gai(sys_prompt, user_prompt, model="gpt-4o-mini", use_proxy=True)
        if isinstance(response, dict):
            return response
        match = re.search(r'\{.*\}', response, re.DOTALL)
        return json.loads(match.group(0)) if match else json.loads(response)
    except Exception as e:
        if verbose:
            print(f"    [WARNING] LLM error: {e}")
        return {"should_split": False, "reasoning": f"LLM error: {e}", "splits": []}


def algorithmic_decision(blocks) -> Dict:
    """Fallback decision when --no-llm-validate is set: always split, keep largest with original."""
    if len(blocks) < 2:
        return {"should_split": False, "reasoning": "Single block", "splits": []}
    article_counts = [sum(r[2] for r in b) for b in blocks]
    largest_idx = int(np.argmax(article_counts))
    splits = []
    for i, b in enumerate(blocks):
        if i == largest_idx:
            splits.append({"block": i, "keep_with_original": True, "proposed_name": None})
        else:
            # Use first headline as proposed name (fallback)
            first_headline = next((r[3] for r in b if r[3]), f"Split block {i}")
            splits.append({"block": i, "keep_with_original": False, "proposed_name": first_headline[:200]})
    return {"should_split": True, "reasoning": "Algorithmic gap-based split", "splits": splits}


def apply_split(session, original, blocks, decision: Dict, embedding_model, dry_run: bool, verbose: bool):
    """Apply an LLM- or algorithmically-approved split. Returns stats.

    Blocks the LLM marks keep_with_original=true stay with the original event.
    Blocks marked keep_with_original=false get grouped by proposed_name — blocks
    sharing the same name merge into a single new canonical event."""
    if not decision.get("should_split"):
        return {"split": False, "new_events_created": 0}

    splits = decision.get("splits") or []
    if not splits:
        return {"split": False, "new_events_created": 0}

    # Map block index -> decision
    decision_by_block = {s["block"]: s for s in splits if "block" in s}

    # Identify blocks that stay with the original event
    keep_indices = [i for i, s in decision_by_block.items() if s.get("keep_with_original")]
    if not keep_indices:
        # Default: keep the largest block with original
        article_counts = [sum(r[2] for r in b) for b in blocks]
        keep_indices = [int(np.argmax(article_counts))]

    # Group non-kept blocks by proposed_name (LLM may give multiple blocks the
    # same name to indicate they represent one event spanning a long window).
    # Reject obviously-placeholder names from the LLM (e.g. literal "Distinct Event Name")
    # and fall back to the block's representative headline.
    PLACEHOLDER_PATTERNS = (
        "distinct event name", "specific real-world event name",
        "event name", "different event name", "<", ">"
    )

    def looks_like_placeholder(name: str) -> bool:
        if not name or len(name) < 8:
            return True
        low = name.lower().strip()
        return any(p in low for p in PLACEHOLDER_PATTERNS)

    name_to_block_indices: Dict[str, List[int]] = {}
    for i in range(len(blocks)):
        if i in keep_indices:
            continue
        s = decision_by_block.get(i, {})
        proposed_name = s.get("proposed_name")
        if not proposed_name or looks_like_placeholder(proposed_name):
            # Use the most-articles headline from this block as the fallback name
            block_mentions = blocks[i]
            best = max(block_mentions, key=lambda r: r[2] or 0)
            proposed_name = (best[3] or f"Split of {original.canonical_name}")[:200]
        name_to_block_indices.setdefault(proposed_name, []).append(i)

    # Build list of new event specs — one per UNIQUE name, consolidating mentions
    # from all blocks that share that name
    new_event_specs = []  # list of (proposed_name, combined_mentions)
    for proposed_name, block_idxs in name_to_block_indices.items():
        combined = []
        for idx in block_idxs:
            combined.extend(blocks[idx])
        combined.sort(key=lambda r: r[1])  # by mention_date
        new_event_specs.append((proposed_name, combined))

    if dry_run:
        if verbose:
            print(f"    [DRY RUN] Would create {len(new_event_specs)} new events from this split")
            for name, mentions in new_event_specs:
                dates = [m[1] for m in mentions]
                print(f"      -> '{name[:70]}' ({dates[0]} to {dates[-1]}, n={len(mentions)})")
        return {"split": True, "new_events_created": len(new_event_specs), "dry_run": True}

    # Create new canonical_events and reassign mentions
    new_event_ids = []
    for proposed_name, block_mentions in new_event_specs:
        block_dates = [m[1] for m in block_mentions]
        first_date = block_dates[0]
        last_date = block_dates[-1]
        total_articles = sum(int(m[2]) for m in block_mentions)
        total_days = len(block_mentions)
        article_counts = [int(m[2]) for m in block_mentions]
        peak_idx = int(np.argmax(article_counts))
        peak_date = block_mentions[peak_idx][1]
        peak_articles = article_counts[peak_idx]

        embedding = embedding_model.encode(proposed_name).tolist()

        new_id = str(uuid.uuid4())
        session.execute(text("""
            INSERT INTO canonical_events (
                id, canonical_name, initiating_country,
                first_mention_date, last_mention_date,
                total_mention_days, total_articles,
                story_phase, days_since_last_mention,
                unique_sources, source_count,
                peak_mention_date, peak_daily_article_count,
                embedding_vector, alternative_names,
                primary_categories, primary_recipients,
                key_facts,
                llm_validated
            ) VALUES (
                :id, :name, :country,
                :first_d, :last_d,
                :days, :articles,
                'emerging', 0,
                ARRAY[]::text[], 0,
                :peak_d, :peak_a,
                :emb, ARRAY[]::text[],
                :cats, :recips,
                '{}'::jsonb,
                FALSE
            )
        """), {
            "id": new_id,
            "name": proposed_name,
            "country": original.initiating_country,
            "first_d": first_date,
            "last_d": last_date,
            "days": total_days,
            "articles": total_articles,
            "peak_d": peak_date,
            "peak_a": peak_articles,
            "emb": embedding,
            "cats": json.dumps(original.primary_categories) if original.primary_categories else None,
            "recips": json.dumps(original.primary_recipients) if original.primary_recipients else None,
        })
        new_event_ids.append(new_id)

        # Reassign daily_event_mentions for this block to the new event.
        # Cast id::text since daily_event_mentions.id is UUID but the parameter
        # is a list of strings (PostgreSQL won't implicitly cast text[] to uuid[]).
        mention_ids = [str(m[0]) for m in block_mentions]
        session.execute(text("""
            UPDATE daily_event_mentions
            SET canonical_event_id = :new_id
            WHERE id::text = ANY(:mention_ids)
        """), {"new_id": new_id, "mention_ids": mention_ids})

        if verbose:
            safe_name = proposed_name.encode('ascii', 'replace').decode('ascii')[:60]
            print(f"      -> created '{safe_name}' ({first_date}..{last_date}, {total_articles}a, {total_days}d)")

    # Recompute aggregates for the original event from its remaining mentions.
    # Reset material_score, llm_validated, and stale descriptive fields so the
    # downstream pipeline (materiality scoring, descriptions, summaries) recomputes
    # them for the now-smaller temporal scope.
    session.execute(text("""
        UPDATE canonical_events ce
        SET first_mention_date = sub.first_d,
            last_mention_date = sub.last_d,
            total_mention_days = sub.n_days,
            total_articles = sub.n_articles,
            days_since_last_mention = CURRENT_DATE - sub.last_d,
            peak_mention_date = sub.peak_d,
            peak_daily_article_count = sub.peak_a,
            llm_validated = FALSE,
            material_score = NULL,
            material_justification = NULL,
            consolidated_description = NULL,
            key_facts = '{}'::jsonb,
            entities_mentioned = NULL
        FROM (
            SELECT canonical_event_id,
                   MIN(mention_date) AS first_d,
                   MAX(mention_date) AS last_d,
                   COUNT(DISTINCT mention_date) AS n_days,
                   SUM(article_count) AS n_articles,
                   (array_agg(mention_date ORDER BY article_count DESC))[1] AS peak_d,
                   MAX(article_count) AS peak_a
            FROM daily_event_mentions
            WHERE canonical_event_id = :orig_id
            GROUP BY canonical_event_id
        ) sub
        WHERE ce.id = :orig_id
    """), {"orig_id": str(original.id)})

    # Rename the original event if the LLM suggested a more accurate name
    rename = decision.get("rename_original_to")
    if rename and isinstance(rename, str) and rename.strip():
        new_emb = embedding_model.encode(rename).tolist()
        session.execute(text("""
            UPDATE canonical_events
            SET canonical_name = :new_name,
                embedding_vector = :emb,
                alternative_names = COALESCE(alternative_names, ARRAY[]::text[]) || :old_name
            WHERE id = :orig_id
        """), {
            "new_name": rename.strip(),
            "emb": new_emb,
            "old_name": [original.canonical_name],
            "orig_id": str(original.id),
        })
        if verbose:
            safe_old = (original.canonical_name or '').encode('ascii', 'replace').decode('ascii')[:50]
            safe_new = rename.encode('ascii', 'replace').decode('ascii')[:50]
            print(f"      -> renamed original: '{safe_old}' -> '{safe_new}'")

    return {"split": True, "new_events_created": len(new_event_ids),
            "renamed_original": bool(rename)}


def main():
    parser = argparse.ArgumentParser(
        description="Split over-aggregated canonical events at long temporal gaps",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--country", help="Filter to a single initiating country")
    parser.add_argument("--min-span-days", type=int, default=60,
                        help="Only consider events spanning > this many days (default 60)")
    parser.add_argument("--min-gap-days", type=int, default=30,
                        help="Split at internal gaps >= this many days (default 30)")
    parser.add_argument("--drift-threshold", type=float, default=0.70,
                        help="Cosine similarity threshold for headline drift detection "
                             "(default 0.70). New block opens when a daily headline's "
                             "similarity to the current block centroid drops below this.")
    parser.add_argument("--min-block-size", type=int, default=3,
                        help="Minimum mentions per block after the merge post-pass (default 3)")
    parser.add_argument("--no-drift-detection", action="store_true",
                        help="Disable semantic drift detection; gap-based splitting only")
    parser.add_argument("--force-bin-min-span", type=int, default=180,
                        help="Force-bin any block still spanning > N days into fixed windows "
                             "(default 180). Set 0 to disable.")
    parser.add_argument("--force-bin-window-days", type=int, default=90,
                        help="Window size when force-binning long blocks (default 90 days)")
    parser.add_argument("--top-n", type=int, default=50,
                        help="Process the top N candidates (default 50)")
    parser.add_argument("--order-by", choices=["articles", "span"], default="articles",
                        help="Rank candidates by 'articles' (default) or 'span' "
                             "(longest-spanning events first)")
    parser.add_argument("--no-llm-validate", action="store_true",
                        help="Skip LLM validation and split algorithmically")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview proposed splits without writing to the database")
    parser.add_argument("--verbose", action="store_true", default=True)
    args = parser.parse_args()

    print("=" * 80)
    print("SPLIT OVER-AGGREGATED CANONICAL EVENTS")
    print("=" * 80)
    print(f"min_span_days={args.min_span_days}  min_gap_days={args.min_gap_days}  "
          f"top_n={args.top_n}  llm_validate={not args.no_llm_validate}  dry_run={args.dry_run}")
    print(f"drift_detection={not args.no_drift_detection} (threshold={args.drift_threshold}, "
          f"min_block_size={args.min_block_size})")
    print(f"country filter: {args.country or '(all)'}")
    print("=" * 80)

    embedding_model = load_embedding_model()
    drift_threshold = None if args.no_drift_detection else args.drift_threshold

    overall = {
        "candidates_inspected": 0,
        "candidates_with_blocks": 0,
        "candidates_split": 0,
        "new_events_created": 0,
        "candidates_skipped_single_block": 0,
        "candidates_skipped_llm_rejected": 0,
    }

    with get_session() as session:
        candidates = identify_candidates(session, args.min_span_days, args.top_n,
                                         args.country, order_by=args.order_by)
        print(f"\nFound {len(candidates)} candidate events (span > {args.min_span_days}d, "
              f"top {args.top_n} by {args.order_by})\n")

        for idx, original in enumerate(candidates, 1):
            overall["candidates_inspected"] += 1
            safe_name = (original.canonical_name or '').encode('ascii', 'replace').decode('ascii')
            print(f"[{idx}/{len(candidates)}] {original.initiating_country:<14}  "
                  f"span={original.span_days}d  a={original.total_articles}  "
                  f"d={original.total_mention_days}  {safe_name[:70]}")

            mentions = load_mentions(session, original.id)
            blocks, diagnostics = partition_into_blocks(
                mentions,
                min_gap_days=args.min_gap_days,
                drift_threshold=drift_threshold,
                min_block_size=args.min_block_size,
                embedding_model=embedding_model,
                force_bin_min_span=args.force_bin_min_span,
                force_bin_window_days=args.force_bin_window_days,
            )

            if "min_sim_observed" in diagnostics:
                ms = diagnostics["min_sim_observed"]
                msd = diagnostics["min_sim_at_date"]
                msh = (diagnostics["min_sim_at_headline"] or "")[:80]
                print(f"    drift diagnostic: min_sim={ms} on {msd} (headline: {msh!r})")
            if diagnostics.get("force_binned_blocks"):
                print(f"    force-binned {diagnostics['force_binned_blocks']} block(s) into "
                      f"{args.force_bin_window_days}-day windows")

            if len(blocks) < 2:
                overall["candidates_skipped_single_block"] += 1
                print(f"    -> single block ({len(mentions)} mentions, no qualifying gap or drift); skipped")
                continue

            overall["candidates_with_blocks"] += 1
            print(f"    -> {len(blocks)} temporal blocks detected")
            for i, b in enumerate(blocks):
                print(f"       block {i}: {b[0][1]} to {b[-1][1]}  ({len(b)} days, "
                      f"{sum(r[2] for r in b)} articles)")

            if args.no_llm_validate:
                decision = algorithmic_decision(blocks)
            else:
                decision = llm_validate_split(original.canonical_name, blocks, args.verbose)
                print(f"    LLM: should_split={decision.get('should_split')}  "
                      f"({decision.get('reasoning', '')[:120]})")

            if not decision.get("should_split"):
                overall["candidates_skipped_llm_rejected"] += 1
                continue

            try:
                result = apply_split(session, original, blocks, decision, embedding_model,
                                     args.dry_run, args.verbose)
                if result.get("split"):
                    overall["candidates_split"] += 1
                    overall["new_events_created"] += result.get("new_events_created", 0)
                if not args.dry_run:
                    session.commit()
            except Exception as e:
                session.rollback()
                print(f"    [ERROR] split failed: {e}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    for k, v in overall.items():
        print(f"  {k:<35} {v}")


if __name__ == "__main__":
    main()
