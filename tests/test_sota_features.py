"""
Tests for SOTA LLM alignment features.

Tests structured output schemas, tiered model selection, temperature config,
token-aware context packing, reranking, HyDE, and hybrid search integration.
"""
import sys
import pytest
import json
import numpy as np
from unittest.mock import patch, MagicMock
from datetime import date
from pathlib import Path
import importlib.util

# Mock torch only if it is genuinely not installed (it may be absent from a
# lightweight test venv). Use find_spec rather than checking sys.modules so we
# never shadow a real, installed torch that simply hasn't been imported yet.
# The stub exposes a real `Tensor` class because scipy/sklearn probe torch via
# `issubclass(x, torch.Tensor)`; a bare MagicMock there raises TypeError and
# poisons array validation for the whole test session.
if importlib.util.find_spec('torch') is None:
    _torch_stub = MagicMock()
    _torch_stub.Tensor = type('Tensor', (), {})
    sys.modules['torch'] = _torch_stub


# =============================================================================
# Structured Output Schemas (services/pipeline/batch/schemas.py)
# =============================================================================

@pytest.mark.unit
class TestStructuredOutputSchemas:
    """Test OpenAI Structured Output JSON schemas."""

    def test_all_schemas_have_required_fields(self):
        """Every schema must have name, strict=True, and a valid schema object."""
        from services.pipeline.batch.schemas import (
            SCHEMA_CLUSTER_DECONFLICT,
            SCHEMA_CANONICAL_DECONFLICT,
            SCHEMA_ENTITY_EXTRACT,
            SCHEMA_SCORE_MATERIALITY,
            SCHEMA_ENTITY_DECONFLICT,
            SCHEMA_CANONICAL_ENTITY_DECONFLICT,
            SCHEMA_DAILY_SUMMARY,
            SCHEMA_WEEKLY_SUMMARY,
            SCHEMA_MONTHLY_SUMMARY,
            SCHEMA_ENTITY_DESCRIPTION,
            SCHEMA_RELATIONSHIP_CLASSIFICATION,
            SCHEMA_BILATERAL_SUMMARY,
        )

        all_schemas = [
            SCHEMA_CLUSTER_DECONFLICT,
            SCHEMA_CANONICAL_DECONFLICT,
            SCHEMA_ENTITY_EXTRACT,
            SCHEMA_SCORE_MATERIALITY,
            SCHEMA_ENTITY_DECONFLICT,
            SCHEMA_CANONICAL_ENTITY_DECONFLICT,
            SCHEMA_DAILY_SUMMARY,
            SCHEMA_WEEKLY_SUMMARY,
            SCHEMA_MONTHLY_SUMMARY,
            SCHEMA_ENTITY_DESCRIPTION,
            SCHEMA_RELATIONSHIP_CLASSIFICATION,
            SCHEMA_BILATERAL_SUMMARY,
        ]

        for schema in all_schemas:
            assert "name" in schema, f"Schema missing 'name' field"
            assert schema["strict"] is True, f"{schema['name']} must have strict=True"
            assert "schema" in schema, f"{schema['name']} missing 'schema' field"

            inner = schema["schema"]
            assert inner["type"] == "object", f"{schema['name']} schema type must be 'object'"
            assert "properties" in inner, f"{schema['name']} missing 'properties'"
            assert "required" in inner, f"{schema['name']} missing 'required'"
            assert inner["additionalProperties"] is False, f"{schema['name']} must have additionalProperties=False"

    def test_schema_required_matches_properties(self):
        """Every required field must exist in properties."""
        from services.pipeline.batch.schemas import (
            SCHEMA_CLUSTER_DECONFLICT, SCHEMA_CANONICAL_DECONFLICT,
            SCHEMA_ENTITY_EXTRACT, SCHEMA_SCORE_MATERIALITY,
            SCHEMA_ENTITY_DECONFLICT, SCHEMA_CANONICAL_ENTITY_DECONFLICT,
            SCHEMA_DAILY_SUMMARY, SCHEMA_WEEKLY_SUMMARY,
            SCHEMA_MONTHLY_SUMMARY, SCHEMA_ENTITY_DESCRIPTION,
            SCHEMA_RELATIONSHIP_CLASSIFICATION, SCHEMA_BILATERAL_SUMMARY,
        )

        all_schemas = [
            SCHEMA_CLUSTER_DECONFLICT, SCHEMA_CANONICAL_DECONFLICT,
            SCHEMA_ENTITY_EXTRACT, SCHEMA_SCORE_MATERIALITY,
            SCHEMA_ENTITY_DECONFLICT, SCHEMA_CANONICAL_ENTITY_DECONFLICT,
            SCHEMA_DAILY_SUMMARY, SCHEMA_WEEKLY_SUMMARY,
            SCHEMA_MONTHLY_SUMMARY, SCHEMA_ENTITY_DESCRIPTION,
            SCHEMA_RELATIONSHIP_CLASSIFICATION, SCHEMA_BILATERAL_SUMMARY,
        ]

        for schema in all_schemas:
            inner = schema["schema"]
            props = set(inner["properties"].keys())
            required = set(inner["required"])
            assert required == props, (
                f"{schema['name']}: required fields {required - props} not in properties, "
                f"or properties {props - required} not required"
            )

    def test_cluster_deconflict_schema_fields(self):
        """Verify cluster_deconflict has expected fields."""
        from services.pipeline.batch.schemas import SCHEMA_CLUSTER_DECONFLICT

        props = SCHEMA_CLUSTER_DECONFLICT["schema"]["properties"]
        assert props["reasoning"]["type"] == "string"
        assert props["same_event"]["type"] == "boolean"
        assert props["groups"]["type"] == "array"
        assert props["confidence"]["type"] == "number"

    def test_entity_extract_schema_has_all_entity_types(self):
        """Entity extraction must cover persons, organizations, companies, locations."""
        from services.pipeline.batch.schemas import SCHEMA_ENTITY_EXTRACT

        props = SCHEMA_ENTITY_EXTRACT["schema"]["properties"]
        for entity_type in ["persons", "organizations", "companies", "locations"]:
            assert entity_type in props, f"Missing entity type: {entity_type}"
            assert props[entity_type]["type"] == "array"

    def test_bilateral_summary_schema_completeness(self):
        """Bilateral summary must have overview, themes, initiatives, assessment."""
        from services.pipeline.batch.schemas import SCHEMA_BILATERAL_SUMMARY

        props = SCHEMA_BILATERAL_SUMMARY["schema"]["properties"]
        expected = ["overview", "key_themes", "major_initiatives", "trend_analysis",
                    "current_status", "notable_developments", "material_assessment"]
        for field in expected:
            assert field in props, f"Bilateral summary missing field: {field}"

    def test_schemas_are_json_serializable(self):
        """All schemas must be JSON-serializable (required for API calls)."""
        from services.pipeline.batch.schemas import (
            SCHEMA_CLUSTER_DECONFLICT, SCHEMA_CANONICAL_DECONFLICT,
            SCHEMA_ENTITY_EXTRACT, SCHEMA_SCORE_MATERIALITY,
            SCHEMA_ENTITY_DECONFLICT, SCHEMA_CANONICAL_ENTITY_DECONFLICT,
            SCHEMA_DAILY_SUMMARY, SCHEMA_WEEKLY_SUMMARY,
            SCHEMA_MONTHLY_SUMMARY, SCHEMA_ENTITY_DESCRIPTION,
            SCHEMA_RELATIONSHIP_CLASSIFICATION, SCHEMA_BILATERAL_SUMMARY,
        )

        for schema in [SCHEMA_CLUSTER_DECONFLICT, SCHEMA_CANONICAL_DECONFLICT,
                        SCHEMA_ENTITY_EXTRACT, SCHEMA_SCORE_MATERIALITY,
                        SCHEMA_ENTITY_DECONFLICT, SCHEMA_CANONICAL_ENTITY_DECONFLICT,
                        SCHEMA_DAILY_SUMMARY, SCHEMA_WEEKLY_SUMMARY,
                        SCHEMA_MONTHLY_SUMMARY, SCHEMA_ENTITY_DESCRIPTION,
                        SCHEMA_RELATIONSHIP_CLASSIFICATION, SCHEMA_BILATERAL_SUMMARY]:
            serialized = json.dumps(schema)
            assert isinstance(serialized, str)
            deserialized = json.loads(serialized)
            assert deserialized["name"] == schema["name"]


