"""Tests for the /analyze agent tools.

These exercise argument handling, query/result shaping, aggregation logic, and
error paths without a live database or LLM. DB access is faked at
shared.database.database.get_session; the RAG, citation, and LLM-provider
dependencies are injected as lightweight stand-ins.
"""
import datetime
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Context-manager session whose execute() returns canned rows."""

    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, stmt, params=None):
        self.executed.append((stmt, params))
        return _FakeResult(self._rows)


@pytest.fixture
def fake_session(monkeypatch):
    """Patch get_session to yield a _FakeSession over the rows the test sets."""
    holder = {"rows": []}

    def _factory():
        return _FakeSession(holder["rows"])

    monkeypatch.setattr("shared.database.database.get_session", _factory)
    return holder


class _FakeProvider:
    name = "fake"

    def __init__(self, text=""):
        self._text = text

    def complete(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        return types.SimpleNamespace(text=self._text, tool_calls=[])


# ---------------------------------------------------------------------------
# entity_lookup
# ---------------------------------------------------------------------------
def test_entity_lookup_shapes_matches(fake_session):
    from agent.tools.entity_lookup import TOOL
    fake_session["rows"] = [
        {
            "canonical_id": "e1", "name": "Xi Jinping", "entity_type": "person",
            "primary_role": "head_of_state", "initiating_country": "China",
            "country_affiliations": ["China"], "alternative_names": ["Xi"],
            "entity_description": "President of China.", "total_documents": 42,
            "total_mention_days": 30,
            "first_mention_date": datetime.date(2024, 1, 1),
            "last_mention_date": datetime.date(2024, 6, 1),
        }
    ]
    res = TOOL.run(name="Xi")
    assert res.ok
    m = res.data["matches"][0]
    assert m["canonical_id"] == "e1"
    assert m["aliases"] == ["Xi"]
    assert m["first_mention_date"] == "2024-01-01"  # date -> iso string


def test_entity_lookup_empty_returns_ok_no_match(fake_session):
    from agent.tools.entity_lookup import TOOL
    fake_session["rows"] = []
    res = TOOL.run(name="Nobody")
    assert res.ok and res.data["matches"] == []


def test_entity_lookup_requires_name():
    from agent.tools.entity_lookup import TOOL
    res = TOOL.run(name="  ")
    assert not res.ok and "required" in res.error


# ---------------------------------------------------------------------------
# entity_graph
# ---------------------------------------------------------------------------
def test_entity_graph_builds_nodes_and_edges(fake_session):
    from agent.tools.entity_graph import TOOL
    fake_session["rows"] = [
        {
            "from_id": "root", "to_id": "n2", "relationship_type": "works_with",
            "weight": 7, "description": "co-signed accord",
            "from_name": "Root Co", "to_name": "Partner Co",
            "from_type": "organization", "to_type": "organization",
        }
    ]
    res = TOOL.run(canonical_id="root", hops=1, min_cooccurrences=2)
    assert res.ok
    ids = {n["canonical_id"] for n in res.data["nodes"]}
    assert ids == {"root", "n2"}
    assert res.data["edges"][0]["weight"] == 7


def test_entity_graph_requires_id():
    from agent.tools.entity_graph import TOOL
    res = TOOL.run(canonical_id="")
    assert not res.ok


# ---------------------------------------------------------------------------
# event_timeline
# ---------------------------------------------------------------------------
def test_event_timeline_shapes_and_orders(fake_session):
    from agent.tools.event_timeline import TOOL
    fake_session["rows"] = [
        {
            "event_id": "ev1", "event_name": "Summit", "initiating_country": "China",
            "first_mention_date": datetime.date(2024, 2, 1),
            "last_mention_date": datetime.date(2024, 2, 3),
            "story_phase": "peak", "total_articles": 12, "source_count": 5,
            "primary_categories": {"Diplomacy": 10}, "primary_recipients": {"Egypt": 8},
            "material_score": 7.5, "consolidated_description": "A summit happened.",
        }
    ]
    res = TOOL.run(start_date="2024-01-01", end_date="2024-03-01", influencer="China")
    assert res.ok
    ev = res.data["events"][0]
    assert ev["material_score"] == 7.5
    assert ev["recipients"] == {"Egypt": 8}


def test_event_timeline_requires_dates():
    from agent.tools.event_timeline import TOOL
    res = TOOL.run(start_date="2024-01-01")
    assert not res.ok


# ---------------------------------------------------------------------------
# materiality_filter
# ---------------------------------------------------------------------------
def test_materiality_filter_shapes(fake_session):
    from agent.tools.materiality_filter import TOOL
    fake_session["rows"] = [
        {
            "event_id": "ev1", "event_name": "Big", "initiating_country": "China",
            "material_score": 9.0, "material_justification": "high impact",
            "total_articles": 20,
            "first_mention_date": datetime.date(2024, 1, 1),
            "last_mention_date": datetime.date(2024, 1, 5),
        }
    ]
    res = TOOL.run(event_ids=["ev1", "ev2"], min_score=5)
    assert res.ok
    assert res.data["events"][0]["material_score"] == 9.0
    assert res.data["input_count"] == 2


def test_materiality_filter_requires_event_ids():
    from agent.tools.materiality_filter import TOOL
    res = TOOL.run(event_ids=[])
    assert not res.ok


# ---------------------------------------------------------------------------
# country_grouping
# ---------------------------------------------------------------------------
def test_country_grouping_pair_aggregation(fake_session):
    from agent.tools.country_grouping import TOOL
    fake_session["rows"] = [
        {"event_id": "1", "initiating_country": "China",
         "primary_recipients": {"Egypt": 3, "Kenya": 1}, "material_score": 8.0},
        {"event_id": "2", "initiating_country": "China",
         "primary_recipients": {"Egypt": 2}, "material_score": 6.0},
    ]
    res = TOOL.run(event_ids=["1", "2"], group_by="pair")
    assert res.ok
    top = res.data["groups"][0]
    assert top["group"] == "China -> Egypt"
    assert top["event_count"] == 2
    assert top["avg_material_score"] == 7.0


def test_country_grouping_initiator(fake_session):
    from agent.tools.country_grouping import TOOL
    fake_session["rows"] = [
        {"event_id": "1", "initiating_country": "China",
         "primary_recipients": {"Egypt": 3}, "material_score": None},
    ]
    res = TOOL.run(event_ids=["1"], group_by="initiator")
    assert res.ok
    assert res.data["groups"][0]["group"] == "China"
    assert res.data["groups"][0]["avg_material_score"] is None


def test_country_grouping_requires_event_ids():
    from agent.tools.country_grouping import TOOL
    assert not TOOL.run(event_ids=[]).ok


# ---------------------------------------------------------------------------
# bilateral_context
# ---------------------------------------------------------------------------
def test_bilateral_context_found(fake_session):
    from agent.tools.bilateral_context import TOOL
    fake_session["rows"] = [
        {
            "initiating_country": "China", "recipient_country": "Egypt",
            "first_interaction_date": datetime.date(2020, 1, 1),
            "last_interaction_date": datetime.date(2024, 1, 1),
            "analysis_generated_at": datetime.datetime(2024, 6, 1, 12, 0),
            "total_documents": 500, "total_daily_events": 120,
            "count_by_category": {"Economic": 300},
            "count_by_source": {"Reuters": 100, "Xinhua": 80, "AP": 5},
            "activity_by_month": {"2024-01": 10},
            "relationship_summary": {"overview": "Strong ties."},
            "material_score_avg": 6.5, "material_score_median": 6.0,
        }
    ]
    res = TOOL.run(influencer="China", recipient="Egypt")
    assert res.ok and res.data["found"] is True
    assert res.data["summary"] == {"overview": "Strong ties."}
    assert res.data["material_score_avg"] == 6.5
    # top_sources keeps the highest-count sources
    assert "Reuters" in res.data["top_sources"]


def test_bilateral_context_not_found(fake_session):
    from agent.tools.bilateral_context import TOOL
    fake_session["rows"] = []
    res = TOOL.run(influencer="China", recipient="Atlantis")
    assert res.ok and res.data["found"] is False


def test_bilateral_context_requires_both(fake_session):
    from agent.tools.bilateral_context import TOOL
    assert not TOOL.run(influencer="China").ok


# ---------------------------------------------------------------------------
# citation_resolver
# ---------------------------------------------------------------------------
def test_citation_resolver_wraps_utils(monkeypatch):
    fake = types.ModuleType("shared.utils.citation_utils")
    fake.get_citations_for_doc_ids = lambda ids: [
        {"doc_id": "d1", "citation": "[Reuters | ATOM ID: d1 | T | 1 Jan]",
         "source_name": "Reuters", "title": "T", "date": "1 Jan"}
    ]
    fake.build_hyperlink = lambda ids: "https://atom/search?x=1"
    monkeypatch.setitem(sys.modules, "shared.utils.citation_utils", fake)

    from agent.tools.citation_resolver import TOOL
    res = TOOL.run(doc_ids=["d1", "d2", "d1"])  # dupes collapsed
    assert res.ok
    assert res.data["hyperlink"] == "https://atom/search?x=1"
    assert res.data["missing"] == ["d2"]
    assert res.citations == ["d1", "d2"]


def test_citation_resolver_requires_ids():
    from agent.tools.citation_resolver import TOOL
    assert not TOOL.run(doc_ids=[]).ok


# ---------------------------------------------------------------------------
# corroboration_check
# ---------------------------------------------------------------------------
def _inject_rag(monkeypatch, results):
    fake = types.ModuleType("services.chat.rag_service")
    fake.intelligent_search = lambda query, k=10, **kw: (results, {})
    monkeypatch.setitem(sys.modules, "services.chat.rag_service", fake)


def test_corroboration_check_classifies_stances(monkeypatch):
    _inject_rag(monkeypatch, [
        {"doc_id": "d1", "content": "Confirms the deal.", "title": "A",
         "source_name": "Reuters", "date": "2024-01-01",
         "initiating_country": "China", "recipient_country": "Egypt",
         "relevance_score": 0.9},
    ])
    monkeypatch.setattr(
        "agent.llm.provider.get_provider",
        lambda: _FakeProvider('{"stances": [{"n": 0, "stance": "supports", "why": "x"}]}'),
    )
    from agent.tools.corroboration_check import TOOL
    res = TOOL.run(claim="A deal was signed", top_k=5)
    assert res.ok
    assert res.data["candidates"][0]["stance"] == "supports"
    assert res.data["stance_tally"]["supports"] == 1
    assert res.data["diversity"]["distinct_sources"] == 1


def test_corroboration_check_degrades_without_llm(monkeypatch):
    _inject_rag(monkeypatch, [
        {"doc_id": "d1", "content": "text", "title": "A", "source_name": "Reuters",
         "date": "2024-01-01", "initiating_country": "China",
         "recipient_country": "Egypt", "relevance_score": 0.5},
    ])

    def _boom():
        raise RuntimeError("no llm")
    monkeypatch.setattr("agent.llm.provider.get_provider", _boom)

    from agent.tools.corroboration_check import TOOL
    res = TOOL.run(claim="something")
    assert res.ok  # still returns candidates
    assert res.data["candidates"][0]["stance"] is None
    assert res.data["stance_tally"]["unclassified"] == 1


def test_corroboration_check_requires_claim_or_event():
    from agent.tools.corroboration_check import TOOL
    assert not TOOL.run().ok


# ---------------------------------------------------------------------------
# briefing_generator
# ---------------------------------------------------------------------------
def test_briefing_generator_parses_json(monkeypatch):
    payload = (
        '{"title": "China-Egypt", "executive_summary": "Summary.", '
        '"key_judgments": [{"judgment": "j1", "confidence": "MED"}], '
        '"evidence": [{"source_id": "d1", "title": "t", "snippet": "s"}]}'
    )
    monkeypatch.setattr("agent.llm.provider.get_provider", lambda: _FakeProvider(payload))
    from agent.tools.briefing_generator import TOOL
    res = TOOL.run(query="China in Egypt", evidence=[{"source_id": "d1"}])
    assert res.ok
    b = res.data["briefing"]
    assert b["title"] == "China-Egypt"
    assert b["key_judgments"][0]["confidence"] == "MED"
    assert res.citations == ["d1"]
    # missing list fields are normalized to []
    assert b["information_gaps"] == []


def test_briefing_generator_prose_fallback(monkeypatch):
    monkeypatch.setattr(
        "agent.llm.provider.get_provider", lambda: _FakeProvider("just some prose")
    )
    from agent.tools.briefing_generator import TOOL
    res = TOOL.run(query="Q")
    assert res.ok
    assert res.data["briefing"]["executive_summary"] == "just some prose"
    assert res.data["briefing"]["title"] == "Q"


def test_briefing_generator_requires_query():
    from agent.tools.briefing_generator import TOOL
    assert not TOOL.run(query="").ok
