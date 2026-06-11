"""Tests for the modern ATOM CSV pipeline (atom_pipeline.py).

LLM calls (shared.utils.utils.gai) and DB access are mocked; these cover CSV
parsing quirks, salience gating, extraction normalization, Document mapping,
the resumable results.json artifact, and the end-to-end flow.
"""
import json
import sys
import types

import pytest

# shared.utils.utils imports the OpenAI SDK at module top; stub it so the
# pipeline is testable without the package (gai itself is mocked in tests).
if "openai" not in sys.modules:
    _openai_stub = types.ModuleType("openai")
    _openai_stub.OpenAI = object
    _openai_stub.AzureOpenAI = object
    sys.modules["openai"] = _openai_stub

from services.pipeline.ingestion.atom_pipeline import (
    AtomRecord,
    _parse_date,
    build_document,
    classify_salience,
    extract_record,
    load_atom_csv,
    process_atom_csv,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _gai_response(payload: str):
    return {"choices": [{"message": {"content": payload}}]}


def _mock_gai(monkeypatch, replies):
    """Patch shared.utils.utils.gai to pop canned replies (in order)."""
    calls = []

    def fake_gai(sys_prompt, user_prompt, model="m", **kw):
        calls.append({"sys": sys_prompt, "user": user_prompt, "model": model})
        return _gai_response(replies.pop(0))

    monkeypatch.setattr("shared.utils.utils.gai", fake_gai)
    return calls


EXTRACTION_JSON = json.dumps({
    "salience-justification": "Clear soft power.",
    "salience-bool": True,
    "category": "Economic;Diplomacy",
    "category-justification": "Deal signed.",
    "subcategory": "Infrastructure",
    "initiating-country": "China",
    "recipient-country": "Egypt",
    "projects": "Suez Canal Zone Phase 2",
    "LAT_LONG": "30.5852,32.2654",
    "location": "Ismailia, Egypt",
    "monetary-commitment": "$1,000,000,000",
    "distilled-text": "China signed a deal with Egypt.",
    "event-name": "China-Egypt Suez Canal Economic Zone Phase 2 Expansion",
})


CSV_CONTENT = (
    '"ATOM ID","Title","Body","Source Name","Source Date, Start","Collection Name"\n'
    '"A1","China deal","China signed a big deal\nwith Egypt.","Reuters","2024-08-01T10:00:00Z","ne_auto"\n'
    '"A2","Sports","Local football match results.","AP","2024-08-02T10:00:00Z","ne_auto"\n'
    '"A3","China deal","Duplicate title row.","Xinhua","2024-08-03T10:00:00Z","ne_auto"\n'
    '"A4","No body","","AP","2024-08-03T10:00:00Z","ne_auto"\n'
)


@pytest.fixture
def csv_file(tmp_path):
    p = tmp_path / "atom_export.csv"
    p.write_text(CSV_CONTENT, encoding="utf-8-sig")
    return str(p)


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------
def test_load_atom_csv_basics(csv_file):
    records = load_atom_csv(csv_file)
    ids = [r.atom_id for r in records]
    assert ids == ["A1", "A2"]  # A3 dup title dropped, A4 empty body dropped
    r = records[0]
    assert r.title == "China deal"
    assert "\n" not in r.body
    assert r.source_name == "Reuters"
    assert r.date == "2024-08-01"
    assert r.collection_name == "ne_auto"


def test_load_atom_csv_collection_filter(csv_file):
    assert load_atom_csv(csv_file, collection="other") == []


def test_load_atom_csv_missing_columns(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("Foo,Bar\n1,2\n")
    with pytest.raises(ValueError, match="missing required columns"):
        load_atom_csv(str(p))


def test_parse_date_variants():
    assert _parse_date("2024-08-01T10:00:00Z") == "2024-08-01"
    assert _parse_date("2024-08-01") == "2024-08-01"
    assert _parse_date(None) is None
    assert _parse_date("not a date") is None


# ---------------------------------------------------------------------------
# LLM stages
# ---------------------------------------------------------------------------
def test_classify_salience_true_false(monkeypatch):
    _mock_gai(monkeypatch, ['{"salience": true}', '{"salience": false}'])
    rec = AtomRecord(atom_id="A1", title="t", body="b")
    assert classify_salience(rec) is True
    assert classify_salience(rec) is False


def test_classify_salience_rejects_garbage(monkeypatch):
    _mock_gai(monkeypatch, ['{"unexpected": 1}'])
    with pytest.raises(ValueError, match="unexpected salience output"):
        classify_salience(AtomRecord(atom_id="A1", title="t", body="b"))


def test_extract_record_returns_hyphen_keys(monkeypatch):
    _mock_gai(monkeypatch, [EXTRACTION_JSON])
    out = extract_record(AtomRecord(atom_id="A1", title="t", body="b"))
    assert out["event-name"].startswith("China-Egypt")
    assert out["salience-bool"] is True


# ---------------------------------------------------------------------------
# Document mapping
# ---------------------------------------------------------------------------
def test_build_document_maps_fields():
    rec = AtomRecord(
        atom_id="A1", title="China deal", body="...", source_name="Reuters",
        date="2024-08-01", collection_name="ne_auto",
    )
    doc = build_document(rec, json.loads(EXTRACTION_JSON), model="gpt-4o-mini")
    assert doc.doc_id == "A1"
    assert doc.salience_bool == "true"
    assert doc.category == "Economic;Diplomacy"
    assert doc.initiating_country == "China"
    assert doc.recipient_country == "Egypt"
    assert doc.lat_long == "30.5852,32.2654"
    assert doc.distilled_text == "China signed a deal with Egypt."
    assert doc.event_name == "China-Egypt Suez Canal Economic Zone Phase 2 Expansion"
    assert doc.date.isoformat() == "2024-08-01"
    assert doc.gai_promptid == "atom_pipeline_extraction"


def test_build_document_event_name_falls_back_to_projects():
    extraction = json.loads(EXTRACTION_JSON)
    extraction["event-name"] = "N/A"
    doc = build_document(
        AtomRecord(atom_id="A1", title="t", body="b"), extraction, model="m"
    )
    assert doc.event_name == "Suez Canal Zone Phase 2"


def test_build_document_normalizes_na():
    extraction = json.loads(EXTRACTION_JSON)
    extraction["monetary-commitment"] = "N/A"
    doc = build_document(
        AtomRecord(atom_id="A1", title="t", body="b"), extraction, model="m"
    )
    assert doc.monetary_commitment is None


# ---------------------------------------------------------------------------
# End-to-end (mocked gai + DB)
# ---------------------------------------------------------------------------
def test_process_atom_csv_end_to_end(monkeypatch, csv_file, tmp_path):
    # A1 salient -> extraction; A2 non-salient.
    _mock_gai(monkeypatch, ['{"salience": true}', EXTRACTION_JSON, '{"salience": false}'])

    persisted = []
    monkeypatch.setattr(
        "services.pipeline.ingestion.atom_pipeline._persist_documents",
        lambda docs: persisted.extend(docs),
    )
    monkeypatch.setattr(
        "services.pipeline.ingestion.atom_pipeline._existing_doc_ids",
        lambda ids: set(),
    )

    results_path = str(tmp_path / "results.json")
    summary = process_atom_csv(csv_file, results_path=results_path)

    assert summary["total_rows"] == 2
    assert summary["extracted"] == 1
    assert summary["non_salient"] == 1
    assert summary["errors"] == 0
    assert summary["persisted"] == 1
    assert persisted[0].doc_id == "A1"

    saved = json.loads(open(results_path).read())
    assert saved["A1"]["event-name"].startswith("China-Egypt")
    assert saved["A2"] == {"salience-bool": False}


def test_process_atom_csv_resumes_from_results(monkeypatch, csv_file, tmp_path):
    results_path = str(tmp_path / "results.json")
    with open(results_path, "w") as f:
        json.dump({"A1": json.loads(EXTRACTION_JSON)}, f)

    # Only A2 should hit the LLM (one salience call).
    calls = _mock_gai(monkeypatch, ['{"salience": false}'])
    monkeypatch.setattr(
        "services.pipeline.ingestion.atom_pipeline._existing_doc_ids",
        lambda ids: set(),
    )
    monkeypatch.setattr(
        "services.pipeline.ingestion.atom_pipeline._persist_documents",
        lambda docs: None,
    )

    summary = process_atom_csv(csv_file, results_path=results_path)
    assert summary["skipped_existing"] == 1
    assert len(calls) == 1


def test_process_atom_csv_dry_run_skips_db(monkeypatch, csv_file, tmp_path):
    _mock_gai(monkeypatch, ['{"salience": true}', EXTRACTION_JSON, '{"salience": false}'])

    def _boom(*a, **k):
        raise AssertionError("DB should not be touched in dry-run")

    monkeypatch.setattr(
        "services.pipeline.ingestion.atom_pipeline._persist_documents", _boom
    )
    monkeypatch.setattr(
        "services.pipeline.ingestion.atom_pipeline._existing_doc_ids", _boom
    )

    summary = process_atom_csv(
        csv_file, results_path=str(tmp_path / "r.json"), dry_run=True
    )
    assert summary["extracted"] == 1
    assert summary["persisted"] == 0


def test_process_atom_csv_records_errors(monkeypatch, csv_file, tmp_path):
    # First salience call explodes; second row proceeds normally.
    def fake_gai(sys_prompt, user_prompt, model="m", **kw):
        if "China signed" in user_prompt:
            raise RuntimeError("LLM down")
        return _gai_response('{"salience": false}')

    monkeypatch.setattr("shared.utils.utils.gai", fake_gai)
    monkeypatch.setattr(
        "services.pipeline.ingestion.atom_pipeline._existing_doc_ids", lambda ids: set()
    )
    monkeypatch.setattr(
        "services.pipeline.ingestion.atom_pipeline._persist_documents", lambda docs: None
    )

    results_path = str(tmp_path / "r.json")
    summary = process_atom_csv(csv_file, results_path=results_path)
    assert summary["errors"] == 1
    assert summary["non_salient"] == 1
    saved = json.loads(open(results_path).read())
    assert "salience" in saved["A1"]["error"]
