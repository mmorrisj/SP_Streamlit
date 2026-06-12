"""
Unit tests for the UI-driven ingestion service
(services/pipeline/ingestion/ingestion_service.py).

These run without a database: the duplicate check is monkeypatched and
validation operates on temp files.
"""
import json

import pytest

from services.pipeline.ingestion import ingestion_service as svc


def make_dsr_doc(doc_id="doc-001", event_name="China-Egypt Port MOU", distilled="Distilled text."):
    """Minimal valid DSR record accepted by parse_doc."""
    return {
        "id": doc_id,
        "title": {"title": f"Title for {doc_id}"},
        "machineTranslations": {},
        "source": {
            "name": {"transliterated": "Test Source"},
            "geofocusCountry": "Egypt",
            "descriptor": "newspaper",
            "medium": "print",
            "country": {"physical": "Egypt", "editorial": "Egypt", "consumption": "Egypt"},
            "startDate": "2024-08-01T00:00:00Z",
        },
        "custom": {"atom": {"collection_name": "ne_auto"}},
        "auto": {"gai": [
            {},
            {
                "modelVersion": "gpt-4o-mini",
                "filter": {"identifier": "sp-1", "version": 3},
                "value": [
                    {"type": "event-name", "value": event_name},
                    {"type": "initiating-country", "value": "China"},
                    {"type": "recipient-country", "value": "Egypt"},
                    {"type": "category", "value": "Economic"},
                    {"type": "distilled-text", "value": distilled},
                ],
            },
        ]},
    }


@pytest.mark.unit
class TestDetectFileType:
    def test_json_extension_with_json_content(self):
        assert svc.detect_file_type("results.json", b'[{"id": 1}]') == svc.FILE_TYPE_DSR

    def test_csv_extension_with_csv_content(self):
        assert svc.detect_file_type("atom.csv", b"Title,Body\na,b") == svc.FILE_TYPE_ATOM

    def test_csv_extension_with_json_content_rejected(self):
        with pytest.raises(ValueError, match="appears to contain JSON"):
            svc.detect_file_type("atom.csv", b'[{"id": 1}]')

    def test_json_extension_with_non_json_content_rejected(self):
        with pytest.raises(ValueError, match="does not start with JSON"):
            svc.detect_file_type("results.json", b"Title,Body")

    def test_unsupported_extension_rejected(self):
        with pytest.raises(ValueError, match="Unsupported file type"):
            svc.detect_file_type("notes.txt", b"hello")

    def test_json_with_utf8_bom(self):
        assert svc.detect_file_type("results.json", "﻿[{}]".encode("utf-8")) == svc.FILE_TYPE_DSR


@pytest.mark.unit
class TestParseAll:
    def test_valid_invalid_and_duplicate_records(self):
        records = [
            make_dsr_doc("doc-001"),
            {"id": "doc-002"},  # missing auto.gai
            make_dsr_doc("doc-001"),  # within-file duplicate
        ]
        parsed, errors = svc._parse_all(records)

        assert [d.doc_id for d in parsed] == ["doc-001"]
        assert len(errors) == 2
        reasons = {e["doc_id"]: e["reason"] for e in errors}
        assert "auto.gai" in reasons["doc-002"]
        assert "Duplicate doc_id" in reasons["doc-001"]

    def test_parsed_fields(self):
        parsed, _ = svc._parse_all([make_dsr_doc()])
        doc = parsed[0]
        assert doc.initiating_country == "China"
        assert doc.recipient_country == "Egypt"
        assert doc.event_name == "China-Egypt Port MOU"
        assert doc.distilled_text == "Distilled text."