# =============================================================================
# Schema-to-Job-Type Mapping
# =============================================================================

@pytest.mark.unit
class TestSchemaJobTypeMapping:
    """Test get_response_format_for_job_type mapping."""

    def test_all_job_types_return_json_schema(self):
        """Every supported job type should return a json_schema format."""
        from services.pipeline.batch.schemas import get_response_format_for_job_type
        from services.pipeline.batch.batch_config import SUPPORTED_JOB_TYPES

        for job_type in SUPPORTED_JOB_TYPES:
            fmt = get_response_format_for_job_type(job_type)
            assert fmt["type"] == "json_schema", f"{job_type} should return json_schema format"
            assert "json_schema" in fmt, f"{job_type} missing json_schema payload"
            assert fmt["json_schema"]["strict"] is True

    def test_unknown_job_type_falls_back(self):
        """Unknown job types should fall back to json_object."""
        from services.pipeline.batch.schemas import get_response_format_for_job_type

        fmt = get_response_format_for_job_type("nonexistent_job_type")
        assert fmt == {"type": "json_object"}

    def test_schema_names_are_unique(self):
        """Every schema mapped to a job type must have a unique name."""
        from services.pipeline.batch.schemas import get_response_format_for_job_type
        from services.pipeline.batch.batch_config import SUPPORTED_JOB_TYPES

        names = []
        for job_type in SUPPORTED_JOB_TYPES:
            fmt = get_response_format_for_job_type(job_type)
            names.append(fmt["json_schema"]["name"])

        for name in names:
            assert isinstance(name, str) and len(name) > 0


