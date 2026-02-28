"""
Batch processing for report generation using OpenAI Batch API.

Prepares event narrative and entity summary LLM calls as JSONL,
submits them as a single batch (50% cost reduction), then injects
results back into the report pipeline. Sequential calls (category
narratives, synthesis, title) run normally via gai() after the
batch completes.

Usage (via CLI):
    python scripts/generate_report.py \\
        --country China --start-date 2024-08-01 --end-date 2024-08-31 \\
        --batch --model gpt-5-mini
"""

import json
import os
import sys
import time
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

from openai import OpenAI

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from shared.database.database import get_session
from shared.utils.utils import Config, gai
from shared.utils.citation_utils import build_hyperlink
from server.report_generator import (
    parse_date,
    get_top_events_by_category,
    _deduplicate_and_backfill,
    get_document_details,
    compute_metrics,
    get_top_entities,
    compute_materiality_trends,
    get_entities_for_events,
    generate_category_narrative,
    generate_overall_synthesis,
    generate_publication_title,
    _build_citations_output,
    _check_llm_availability,
)


def _get_openai_client() -> OpenAI:
    """Get OpenAI client using OPENAI_PROJ_API env var."""
    api_key = os.getenv("OPENAI_PROJ_API", "").strip()
    if not api_key:
        raise ValueError(
            "OPENAI_PROJ_API environment variable not set. "
            "Required for batch API access."
        )
    return OpenAI(api_key=api_key)


def _build_event_narrative_messages(
    event: Dict,
    source_docs: Optional[List[Dict]] = None,
    source_map: Optional[Dict[str, int]] = None,
) -> List[Dict[str, str]]:
    """Build chat messages for event narrative generation.

    Replicates the exact prompts from generate_event_narrative() in
    report_generator.py.
    """
    source_context = ""
    if source_docs and source_map:
        source_lines = []
        for doc in source_docs[:5]:
            cnum = source_map.get(doc["doc_id"])
            if cnum:
                source_lines.append(
                    f'  [{cnum}] "{doc["headline"]}" — {doc["source_name"]}, '
                    f"{doc.get('published_date', 'n.d.')}"
                )
        if source_lines:
            source_context = "\n\nSource Documents:\n" + "\n".join(source_lines)

    citation_instruction = ""
    if source_context:
        citation_instruction = (
            "\n\nIMPORTANT: Include inline citations [1], [2], etc. after factual claims, "
            "using the citation numbers from the Source Documents list. "
            "Every substantive claim must be attributed to at least one source."
        )

    sys_prompt = (
        "You are an analyst writing a factual briefing. Your output must be strictly evidence-based.\n\n"
        "Generate two sections:\n"
        "1. OVERVIEW: State precisely what happened — name the specific actors, actions taken, dates, "
        "locations, and agreements or outcomes. 2-3 sentences.\n"
        "2. OUTCOMES: State the documented results: agreements signed, funds committed, projects launched, "
        "statements issued, or positions taken. 2-3 sentences.\n\n"
        "RULES:\n"
        "- Report only facts that are stated or directly supported by the source material.\n"
        "- Name specific people, organizations, amounts, dates, and places wherever available.\n"
        '- Do NOT use speculative language: no "could", "might", "potentially", "is expected to", '
        '"remains to be seen", "signals", "underscores".\n'
        "- Do NOT editorialize or assess significance — let the facts speak.\n"
        '- Do NOT use filler phrases like "This event represents", "This development highlights", '
        '"This is a significant".'
        f"{citation_instruction}"
    )

    user_prompt = (
        f"Event: {event['event_name']}\n"
        f"Description: {event['description']}\n"
        f"Date Range: {event['first_mention_date']} to {event['last_mention_date']}\n"
        f"Coverage: {event['article_count']} articles over {event['mention_days']} days"
        f"{source_context}\n\n"
        'Generate Overview and Outcomes.\n'
        'Return JSON: {"overview": "...", "outcomes": "..."}'
    )

    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _build_entity_summary_messages(
    entity: Dict,
    country: str,
    start_date: date,
    end_date: date,
    source_docs: Optional[List[Dict]] = None,
    source_map: Optional[Dict[str, int]] = None,
) -> List[Dict[str, str]]:
    """Build chat messages for entity summary generation.

    Replicates the exact prompts from generate_entity_summary() in
    report_generator.py.
    """
    categories_str = (
        ", ".join(
            f"{k} ({v})"
            for k, v in sorted(
                (entity.get("primary_categories") or {}).items(),
                key=lambda x: x[1],
                reverse=True,
            )[:4]
        )
        or "Unknown"
    )

    recipients_str = (
        ", ".join(
            f"{k} ({v})"
            for k, v in sorted(
                (entity.get("primary_recipients") or {}).items(),
                key=lambda x: x[1],
                reverse=True,
            )[:4]
        )
        or "Unknown"
    )

    source_context = ""
    citation_instruction = ""
    if source_docs and source_map:
        source_lines = []
        for doc in source_docs[:5]:
            cnum = source_map.get(doc["doc_id"])
            if cnum:
                source_lines.append(
                    f'  [{cnum}] "{doc["headline"]}" — {doc["source_name"]}, '
                    f"{doc.get('published_date', 'n.d.')}"
                )
        if source_lines:
            source_context = "\nSource Documents:\n" + "\n".join(source_lines)
            citation_instruction = (
                "\nInclude inline citations [1], [2], etc. from the Source Documents "
                "after factual claims."
            )

    sys_prompt = (
        "You are an analyst. Write a concise 2-3 sentence factual summary of this entity's\n"
        "documented activities during the specified period.\n\n"
        "RULES:\n"
        "- State what the entity did: meetings attended, agreements signed, statements made, "
        "projects involved in.\n"
        "- Name specific counterparts, dates, locations, and outcomes where available.\n"
        "- Do NOT speculate about motives, influence, or future impact.\n"
        '- Do NOT use "significant", "key player", "instrumental", "pivotal", or similar editorializing.'
        f"{citation_instruction}"
    )

    user_prompt = (
        f"Entity: {entity['name']}\n"
        f"Type: {entity['entity_type']}\n"
        f"Role: {entity.get('role') or 'Unknown'}\n"
        f"Country Context: {country}\n"
        f"Period: {start_date} to {end_date}\n"
        f"Documents: {entity['total_documents']} across {entity['total_mention_days']} days\n"
        f"Categories: {categories_str}\n"
        f"Recipients: {recipients_str}\n"
        f"Existing Description: {entity.get('description') or 'None'}"
        f"{source_context}\n\n"
        "Write a factual summary of this entity's documented activities during this period."
    )

    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]