@pytest.mark.unit
class TestValidateDsr:
    def test_report_contents(self, tmp_path, monkeypatch):
        path = tmp_path / "results.json"
        path.write_text(json.dumps([
            make_dsr_doc("doc-001"),
            make_dsr_doc("doc-002", event_name=None, distilled=None),
            {"id": "doc-003"},  # unparseable
        ]))
        # doc-002 already exists in the "database"
        monkeypatch.setattr(svc, "_existing_doc_ids", lambda ids, chunk_size=1000: {"doc-002"})

        report, errors = svc._validate_dsr(str(path))

        assert report["file_type"] == svc.FILE_TYPE_DSR
        assert report["total_records"] == 3
        assert report["parseable"] == 2
        assert report["parse_errors"] == 1
        assert report["new_documents"] == 1
        assert report["existing_documents"] == 1
        assert report["runnable"] is True
        assert report["date_range"] == {"min": "2024-08-01", "max": "2024-08-01"}
        assert report["top_initiating_countries"][0]["country"] == "China"

        warning_codes = {w["code"] for w in report["warnings"]}
        assert "missing_event_name" in warning_codes
        assert "missing_distilled_text" in warning_codes

        assert len(report["sample"]) == 2
        assert errors[0]["doc_id"] == "doc-003"

    def test_empty_file_not_runnable(self, tmp_path, monkeypatch):
        path = tmp_path / "results.json"
        path.write_text(json.dumps([{"id": "bad"}]))
        monkeypatch.setattr(svc, "_existing_doc_ids", lambda ids, chunk_size=1000: set())

        report, _ = svc._validate_dsr(str(path))
        assert report["runnable"] is False
        assert report["not_runnable_reason"]

    def test_nested_list_structure(self, tmp_path, monkeypatch):
        """Some exports wrap documents one list level deeper."""
        path = tmp_path / "results.json"
        path.write_text(json.dumps([[make_dsr_doc("doc-001")], [make_dsr_doc("doc-002")]]))
        monkeypatch.setattr(svc, "_existing_doc_ids", lambda ids, chunk_size=1000: set())

        report, _ = svc._validate_dsr(str(path))
        assert report["parseable"] == 2


ATOM_CSV = (
    '"ATOM ID","Title","Body","Source Name","Source Date, Start","Collection Name"\n'
    '"A1","Article A","Some body text","Reuters","2024-08-01T00:00:00Z","ne_auto"\n'
    '"A2","Article A","Other text","AP","2024-08-02T00:00:00Z","ne_auto"\n'
    '"A3","Article B","","AP","2024-08-03T00:00:00Z","ne_auto"\n'
)


@pytest.mark.unit
class TestValidateAtomCsv:
    def test_runnable_with_counts(self, tmp_path, monkeypatch):
        path = tmp_path / "atom.csv"
        path.write_text(ATOM_CSV)
        monkeypatch.setattr(svc, "_existing_doc_ids", lambda ids, chunk_size=1000: set())

        report, errors = svc._validate_atom_csv(str(path))

        assert report["file_type"] == svc.FILE_TYPE_ATOM
        assert report["total_records"] == 3
        # A2 duplicate title dropped, A3 empty body dropped -> 1 usable row
        assert report["usable_rows"] == 1
        assert report["new_rows"] == 1
        assert report["runnable"] is True
        assert "LLM calls" in report["llm_cost_note"]
        assert errors == []

        warning_codes = {w["code"] for w in report["warnings"]}
        assert "empty_body" in warning_codes
        assert "duplicate_titles" in warning_codes
        assert report["collections"] == {"ne_auto": 3}

    def test_all_rows_already_ingested_not_runnable(self, tmp_path, monkeypatch):
        path = tmp_path / "atom.csv"
        path.write_text(ATOM_CSV)
        monkeypatch.setattr(svc, "_existing_doc_ids", lambda ids, chunk_size=1000: {"A1"})

        report, _ = svc._validate_atom_csv(str(path))
        assert report["already_in_db"] == 1
        assert report["new_rows"] == 0
        assert report["runnable"] is False
        assert "already in the database" in report["not_runnable_reason"]

    def test_missing_atom_id_column_not_runnable(self, tmp_path):
        path = tmp_path / "atom.csv"
        path.write_text(
            "Title,Body,Collection Name\n"
            "Article A,Some body text,ne_auto\n"
        )
        report, _ = svc._validate_atom_csv(str(path))
        assert report["runnable"] is False
        assert report["not_runnable_reason"]