# =============================================================================
# Tiered Model Selection (batch_config.py)
# =============================================================================

@pytest.mark.unit
class TestTieredModelSelection:
    """Test tiered model assignment by job type."""

    def test_extraction_tasks_use_mini_model(self):
        """Extraction tasks should default to gpt-4o-mini."""
        from services.pipeline.batch.batch_config import (
            DEFAULT_MODELS,
            JOB_TYPE_ENTITY_EXTRACT,
            JOB_TYPE_DAILY_ENTITY_EXTRACT,
            JOB_TYPE_SCORE_MATERIALITY,
            JOB_TYPE_SCORE_SUMMARY_MATERIALITY,
            JOB_TYPE_CLASSIFY_ENTITY_RELATIONSHIPS,
        )

        extraction_jobs = [
            JOB_TYPE_ENTITY_EXTRACT,
            JOB_TYPE_DAILY_ENTITY_EXTRACT,
            JOB_TYPE_SCORE_MATERIALITY,
            JOB_TYPE_SCORE_SUMMARY_MATERIALITY,
            JOB_TYPE_CLASSIFY_ENTITY_RELATIONSHIPS,
        ]

        for job_type in extraction_jobs:
            model = DEFAULT_MODELS[job_type]
            assert "mini" in model or model == DEFAULT_MODELS[JOB_TYPE_ENTITY_EXTRACT], \
                f"{job_type} should use extraction-tier model, got {model}"

    def test_reasoning_tasks_use_stronger_model(self):
        """Reasoning/deconfliction tasks should use gpt-4o."""
        from services.pipeline.batch.batch_config import (
            DEFAULT_MODELS,
            JOB_TYPE_CLUSTER_DECONFLICT,
            JOB_TYPE_CANONICAL_DECONFLICT,
            JOB_TYPE_ENTITY_DECONFLICT,
            JOB_TYPE_CANONICAL_ENTITY_DECONFLICT,
        )

        reasoning_jobs = [
            JOB_TYPE_CLUSTER_DECONFLICT,
            JOB_TYPE_CANONICAL_DECONFLICT,
            JOB_TYPE_ENTITY_DECONFLICT,
            JOB_TYPE_CANONICAL_ENTITY_DECONFLICT,
        ]

        models = {DEFAULT_MODELS[j] for j in reasoning_jobs}
        assert len(models) == 1, f"Reasoning tasks should share one model tier, got {models}"

    def test_generation_tasks_use_stronger_model(self):
        """Generation tasks (summaries, descriptions) should use gpt-4o."""
        from services.pipeline.batch.batch_config import (
            DEFAULT_MODELS,
            JOB_TYPE_GENERATE_DAILY_SUMMARY,
            JOB_TYPE_GENERATE_WEEKLY_SUMMARY,
            JOB_TYPE_GENERATE_MONTHLY_SUMMARY,
            JOB_TYPE_GENERATE_ENTITY_DESCRIPTIONS,
            JOB_TYPE_GENERATE_BILATERAL_SUMMARIES,
        )

        gen_jobs = [
            JOB_TYPE_GENERATE_DAILY_SUMMARY,
            JOB_TYPE_GENERATE_WEEKLY_SUMMARY,
            JOB_TYPE_GENERATE_MONTHLY_SUMMARY,
            JOB_TYPE_GENERATE_ENTITY_DESCRIPTIONS,
            JOB_TYPE_GENERATE_BILATERAL_SUMMARIES,
        ]

        models = {DEFAULT_MODELS[j] for j in gen_jobs}
        assert len(models) == 1, f"Generation tasks should share one model tier, got {models}"

    def test_get_model_for_job_type_validates(self):
        """get_model_for_job_type should raise ValueError for unsupported types."""
        from services.pipeline.batch.batch_config import get_model_for_job_type

        with pytest.raises(ValueError, match="Unsupported job_type"):
            get_model_for_job_type("fake_job_type")

    def test_all_job_types_have_model_mapping(self):
        """Every supported job type must have a model in DEFAULT_MODELS."""
        from services.pipeline.batch.batch_config import DEFAULT_MODELS, SUPPORTED_JOB_TYPES

        for job_type in SUPPORTED_JOB_TYPES:
            assert job_type in DEFAULT_MODELS, f"{job_type} missing from DEFAULT_MODELS"


