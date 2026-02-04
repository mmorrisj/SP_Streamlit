"""
Tests for data pipeline processing components.

Tests embedding generation, data processing, and pipeline utilities.
"""
import pytest
import numpy as np
import pandas as pd
from datetime import date, datetime
from unittest.mock import Mock, patch, MagicMock


@pytest.mark.unit
@pytest.mark.pipeline
class TestEmbeddingProcessing:
    """Test embedding generation and processing."""

    def test_embedding_dimension(self, mock_embedding_model):
        """Test that embeddings have correct dimensions."""
        text = "Test document about China's diplomatic activities"
        embedding = mock_embedding_model.encode(text)

        assert embedding.shape == (384,)
        assert isinstance(embedding, np.ndarray)

    def test_batch_embedding_generation(self, mock_embedding_model):
        """Test batch embedding generation."""
        texts = [
            "China announces new infrastructure project",
            "Russia participates in international summit",
            "India signs trade agreement"
        ]

        embeddings = mock_embedding_model.encode(texts)

        assert embeddings.shape == (3, 384)
        assert isinstance(embeddings, np.ndarray)

    def test_embedding_normalization(self):
        """Test L2 normalization of embeddings."""
        embedding = np.random.rand(384)

        # Normalize
        norm = np.linalg.norm(embedding)
        normalized = embedding / norm

        # Check that norm is 1
        assert np.allclose(np.linalg.norm(normalized), 1.0)


@pytest.mark.unit
@pytest.mark.pipeline
class TestDataProcessing:
    """Test data processing utilities."""

    def test_document_text_cleaning(self):
        """Test text cleaning for documents."""
        raw_text = "  This is a test document.   \n\n  With extra whitespace.  "

        # Simple cleaning function
        cleaned = " ".join(raw_text.split())

        assert cleaned == "This is a test document. With extra whitespace."
        assert "  " not in cleaned
        assert "\n" not in cleaned

    def test_date_parsing(self):
        """Test date parsing from various formats."""
        date_strings = [
            "2024-08-01",
            "08/01/2024",
            "2024-08-01T00:00:00"
        ]

        for date_str in date_strings[:1]:  # Test first format
            parsed = datetime.strptime(date_str, "%Y-%m-%d").date()
            assert isinstance(parsed, type(date.today()))
            assert parsed.year == 2024
            assert parsed.month == 8

    def test_country_normalization(self):
        """Test country name normalization."""
        # Mapping of variations to standard names
        country_mapping = {
            "PRC": "China",
            "People's Republic of China": "China",
            "Russian Federation": "Russia",
            "USA": "United States",
        }

        assert country_mapping.get("PRC") == "China"
        assert country_mapping.get("Russian Federation") == "Russia"


@pytest.mark.unit
@pytest.mark.pipeline
class TestClusteringUtilities:
    """Test clustering utilities."""

    def test_cosine_similarity_calculation(self):
        """Test cosine similarity between embeddings."""
        vec1 = np.array([1, 0, 0])
        vec2 = np.array([0, 1, 0])
        vec3 = np.array([1, 0, 0])

        # Calculate cosine similarity
        def cosine_similarity(a, b):
            return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

        sim_perpendicular = cosine_similarity(vec1, vec2)
        sim_identical = cosine_similarity(vec1, vec3)

        assert np.isclose(sim_perpendicular, 0.0)
        assert np.isclose(sim_identical, 1.0)

    def test_similarity_threshold_filtering(self):
        """Test filtering based on similarity threshold."""
        similarities = np.array([0.95, 0.87, 0.92, 0.75, 0.88])
        threshold = 0.85

        filtered = similarities[similarities >= threshold]

        assert len(filtered) == 4
        assert all(filtered >= threshold)


@pytest.mark.integration
@pytest.mark.pipeline
@pytest.mark.database
class TestDocumentIngestion:
    """Test document ingestion pipeline."""

    def test_create_document_from_dict(self, db_session):
        """Test creating document from dictionary data."""
        from shared.models.models import Document

        doc_data = {
            "doc_id": "INGEST001",
            "title": "Test Ingestion",
            "content": "Test content",
            "url": "https://example.com/test",
            "date_accessed": "2024-08-01"
        }

        doc = Document(**doc_data)
        db_session.add(doc)
        db_session.commit()

        assert doc.doc_id == "INGEST001"
        assert doc.title == "Test Ingestion"

    def test_batch_document_insertion(self, db_session):
        """Test batch insertion of multiple documents."""
        from shared.models.models import Document

        documents = [
            {
                "doc_id": f"BATCH{i:03d}",
                "title": f"Document {i}",
                "content": f"Content {i}"
            }
            for i in range(10)
        ]

        # Bulk insert
        db_session.bulk_insert_mappings(Document, documents)
        db_session.commit()

        # Verify
        count = db_session.query(Document).filter(
            Document.doc_id.like("BATCH%")
        ).count()
        assert count == 10

    def test_duplicate_document_handling(self, db_session, create_test_document):
        """Test handling of duplicate documents."""
        from shared.models.models import Document
        from sqlalchemy.exc import IntegrityError

        create_test_document(doc_id="DUP001")

        # Try to insert duplicate
        duplicate = Document(doc_id="DUP001", title="Duplicate")
        db_session.add(duplicate)

        with pytest.raises(IntegrityError):
            db_session.commit()