def prepare_report_batch_jsonl(
    events_by_category: Dict[str, List[Dict]],
    entities_by_type: Dict[str, List[Dict]],
    source_map: Dict[str, int],
    documents_by_event: Dict[str, List[Dict]],
    entity_docs_by_id: Dict[str, List[Dict]],
    config: Config,
    country: str,
    start_date: date,
    end_date: date,
    model: str = "gpt-4o-mini",
    cached_narratives: Optional[Dict[str, Dict]] = None,
    quiet: bool = False,
) -> Tuple[str, int, int]:
    """Prepare JSONL file for OpenAI Batch API.

    Args:
        events_by_category: Events grouped by category.
        entities_by_type: Entities grouped by type.
        source_map: doc_id -> citation number mapping.
        documents_by_event: event_id -> list of document dicts.
        entity_docs_by_id: entity_id -> list of document dicts.
        config: Config object.
        country: Initiating country.
        start_date: Report start date.
        end_date: Report end date.
        model: LLM model name.
        cached_narratives: Pre-loaded cached narratives (event_name -> {overview, outcomes}).
        quiet: Suppress output.

    Returns:
        Tuple of (jsonl_file_path, event_count, entity_count).
    """
    cached_narratives = cached_narratives or {}
    lines = []
    event_count = 0
    entity_count = 0

    # Temperature handling: gpt-5 family doesn't support non-1 values
    extra_params = {}
    if not model.startswith("gpt-5"):
        extra_params["temperature"] = 0.4

    # Event narratives
    for category, events in events_by_category.items():
        for event in events:
            # Skip if cached
            if event["event_name"] in cached_narratives:
                continue

            event_docs = documents_by_event.get(event["id"], [])
            messages = _build_event_narrative_messages(
                event, source_docs=event_docs, source_map=source_map
            )

            body = {"model": model, "messages": messages, **extra_params}
            line = {
                "custom_id": f"report_event_{event['id']}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": body,
            }
            lines.append(json.dumps(line, ensure_ascii=False))
            event_count += 1

    # Entity summaries
    for etype, entities in entities_by_type.items():
        for entity in entities:
            ent_docs = entity_docs_by_id.get(entity["id"], [])
            messages = _build_entity_summary_messages(
                entity,
                country,
                start_date,
                end_date,
                source_docs=ent_docs,
                source_map=source_map,
            )

            body = {"model": model, "messages": messages, **extra_params}
            line = {
                "custom_id": f"report_entity_{entity['id']}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": body,
            }
            lines.append(json.dumps(line, ensure_ascii=False))
            entity_count += 1

    if not lines:
        return "", 0, 0

    # Write to temp file
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".jsonl",
        prefix="report_batch_",
        delete=False,
        encoding="utf-8",
    )
    tmp.write("\n".join(lines) + "\n")
    tmp.close()

    if not quiet:
        size_kb = os.path.getsize(tmp.name) / 1024
        print(
            f"[Batch] JSONL prepared: {len(lines)} requests "
            f"({event_count} events, {entity_count} entities), "
            f"{size_kb:.1f} KB"
        )

    return tmp.name, event_count, entity_count