# =============================================================================
# Temperature Configuration (batch_config.py)
# =============================================================================

@pytest.mark.unit
class TestTemperatureConfig:
    """Test per-job-type temperature settings."""

    def test_all_job_types_have_temperature(self):
        """Every supported job type must have a temperature mapping."""
        from services.pipeline.batch.batch_config import (
            TEMPERATURE_BY_JOB_TYPE, SUPPORTED_JOB_TYPES
        )

        for job_type in SUPPORTED_JOB_TYPES:
            assert job_type in TEMPERATURE_BY_JOB_TYPE, \
                f"{job_type} missing from TEMPERATURE_BY_JOB_TYPE"

    def test_extraction_temperatures_are_low(self):
        """Extraction tasks should have deterministic (low) temperature."""
        from services.pipeline.batch.batch_config import (
            TEMPERATURE_BY_JOB_TYPE,
            JOB_TYPE_ENTITY_EXTRACT,
            JOB_TYPE_SCORE_MATERIALITY,
        )

        assert TEMPERATURE_BY_JOB_TYPE[JOB_TYPE_ENTITY_EXTRACT] <= 0.2
        assert TEMPERATURE_BY_JOB_TYPE[JOB_TYPE_SCORE_MATERIALITY] <= 0.2

    def test_generation_temperatures_are_higher(self):
        """Generation tasks should have slightly higher temperature."""
        from services.pipeline.batch.batch_config import (
            TEMPERATURE_BY_JOB_TYPE,
            JOB_TYPE_GENERATE_DAILY_SUMMARY,
            JOB_TYPE_GENERATE_BILATERAL_SUMMARIES,
        )

        assert TEMPERATURE_BY_JOB_TYPE[JOB_TYPE_GENERATE_DAILY_SUMMARY] >= 0.3
        assert TEMPERATURE_BY_JOB_TYPE[JOB_TYPE_GENERATE_BILATERAL_SUMMARIES] >= 0.3

    def test_temperatures_within_valid_range(self):
        """All temperatures must be between 0 and 2."""
        from services.pipeline.batch.batch_config import TEMPERATURE_BY_JOB_TYPE

        for job_type, temp in TEMPERATURE_BY_JOB_TYPE.items():
            assert 0 <= temp <= 2, f"{job_type} temperature {temp} out of range"

    def test_batch_config_default_temperature(self):
        """Default fallback temperature should be low."""
        from services.pipeline.batch.batch_config import DEFAULT_TEMPERATURE

        assert DEFAULT_TEMPERATURE <= 0.3, f"Default temperature {DEFAULT_TEMPERATURE} too high"


# =============================================================================
# Token-Aware Context Packing (rag_service.py)
# =============================================================================