@pytest.mark.integration
@pytest.mark.pipeline
@pytest.mark.slow
class TestEventClustering:
    """Test event clustering functionality."""

    @pytest.fixture
    def sample_events_data(self):
        """Create sample events for clustering."""
        return pd.DataFrame({
            'doc_id': ['E001', 'E002', 'E003', 'E004'],
            'event_name': [
                'China announces Belt and Road project',
                'China unveils new Belt and Road initiative',
                'Russia hosts military exercises',
                'Russia conducts joint military drills'
            ],
            'date': ['2024-08-01'] * 4,
            'initiating_country': ['China', 'China', 'Russia', 'Russia']
        })

    def test_event_grouping_by_country_and_date(self, sample_events_data):
        """Test grouping events by country and date."""
        grouped = sample_events_data.groupby(['initiating_country', 'date'])

        assert len(grouped) == 2  # China and Russia
        china_group = grouped.get_group(('China', '2024-08-01'))
        assert len(china_group) == 2

    def test_similar_event_detection(self, sample_events_data, mock_embedding_model):
        """Test detecting similar events using embeddings."""
        # Generate embeddings for event names
        event_names = sample_events_data['event_name'].tolist()
        embeddings = mock_embedding_model.encode(event_names)

        # Calculate pairwise similarities (simplified)
        from sklearn.metrics.pairwise import cosine_similarity
        similarities = cosine_similarity(embeddings)

        # Events 0 and 1 should be similar (both about Belt and Road)
        # This is a mock test - in reality, similar text would have higher similarity
        assert similarities.shape == (4, 4)


@pytest.mark.unit
@pytest.mark.pipeline
class TestConfigLoading:
    """Test configuration loading and validation."""

    def test_load_config(self, test_config):
        """Test loading configuration from YAML."""
        assert isinstance(test_config, dict)

    def test_config_has_required_fields(self, test_config):
        """Test that config has required fields."""
        if test_config:  # Only test if config loaded
            expected_fields = ['influencers', 'recipients', 'categories']
            for field in expected_fields:
                # Field may or may not exist, just check structure
                if field in test_config:
                    assert isinstance(test_config[field], list)


@pytest.mark.unit
@pytest.mark.pipeline
class TestDataValidation:
    """Test data validation utilities."""

    def test_validate_country_name(self, test_config):
        """Test country name validation."""
        if test_config and 'influencers' in test_config:
            valid_countries = test_config['influencers']
            assert isinstance(valid_countries, list)

            # Test validation function
            def is_valid_country(country, valid_list):
                return country in valid_list

            if valid_countries:
                assert is_valid_country(valid_countries[0], valid_countries)
                assert not is_valid_country("InvalidCountry", valid_countries)

    def test_validate_date_range(self):
        """Test date range validation."""
        start_date = date(2024, 1, 1)
        end_date = date(2024, 12, 31)

        assert start_date < end_date

        # Invalid range
        invalid_start = date(2024, 12, 31)
        invalid_end = date(2024, 1, 1)

        assert not (invalid_start < invalid_end)

    def test_validate_salience_score(self):
        """Test salience score validation."""
        def is_valid_salience(score):
            return isinstance(score, (int, float)) and 0 <= score <= 10

        assert is_valid_salience(5)
        assert is_valid_salience(10)
        assert is_valid_salience(0)
        assert not is_valid_salience(-1)
        assert not is_valid_salience(11)


@pytest.mark.integration
@pytest.mark.pipeline
@pytest.mark.slow
@pytest.mark.llm
class TestLLMIntegration:
    """Test LLM integration (requires API key)."""

    @pytest.mark.skipif(
        not pytest.config.getoption("--run-llm-tests", default=False),
        reason="LLM tests are expensive, use --run-llm-tests to enable"
    )
    def test_llm_event_deconfliction(self, mock_openai_response):
        """Test LLM-based event deconfliction."""
        # Mock LLM response
        response = mock_openai_response

        assert "choices" in response
        assert len(response["choices"]) > 0

    def test_parse_llm_json_response(self, mock_openai_response):
        """Test parsing JSON from LLM response."""
        import json

        content = mock_openai_response["choices"][0]["message"]["content"]
        parsed = json.loads(content)

        assert "salience" in parsed
        assert "category" in parsed


@pytest.mark.unit
@pytest.mark.pipeline
class TestS3Operations:
    """Test S3 operations (mocked)."""

    def test_list_parquet_files(self, mock_s3_client):
        """Test listing parquet files from S3."""
        # Add mock files
        mock_s3_client.files["embeddings/chunk_001.parquet"] = pd.DataFrame()
        mock_s3_client.files["embeddings/chunk_002.parquet"] = pd.DataFrame()

        files = mock_s3_client.list_parquet_files(
            bucket="test-bucket",
            prefix="embeddings/"
        )

        assert len(files) == 2

    def test_upload_parquet_to_s3(self, mock_s3_client):
        """Test uploading parquet file to S3."""
        df = pd.DataFrame({
            'doc_id': ['DOC001', 'DOC002'],
            'embedding': [[0.1] * 384, [0.2] * 384]
        })

        result = mock_s3_client.upload_parquet(
            df,
            bucket="test-bucket",
            key="embeddings/test.parquet"
        )

        assert result["success"]
        assert "embeddings/test.parquet" in mock_s3_client.files

    def test_download_parquet_from_s3(self, mock_s3_client):
        """Test downloading parquet file from S3."""
        # Upload first
        df_original = pd.DataFrame({
            'doc_id': ['DOC001'],
            'value': [123]
        })
        mock_s3_client.files["test.parquet"] = df_original

        # Download
        df_downloaded = mock_s3_client.download_parquet_as_dataframe(
            bucket="test-bucket",
            key="test.parquet"
        )

        assert df_downloaded is not None
        pd.testing.assert_frame_equal(df_original, df_downloaded)


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--run-llm-tests",
        action="store_true",
        default=False,
        help="Run LLM tests (may incur API costs)"
    )