@pytest.mark.unit
class TestRunAtomIngestion:
    def _capture_updates(self, monkeypatch):
        updates = []
        monkeypatch.setattr(svc, "_update_job", lambda job_id, **f: updates.append(f))
        monkeypatch.setattr(svc, "_cancel_requested", lambda job_id: False)
        return updates

    def test_completed_run_maps_progress_and_embeds(self, monkeypatch):
        updates = self._capture_updates(monkeypatch)
        embed_calls = []
        monkeypatch.setattr(
            svc, "_embed_documents",
            lambda job_id, ids, bs, progress: (embed_calls.append(ids) or ([], len(ids), False)),
        )

        def fake_process(csv_path, reprocess, progress_cb, should_cancel):
            progress_cb({"total_rows": 2, "extracted": 1, "non_salient": 1,
                         "skipped_existing": 0, "persisted": 0, "errors": 0})
            return {
                "total_rows": 2, "extracted": 1, "non_salient": 1,
                "skipped_existing": 0, "persisted": 1, "errors": 0,
                "persisted_doc_ids": ["A1"], "cancelled": False,
                "results_json": "/tmp/results.json",
            }

        monkeypatch.setattr(
            "services.pipeline.ingestion.atom_pipeline.process_atom_csv", fake_process
        )

        svc._run_atom_ingestion("job-1", "/tmp/atom.csv", {"embed_now": True})

        assert embed_calls == [["A1"]]
        final = updates[-1]
        assert final["status"] == svc.IngestionJobStatus.COMPLETED.value
        assert final["progress"]["loaded"] == 1
        assert final["progress"]["non_salient"] == 1
        assert final["progress"]["stage"] == "done"

    def test_cancelled_run_finalizes_cancelled(self, monkeypatch):
        updates = self._capture_updates(monkeypatch)
        monkeypatch.setattr(
            "services.pipeline.ingestion.atom_pipeline.process_atom_csv",
            lambda **kw: {"total_rows": 5, "extracted": 1, "non_salient": 0,
                          "skipped_existing": 0, "persisted": 1, "errors": 0,
                          "persisted_doc_ids": ["A1"], "cancelled": True,
                          "results_json": "/tmp/r.json"},
        )
        svc._run_atom_ingestion("job-1", "/tmp/atom.csv", {"embed_now": True})
        assert updates[-1]["status"] == svc.IngestionJobStatus.CANCELLED.value

    def test_row_errors_yield_completed_with_errors(self, monkeypatch):
        updates = self._capture_updates(monkeypatch)
        monkeypatch.setattr(
            "services.pipeline.ingestion.atom_pipeline.process_atom_csv",
            lambda **kw: {"total_rows": 3, "extracted": 1, "non_salient": 1,
                          "skipped_existing": 0, "persisted": 1, "errors": 1,
                          "persisted_doc_ids": ["A1"], "cancelled": False,
                          "results_json": "/tmp/r.json"},
        )
        svc._run_atom_ingestion("job-1", "/tmp/atom.csv", {"embed_now": False})
        final = updates[-1]
        assert final["status"] == svc.IngestionJobStatus.COMPLETED_WITH_ERRORS.value
        assert "failed salience/extraction" in final["error_log"][0]["reason"]


@pytest.mark.unit
def test_error_log_csv():
    class FakeJob:
        error_log = [
            {"doc_id": "doc-001", "stage": "parse", "reason": "bad record"},
            {"doc_id": "doc-002", "stage": "embed", "reason": "timeout, retried"},
        ]

    csv_text = svc.error_log_csv(FakeJob())
    lines = csv_text.strip().splitlines()
    assert lines[0] == "doc_id,stage,reason"
    assert len(lines) == 3
    assert '"timeout, retried"' in lines[2]