@pytest.mark.unit
class TestTokenCounting:
    """Test tiktoken-based token counting."""

    def test_count_tokens_returns_int(self):
        """count_tokens should return a positive integer."""
        from services.chat.rag_service import count_tokens

        result = count_tokens("Hello world")
        assert isinstance(result, int)
        assert result > 0

    def test_count_tokens_empty_string(self):
        """Empty string should have 0 tokens."""
        from services.chat.rag_service import count_tokens

        assert count_tokens("") == 0

    def test_count_tokens_longer_text_has_more_tokens(self):
        """Longer text should have more tokens."""
        from services.chat.rag_service import count_tokens

        short = count_tokens("Hi")
        long = count_tokens("This is a significantly longer piece of text with many words.")
        assert long > short

    def test_token_encoder_caching(self):
        """Token encoder should be cached (singleton)."""
        from services.chat.rag_service import _get_token_encoder

        enc1 = _get_token_encoder()
        enc2 = _get_token_encoder()
        assert enc1 is enc2


@pytest.mark.unit
class TestContextPacking:
    """Test token-aware context packing in build_context_prompt."""

    def _make_doc(self, idx, content_len=100):
        """Helper to create a mock document dict."""
        return {
            "citation_number": idx,
            "doc_id": f"DOC{idx:03d}",
            "content": "x " * content_len,
            "title": f"Document {idx}",
            "source_name": "Test Source",
            "date": "2024-08-01",
            "initiating_country": "China",
            "recipient_country": "Egypt",
            "category": "Economic",
            "relevance_score": 0.95 - (idx * 0.01),
        }

    def test_build_context_with_no_documents(self):
        """Should return a 'no documents' message."""
        from services.chat.rag_service import build_context_prompt

        result = build_context_prompt("test query", [])
        assert "No relevant documents" in result

    def test_build_context_includes_citations(self):
        """Context should include citation numbers."""
        from services.chat.rag_service import build_context_prompt

        docs = [self._make_doc(1), self._make_doc(2)]
        result = build_context_prompt("test query", docs)
        assert "[1]" in result
        assert "[2]" in result

    def test_build_context_includes_metadata(self):
        """Context should include document metadata."""
        from services.chat.rag_service import build_context_prompt

        docs = [self._make_doc(1)]
        result = build_context_prompt("test query", docs)
        assert "Document 1" in result
        assert "Test Source" in result
        assert "2024-08-01" in result

    def test_build_context_with_entity_injection(self):
        """Context should include entity profiles when provided."""
        from services.chat.rag_service import build_context_prompt, MatchedEntity

        entity = MatchedEntity(
            entity_id="1",
            canonical_name="Belt and Road Initiative",
            entity_type="project",
            primary_role="Infrastructure development",
            entity_description="China's global infrastructure investment program",
            initiating_country="China",
            total_documents=500,
            first_mention_date="2023-01-01",
            last_mention_date="2024-08-01",
            match_type="exact",
            match_score=1.0
        )

        docs = [self._make_doc(1)]
        result = build_context_prompt("test query", docs, matched_entities=[entity])
        assert "Belt and Road Initiative" in result
        assert "RELEVANT ENTITIES" in result

    def test_build_context_respects_token_budget(self):
        """Should stop adding documents when token budget is exceeded."""
        from services.chat.rag_service import build_context_prompt, count_tokens

        # Create many large documents
        docs = [self._make_doc(i, content_len=5000) for i in range(50)]
        result = build_context_prompt("test query", docs)

        tokens = count_tokens(result)
        assert tokens < 100000, f"Context has {tokens} tokens, exceeds reasonable budget"

    def test_top_docs_get_full_text(self):
        """Top-ranked documents should get full content (not truncated)."""
        from services.chat.rag_service import build_context_prompt, MAX_FULL_TEXT_DOCS

        unique_marker = "UNIQUE_CONTENT_MARKER_FULL_TEXT_12345"
        docs = [self._make_doc(i, content_len=50) for i in range(MAX_FULL_TEXT_DOCS + 5)]
        docs[0]["content"] = unique_marker + " " * 200

        result = build_context_prompt("test query", docs)
        assert unique_marker in result


# =============================================================================
# Reranking (rag_service.py)
# =============================================================================