def submit_report_batch(
    jsonl_path: str,
    quiet: bool = False,
) -> str:
    """Upload JSONL and create batch job.

    Args:
        jsonl_path: Path to JSONL file.
        quiet: Suppress output.

    Returns:
        OpenAI batch ID.
    """
    client = _get_openai_client()

    if not quiet:
        print("[Batch] Uploading JSONL to OpenAI...")

    with open(jsonl_path, "rb") as f:
        file_obj = client.files.create(file=f, purpose="batch")

    if not quiet:
        print(f"[Batch] File uploaded: {file_obj.id}")
        print("[Batch] Creating batch job...")

    batch = client.batches.create(
        input_file_id=file_obj.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
    )

    if not quiet:
        print(f"[Batch] Batch created: {batch.id}")
        print(f"[Batch] Status: {batch.status}")

    return batch.id


def monitor_report_batch(
    batch_id: str,
    poll_interval: int = 60,
    max_duration: int = 86400,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Poll batch status until completion.

    Args:
        batch_id: OpenAI batch ID.
        poll_interval: Seconds between polls.
        max_duration: Maximum wait time in seconds.
        quiet: Suppress output.

    Returns:
        Final batch status dict with keys: status, output_file_id,
        request_counts, etc.

    Raises:
        TimeoutError: If max_duration exceeded.
        RuntimeError: If batch fails/expires/is cancelled.
    """
    client = _get_openai_client()
    start_time = time.time()

    while True:
        batch = client.batches.retrieve(batch_id)
        elapsed = int(time.time() - start_time)
        elapsed_str = f"{elapsed // 60}m{elapsed % 60:02d}s"

        counts = batch.request_counts
        completed = counts.completed if counts else 0
        failed = counts.failed if counts else 0
        total = counts.total if counts else 0

        if not quiet:
            print(
                f"[Batch] {elapsed_str} | Status: {batch.status} | "
                f"Progress: {completed}/{total} completed, {failed} failed"
            )

        if batch.status == "completed":
            if not quiet:
                print(f"[Batch] Batch completed in {elapsed_str}")
            return {
                "status": batch.status,
                "output_file_id": batch.output_file_id,
                "error_file_id": batch.error_file_id,
                "request_counts": {
                    "total": total,
                    "completed": completed,
                    "failed": failed,
                },
            }

        if batch.status in ("failed", "expired", "cancelled"):
            raise RuntimeError(
                f"Batch {batch_id} ended with status: {batch.status}"
            )

        if time.time() - start_time > max_duration:
            raise TimeoutError(
                f"Batch {batch_id} did not complete within "
                f"{max_duration // 3600}h. Current status: {batch.status}"
            )

        time.sleep(poll_interval)


def process_report_batch_results(
    batch_result: Dict[str, Any],
    quiet: bool = False,
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, str]]:
    """Download and parse batch results.

    Args:
        batch_result: Dict from monitor_report_batch().
        quiet: Suppress output.

    Returns:
        Tuple of:
        - event_narratives: {event_id: {"overview": str, "outcomes": str}}
        - entity_summaries: {entity_id: str}
    """
    client = _get_openai_client()
    output_file_id = batch_result["output_file_id"]

    if not quiet:
        print(f"[Batch] Downloading results from {output_file_id}...")

    content = client.files.content(output_file_id).text
    lines = content.strip().split("\n")

    event_narratives: Dict[str, Dict[str, str]] = {}
    entity_summaries: Dict[str, str] = {}
    errors = 0

    for line in lines:
        try:
            result = json.loads(line)
            custom_id = result["custom_id"]
            response_body = result.get("response", {}).get("body", {})
            choices = response_body.get("choices", [])

            if not choices:
                errors += 1
                continue

            content_str = choices[0].get("message", {}).get("content", "")

            if custom_id.startswith("report_event_"):
                event_id = custom_id[len("report_event_"):]
                # Parse JSON response
                text = content_str.strip()
                if text.startswith("```json"):
                    text = text[7:]
                if text.endswith("```"):
                    text = text[:-3]
                try:
                    parsed = json.loads(text.strip())
                    event_narratives[event_id] = {
                        "overview": parsed.get("overview", ""),
                        "outcomes": parsed.get("outcomes", ""),
                    }
                except json.JSONDecodeError:
                    event_narratives[event_id] = {
                        "overview": content_str,
                        "outcomes": "Detailed outcomes not available.",
                    }

            elif custom_id.startswith("report_entity_"):
                entity_id = custom_id[len("report_entity_"):]
                entity_summaries[entity_id] = content_str.strip()

        except Exception as e:
            errors += 1
            if not quiet:
                print(f"[Batch] Error parsing result line: {e}")

    if not quiet:
        print(
            f"[Batch] Parsed {len(event_narratives)} event narratives, "
            f"{len(entity_summaries)} entity summaries"
            + (f", {errors} errors" if errors else "")
        )

    # Download and log errors if any
    error_file_id = batch_result.get("error_file_id")
    if error_file_id and not quiet:
        try:
            error_content = client.files.content(error_file_id).text
            error_lines = [l for l in error_content.strip().split("\n") if l.strip()]
            if error_lines:
                print(f"[Batch] {len(error_lines)} error(s) from batch:")
                for el in error_lines[:5]:
                    err = json.loads(el)
                    print(f"  - {err.get('custom_id', '?')}: {err.get('error', {}).get('message', '?')}")
        except Exception:
            pass

    return event_narratives, entity_summaries


def generate_report_batch(
    country: str,
    start_date_str: str,
    end_date_str: str,
    recipient: Optional[str] = None,
    top_n: int = 10,
    model: str = "gpt-4o-mini",
    poll_interval: int = 60,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Batch-mode report generation.

    Identical to generate_report() but uses OpenAI Batch API for event
    narratives and entity summaries (50% cost reduction). Sequential
    calls (category narratives, synthesis, title) run normally after
    batch completes.

    Args:
        country: Initiating country.
        start_date_str: Start date (YYYY-MM-DD).
        end_date_str: End date (YYYY-MM-DD).
        recipient: Optional recipient country filter.
        top_n: Top events per category.
        model: LLM model name.
        poll_interval: Batch polling interval in seconds.
        quiet: Suppress progress output.

    Returns:
        Complete report dict (same structure as generate_report()).
    """
    from sqlalchemy import text as sa_text

    start_date = parse_date(start_date_str)
    end_date = parse_date(end_date_str)
    config = Config.from_yaml()

    def log(msg: str):
        if not quiet:
            print(msg, flush=True)

    # ── Steps 1-4: DB queries (identical to generate_report) ──

    with get_session() as session:
        log(f"[Report/Batch] Loading top events for {country} ({start_date} to {end_date})...")
        events_by_category = get_top_events_by_category(
            session, country, start_date, end_date, recipient, top_n
        )
        events_by_category = _deduplicate_and_backfill(
            events_by_category, session, country, start_date, end_date, recipient, top_n
        )

        total_events = sum(len(events) for events in events_by_category.values())
        log(f"[Report/Batch] Found {total_events} events across {len(events_by_category)} categories")

        if total_events == 0:
            return {
                "country": country,
                "title": f"{country} Report: No Events Found",
                "period_start": start_date.isoformat(),
                "period_end": end_date.isoformat(),
                "recipient_filter": recipient or "All",
                "generated_at": datetime.now().isoformat(),
                "overall_summary": "No events found for the selected criteria.",
                "categories": [],
                "metrics": {
                    "total_documents": 0, "total_events": 0,
                    "category_distribution": [], "subcategory_distribution": [],
                    "recipient_distribution": [], "materiality_histogram": [],
                },
                "materiality_trends": {
                    "trend_start": (start_date - timedelta(days=90)).isoformat(),
                    "recipient_series": {}, "overall_series": [],
                    "significant_changes": [],
                },
                "citations_by_event": [],
                "entities": [],
            }

        # Step 2: Document details
        log("[Report/Batch] Loading source documents...")
        documents_by_event = {}
        for category, events in events_by_category.items():
            for event in events:
                if event["doc_ids"]:
                    documents_by_event[event["id"]] = get_document_details(
                        session, event["doc_ids"]
                    )

        # Step 3: Metrics
        log("[Report/Batch] Computing metrics...")
        metrics = compute_metrics(
            session, country, start_date, end_date, recipient, events_by_category,
            valid_recipients=config.recipients,
        )

        # Step 3b: Entities
        log("[Report/Batch] Loading top entities...")
        entities_by_type = get_top_entities(
            session, country, start_date, end_date, recipient, top_n=5
        )
        total_entities = sum(len(ents) for ents in entities_by_type.values())
        log(f"[Report/Batch] Found {total_entities} entities across {len(entities_by_type)} types")

        # Step 3c: Materiality trends
        log("[Report/Batch] Computing materiality trends...")
        materiality_trends = compute_materiality_trends(
            session, country, start_date, end_date, recipient,
            valid_recipients=config.recipients,
        )

        # Entity doc details
        log("[Report/Batch] Loading entity source documents...")
        entity_docs_by_id = {}
        for etype, entities in entities_by_type.items():
            for entity in entities:
                if entity.get("doc_ids"):
                    entity_docs_by_id[entity["id"]] = get_document_details(
                        session, entity["doc_ids"][:5]
                    )

        # Load cached narratives from EventSummary table
        cached_narratives = {}
        try:
            all_event_names = [
                e["event_name"]
                for evts in events_by_category.values()
                for e in evts
            ]
            if all_event_names:
                cached_rows = session.execute(
                    sa_text("""
                        SELECT DISTINCT ON (event_name)
                            event_name, narrative_summary
                        FROM event_summaries
                        WHERE initiating_country = :country
                          AND event_name = ANY(:names)
                          AND is_deleted = false
                          AND narrative_summary IS NOT NULL
                        ORDER BY event_name, period_start DESC
                    """),
                    {"country": country, "names": all_event_names},
                ).fetchall()
                for row in cached_rows:
                    ns = row.narrative_summary or {}
                    if ns.get("overview"):
                        cached_narratives[row.event_name] = ns
                log(
                    f"[Report/Batch] Found {len(cached_narratives)}/{len(all_event_names)} "
                    "cached EventSummary narratives"
                )
        except Exception as e:
            log(f"[Report/Batch] Could not load cached narratives: {e}")

    # Step 4: Build global source map
    log("[Report/Batch] Building citation map...")
    source_map: Dict[str, int] = {}
    all_sources = []
    source_counter = 1

    for category in config.categories:
        events = events_by_category.get(category, [])
        for event in events[:top_n]:
            docs = documents_by_event.get(event["id"], [])
            for doc in docs[:5]:
                doc_id = doc["doc_id"]
                if doc_id not in source_map:
                    source_map[doc_id] = source_counter
                    all_sources.append({
                        "citation_number": source_counter,
                        "doc_id": doc_id,
                        "headline": doc["headline"],
                        "source_name": doc["source_name"],
                        "published_date": doc["published_date"],
                        "categories": doc["categories"],
                        "recipients": doc["recipients"],
                        "repo_hyperlink": build_hyperlink([doc_id]),
                    })
                    source_counter += 1

    for entity_id, docs in entity_docs_by_id.items():
        for doc in docs[:5]:
            doc_id = doc["doc_id"]
            if doc_id not in source_map:
                source_map[doc_id] = source_counter
                all_sources.append({
                    "citation_number": source_counter,
                    "doc_id": doc_id,
                    "headline": doc["headline"],
                    "source_name": doc["source_name"],
                    "published_date": doc["published_date"],
                    "categories": doc["categories"],
                    "recipients": doc["recipients"],
                    "repo_hyperlink": build_hyperlink([doc_id]),
                })
                source_counter += 1

    log(f"[Report/Batch] Total citations: {len(all_sources)}")

    # ── Step 5+7b: Batch event narratives + entity summaries ──

    jsonl_path, batch_event_count, batch_entity_count = prepare_report_batch_jsonl(
        events_by_category=events_by_category,
        entities_by_type=entities_by_type,
        source_map=source_map,
        documents_by_event=documents_by_event,
        entity_docs_by_id=entity_docs_by_id,
        config=config,
        country=country,
        start_date=start_date,
        end_date=end_date,
        model=model,
        cached_narratives=cached_narratives,
        quiet=quiet,
    )

    event_narratives: Dict[str, Dict[str, str]] = {}
    entity_summaries: Dict[str, str] = {}

    if jsonl_path:
        try:
            batch_id = submit_report_batch(jsonl_path, quiet=quiet)
            log(f"[Report/Batch] Batch submitted: {batch_id}")
            log(f"[Report/Batch] Polling every {poll_interval}s...")

            batch_result = monitor_report_batch(
                batch_id, poll_interval=poll_interval, quiet=quiet
            )
            event_narratives, entity_summaries = process_report_batch_results(
                batch_result, quiet=quiet
            )
        except Exception as e:
            log(f"[Report/Batch] Batch failed: {e}")
            log("[Report/Batch] Falling back to sequential LLM calls...")
            return _fallback_to_sequential(
                country, start_date_str, end_date_str, recipient, top_n, model
            )
        finally:
            # Clean up temp file
            try:
                os.unlink(jsonl_path)
            except OSError:
                pass
    else:
        log("[Report/Batch] All narratives cached — no batch needed")

    # ── Inject batch results into events ──

    for category, events in events_by_category.items():
        for event in events:
            # Use cached narrative first
            cached = cached_narratives.get(event["event_name"])
            if cached:
                event["overview"] = cached.get("overview", "")
                event["outcomes"] = cached.get("outcomes", "")
            elif event["id"] in event_narratives:
                event["overview"] = event_narratives[event["id"]].get("overview", "")
                event["outcomes"] = event_narratives[event["id"]].get("outcomes", "")
            else:
                event["overview"] = event.get("description") or f"Event: {event['event_name']}"
                event["outcomes"] = "Detailed outcomes not available."

    # ── Steps 6-8: Sequential LLM calls ──

    llm_available = _check_llm_availability()

    # Step 6: Category narratives (depend on event narratives)
    category_summaries = {}
    if llm_available:
        log("[Report/Batch] Generating category narratives (sequential)...")
        for category in config.categories:
            events = events_by_category.get(category, [])
            if not events:
                continue
            narrative = generate_category_narrative(
                country, category, events, source_map,
                documents_by_event, start_date, end_date,
                model=model,
            )
            category_summaries[category] = narrative
    else:
        log("[Report/Batch] Skipping category narratives (LLM unavailable)")
        for category in config.categories:
            events = events_by_category.get(category, [])
            if events:
                category_summaries[category] = (
                    f"Key developments in {category} during this period "
                    f"included {len(events)} significant events."
                )

    # Step 7: Overall synthesis (depends on category narratives)
    if llm_available:
        log("[Report/Batch] Generating overall synthesis...")
        overall_summary = generate_overall_synthesis(
            country, category_summaries, start_date, end_date, model=model
        )
    else:
        overall_summary = (
            f"This report covers {country}'s strategic activities from "
            f"{start_date} to {end_date}. {total_events} events were identified "
            f"across {len(events_by_category)} categories."
        )

    # Step 7b: Inject entity summaries from batch
    entities_output = []
    for etype, entities in entities_by_type.items():
        entity_list = []
        for entity in entities:
            summary = entity_summaries.get(entity["id"])
            if not summary:
                summary = (
                    f"{entity['name']} was mentioned in "
                    f"{entity['total_documents']} documents during this period."
                )

            entity_doc_citations = []
            for doc_id in entity.get("doc_ids", [])[:3]:
                if doc_id in source_map:
                    entity_doc_citations.append(source_map[doc_id])

            entity_list.append({
                "name": entity["name"],
                "entity_type": entity["entity_type"],
                "role": entity.get("role") or "Unknown",
                "country_affiliations": entity.get("country_affiliations", []),
                "total_documents": entity["total_documents"],
                "total_mention_days": entity["total_mention_days"],
                "first_mention_date": entity.get("first_mention_date"),
                "last_mention_date": entity.get("last_mention_date"),
                "primary_categories": entity.get("primary_categories", {}),
                "primary_recipients": entity.get("primary_recipients", {}),
                "summary": summary,
                "citation_numbers": entity_doc_citations,
                "doc_ids": entity.get("doc_ids", [])[:10],
            })

        if entity_list:
            type_labels = {
                "PERSON": "KEY PERSONS",
                "ORGANIZATION": "KEY ORGANIZATIONS",
                "COMPANY": "KEY COMPANIES",
                "LOCATION": "KEY LOCATIONS",
            }
            entities_output.append({
                "entity_type": etype.lower(),
                "type_label": type_labels.get(etype, etype + "S"),
                "entities": entity_list,
            })

    # Step 8: Title
    if llm_available:
        log("[Report/Batch] Generating title...")
        title = generate_publication_title(
            country, events_by_category, start_date, end_date, model=model
        )
    else:
        title = f"{country} Strategic Activities: {start_date.strftime('%B %Y')}"

    # Step 9: Build categories output
    categories_output = []
    for category in config.categories:
        events = events_by_category.get(category, [])
        if not events:
            continue
        sorted_events = sorted(events, key=lambda e: e["materiality_score"], reverse=True)
        categories_output.append({
            "category": category,
            "narrative": category_summaries.get(category, ""),
            "events": [
                {
                    "event_name": e["event_name"],
                    "first_mention_date": e["first_mention_date"],
                    "last_mention_date": e["last_mention_date"],
                    "article_count": e["article_count"],
                    "materiality_score": e["materiality_score"],
                    "overview": e.get("overview", ""),
                    "outcomes": e.get("outcomes", ""),
                    "material_justification": e.get("material_justification"),
                    "key_entities": e.get("key_entities", []),
                    "doc_ids": e["doc_ids"],
                }
                for e in sorted_events
            ],
        })

    # Step 10: Citations
    citations_by_event = _build_citations_output(
        config, events_by_category, documents_by_event, source_map,
        entities_by_type=entities_by_type, entity_docs_by_id=entity_docs_by_id,
    )

    # Assemble final report
    report = {
        "country": country,
        "title": title,
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "recipient_filter": recipient or "All",
        "generated_at": datetime.now().isoformat(),
        "overall_summary": overall_summary,
        "categories": categories_output,
        "entities": entities_output,
        "metrics": metrics,
        "materiality_trends": materiality_trends,
        "citations_by_event": citations_by_event,
    }

    log("[Report/Batch] Generation complete!")
    return report


def _fallback_to_sequential(
    country: str,
    start_date_str: str,
    end_date_str: str,
    recipient: Optional[str],
    top_n: int,
    model: str,
) -> Dict[str, Any]:
    """Fall back to standard sequential report generation."""
    from server.report_generator import generate_report
    return generate_report(
        country=country,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        recipient=recipient,
        top_n=top_n,
        model=model,
    )