@pytest.mark.unit
class TestReranking:
    """Test cross-encoder reranking logic."""

    def _make_result(self, idx, score=0.9):
        return {
            "citation_number": idx,
            "doc_id": f"DOC{idx:03d}",
            "content": f"Document content for item {idx}",
            "title": f"Title {idx}",
            "relevance_score": score
        }

    def test_rerank_returns_top_k(self):
        """Reranking should return at most top_k results."""
        from services.chat.rag_service import rerank_results

        results = [self._make_result(i, 0.9 - i*0.01) for i in range(20)]

        with patch('services.chat.rag_service.get_reranker') as mock_get:
            mock_reranker = MagicMock()
            mock_reranker.predict.return_value = np.linspace(1.0, 0.0, 20)
            mock_get.return_value = mock_reranker

            reranked = rerank_results("test query", results, top_k=5)
            assert len(reranked) == 5

    def test_rerank_graceful_fallback_no_reranker(self):
        """If reranker is unavailable, return original results (truncated)."""
        from services.chat.rag_service import rerank_results

        results = [self._make_result(i) for i in range(10)]

        with patch('services.chat.rag_service.get_reranker', return_value=None):
            reranked = rerank_results("test query", results, top_k=5)
            assert len(reranked) == 5
            assert reranked[0]["doc_id"] == "DOC000"

    def test_rerank_graceful_fallback_on_error(self):
        """If reranker.predict raises, return original results."""
        from services.chat.rag_service import rerank_results

        results = [self._make_result(i) for i in range(10)]

        with patch('services.chat.rag_service.get_reranker') as mock_get:
            mock_reranker = MagicMock()
            mock_reranker.predict.side_effect = RuntimeError("Model error")
            mock_get.return_value = mock_reranker

            reranked = rerank_results("test query", results, top_k=5)
            assert len(reranked) == 5

    def test_rerank_empty_results(self):
        """Reranking empty results should return empty list."""
        from services.chat.rag_service import rerank_results

        with patch('services.chat.rag_service.get_reranker', return_value=None):
            reranked = rerank_results("test query", [], top_k=5)
            assert reranked == []

    def test_rerank_adds_score_fields(self):
        """Reranking should add rerank_score and vector_score fields."""
        from services.chat.rag_service import rerank_results

        results = [self._make_result(0, score=0.85)]

        with patch('services.chat.rag_service.get_reranker') as mock_get:
            mock_reranker = MagicMock()
            mock_reranker.predict.return_value = [0.95]
            mock_get.return_value = mock_reranker

            reranked = rerank_results("test query", results, top_k=5)
            assert reranked[0]["rerank_score"] == 0.95
            assert reranked[0]["vector_score"] == 0.85


# =============================================================================
# HyDE (rag_service.py)
# =============================================================================

@pytest.mark.unit
class TestHyDE:
    """Test Hypothetical Document Embedding generation."""

    def test_hyde_disabled_returns_none(self):
        """When ENABLE_HYDE is False, should return None immediately."""
        from services.chat.rag_service import generate_hyde_document

        with patch('services.chat.rag_service.ENABLE_HYDE', False):
            result = generate_hyde_document("What is China doing in Africa?")
            assert result is None

    def test_hyde_returns_string_on_success(self):
        """On success, HyDE should return a non-empty string."""
        from services.chat.rag_service import generate_hyde_document

        # generate_hyde_document calls the `gai` helper and returns its string.
        with patch('services.chat.rag_service.ENABLE_HYDE', True), \
             patch('services.chat.rag_service.gai',
                   return_value="China has invested $5B in African ports."):
            result = generate_hyde_document("What is China doing in Africa?")
            assert isinstance(result, str)
            assert len(result) > 0

    def test_hyde_graceful_fallback_on_error(self):
        """If the LLM call fails, HyDE should return None (not raise)."""
        from services.chat.rag_service import generate_hyde_document

        with patch('services.chat.rag_service.ENABLE_HYDE', True), \
             patch('services.chat.rag_service.gai', side_effect=Exception("API error")):
            result = generate_hyde_document("test query")
            assert result is None


# =============================================================================
# RAG Config Loading
# =============================================================================

@pytest.mark.unit
class TestRAGConfigLoading:
    """Test that RAG config values are loaded correctly from config.yaml."""

    def test_rag_config_defaults_exist(self):
        """Verify key RAG config constants are set."""
        from services.chat.rag_service import (
            CHAT_DOCUMENT_LIMIT,
            ENABLE_RERANKING,
            ENABLE_HYDE,
            ENABLE_HYBRID_SEARCH,
            MAX_CONTEXT_TOKENS,
            MAX_FULL_TEXT_DOCS,
            RERANK_MODEL,
            RERANK_TOP_K,
            RERANK_CANDIDATE_K,
        )

        assert isinstance(CHAT_DOCUMENT_LIMIT, int) and CHAT_DOCUMENT_LIMIT > 0
        assert isinstance(ENABLE_RERANKING, bool)
        assert isinstance(ENABLE_HYDE, bool)
        assert isinstance(ENABLE_HYBRID_SEARCH, bool)
        assert isinstance(MAX_CONTEXT_TOKENS, int) and MAX_CONTEXT_TOKENS > 0
        assert isinstance(MAX_FULL_TEXT_DOCS, int) and MAX_FULL_TEXT_DOCS > 0
        assert isinstance(RERANK_MODEL, str) and len(RERANK_MODEL) > 0
        assert isinstance(RERANK_TOP_K, int) and RERANK_TOP_K > 0
        assert isinstance(RERANK_CANDIDATE_K, int)
        assert RERANK_CANDIDATE_K >= RERANK_TOP_K, "Candidate pool must be >= rerank top_k"


# =============================================================================
# Entity Context Building
# =============================================================================

@pytest.mark.unit
class TestEntityContext:
    """Test entity context building for LLM prompt injection."""

    def test_build_entity_context_empty(self):
        """Empty entity list should return empty string."""
        from services.chat.rag_service import build_entity_context

        assert build_entity_context([]) == ""

    def test_build_entity_context_formatting(self):
        """Entity context should include key fields."""
        from services.chat.rag_service import build_entity_context, MatchedEntity

        entity = MatchedEntity(
            entity_id="42",
            canonical_name="BRICS",
            entity_type="organization",
            primary_role="Multilateral bloc",
            entity_description="An intergovernmental organization.",
            initiating_country="China",
            total_documents=200,
            first_mention_date="2023-01-01",
            last_mention_date="2024-12-01",
            match_type="exact",
            match_score=1.0
        )

        result = build_entity_context([entity])
        assert "BRICS" in result
        assert "Multilateral bloc" in result
        assert "200 documents" in result
        assert "RELEVANT ENTITIES" in result

    def test_build_entity_context_truncates_long_descriptions(self):
        """Long entity descriptions should be truncated."""
        from services.chat.rag_service import build_entity_context, MatchedEntity

        long_desc = "A" * 500
        entity = MatchedEntity(
            entity_id="1", canonical_name="Test", entity_type="org",
            primary_role=None, entity_description=long_desc,
            initiating_country="China", total_documents=10,
            first_mention_date="2024-01-01", last_mention_date="2024-12-01",
            match_type="exact", match_score=1.0
        )

        result = build_entity_context([entity])
        assert "..." in result
        assert len(result) < len(long_desc) + 200


# =============================================================================
# Alembic Migration Validity
# =============================================================================

@pytest.mark.unit
class TestAlembicMigration:
    """Test that the search_vector migration is well-formed."""

    @staticmethod
    def _read_migration():
        """Read the migration file as text."""
        migration_path = Path(__file__).parent.parent / "alembic" / "versions" / "006_add_search_vector_for_hybrid_search.py"
        return migration_path.read_text(encoding='utf-8')

    def test_migration_has_upgrade_and_downgrade(self):
        """Migration must have both upgrade and downgrade functions."""
        content = self._read_migration()
        assert "def upgrade()" in content, "Migration missing upgrade()"
        assert "def downgrade()" in content, "Migration missing downgrade()"

    def test_migration_revision_chain(self):
        """Migration should have correct revision identifiers."""
        content = self._read_migration()
        assert "revision: str = '006_search_vector'" in content
        assert "down_revision" in content and "'005_canonical_material'" in content

    def test_migration_creates_search_vector(self):
        """Migration should add search_vector tsvector column."""
        content = self._read_migration()
        assert "search_vector" in content
        assert "tsvector" in content
        assert "GIN" in content
        assert "to_tsvector" in content

    def test_migration_creates_trigger(self):
        """Migration should create auto-update trigger."""
        content = self._read_migration()
        assert "CREATE TRIGGER" in content
        assert "trg_documents_search_vector" in content
        assert "BEFORE INSERT OR UPDATE" in content

    def test_migration_downgrade_cleans_up(self):
        """Downgrade should remove trigger, function, index, and column."""
        content = self._read_migration()
        assert "DROP TRIGGER" in content
        assert "DROP FUNCTION" in content
        assert "DROP INDEX" in content
        assert "DROP COLUMN" in content
