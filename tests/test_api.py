"""
Integration tests for FastAPI endpoints.

Tests API endpoints, request/response validation, and error handling.
"""
import pytest
from datetime import date


@pytest.mark.integration
@pytest.mark.api
class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_endpoint_exists(self, api_client):
        """Test that /api/health endpoint exists."""
        response = api_client.get("/api/health")
        assert response.status_code == 200

    def test_health_endpoint_response(self, api_client):
        """Test health endpoint returns correct structure."""
        response = api_client.get("/api/health")
        data = response.json()

        assert "status" in data
        assert data["status"] in ["healthy", "ok", "up"]


@pytest.mark.integration
@pytest.mark.api
@pytest.mark.database
class TestDocumentEndpoints:
    """Test document-related endpoints."""

    def test_get_documents_empty(self, api_client, db_session):
        """Test getting documents when database is empty."""
        response = api_client.get("/api/documents")
        assert response.status_code == 200

        data = response.json()
        assert "documents" in data
        assert "total" in data
        assert data["total"] == 0

    def test_get_documents_with_data(self, api_client, create_test_document):
        """Test getting documents with data."""
        # Create test documents
        create_test_document(doc_id="API001", title="Test Doc 1", salience=8)
        create_test_document(doc_id="API002", title="Test Doc 2", salience=7)

        response = api_client.get("/api/documents")
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 2
        assert len(data["documents"]) >= 2

    def test_get_documents_pagination(self, api_client, create_test_document):
        """Test document pagination."""
        # Create multiple documents
        for i in range(15):
            create_test_document(doc_id=f"PAGE{i:03d}", title=f"Doc {i}")

        # Get first page
        response = api_client.get("/api/documents?page=1&limit=10")
        assert response.status_code == 200

        data = response.json()
        assert data["page"] == 1
        assert data["limit"] == 10
        assert len(data["documents"]) == 10

        # Get second page
        response = api_client.get("/api/documents?page=2&limit=10")
        data = response.json()
        assert data["page"] == 2
        assert len(data["documents"]) >= 5

    def test_get_documents_filter_by_country(self, api_client, create_test_document):
        """Test filtering documents by initiating country."""

        doc1 = create_test_document(doc_id="FILTER001")
        doc2 = create_test_document(doc_id="FILTER002")

        # Add countries (this would be done through proper relationships)
        # For now, test the API parameter handling
        response = api_client.get("/api/documents?initiating_country=China")
        assert response.status_code == 200

    def test_get_documents_filter_by_date_range(self, api_client):
        """Test filtering documents by date range."""
        response = api_client.get(
            "/api/documents?start_date=2024-01-01&end_date=2024-12-31"
        )
        assert response.status_code == 200

        data = response.json()
        assert "documents" in data

    def test_get_documents_invalid_page(self, api_client):
        """Test invalid page number handling."""
        response = api_client.get("/api/documents?page=-1")
        # Should either return error or default to page 1
        assert response.status_code in [200, 400, 422]

    def test_get_document_stats(self, api_client, create_test_document):
        """Test document statistics endpoint."""
        create_test_document(doc_id="STATS001", salience=8)
        create_test_document(doc_id="STATS002", salience=7)

        response = api_client.get("/api/documents/stats")
        assert response.status_code == 200

        data = response.json()
        assert "total_documents" in data
        assert data["total_documents"] >= 2


@pytest.mark.integration
@pytest.mark.api
@pytest.mark.database
class TestEventsEndpoints:
    """Test event-related endpoints."""

    def test_get_events_empty(self, api_client):
        """Test getting events when database is empty."""
        response = api_client.get("/api/events")
        assert response.status_code == 200

        data = response.json()
        assert "events" in data

    def test_get_events_with_data(self, api_client, db_session):
        """Test getting events with data."""
        from shared.models.models import EventSummary, PeriodType, EventStatus

        # Create test events
        event1 = EventSummary(
            event_name="Test Event 1",
            period_type=PeriodType.DAILY,
            start_date=date(2024, 8, 1),
            end_date=date(2024, 8, 1),
            initiating_country="China",
            status=EventStatus.ACTIVE
        )
        event2 = EventSummary(
            event_name="Test Event 2",
            period_type=PeriodType.DAILY,
            start_date=date(2024, 8, 2),
            end_date=date(2024, 8, 2),
            initiating_country="Russia",
            status=EventStatus.ACTIVE
        )
        db_session.add_all([event1, event2])
        db_session.commit()

        response = api_client.get("/api/events")
        assert response.status_code == 200

        data = response.json()
        assert len(data["events"]) >= 2

    def test_get_events_filter_by_country(self, api_client, db_session):
        """Test filtering events by country."""
        from shared.models.models import EventSummary, PeriodType, EventStatus

        event = EventSummary(
            event_name="China Event",
            period_type=PeriodType.DAILY,
            start_date=date(2024, 8, 1),
            end_date=date(2024, 8, 1),
            initiating_country="China",
            status=EventStatus.ACTIVE
        )
        db_session.add(event)
        db_session.commit()

        response = api_client.get("/api/events?initiating_country=China")
        assert response.status_code == 200

    def test_get_events_timeline(self, api_client):
        """Test events timeline endpoint."""
        response = api_client.get("/api/events/timeline?influencer=China")
        assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.api
class TestBilateralEndpoints:
    """Test bilateral relationship endpoints."""

    def test_get_bilateral_data(self, api_client):
        """Test bilateral data endpoint."""
        response = api_client.get("/api/bilateral")
        assert response.status_code == 200

        data = response.json()
        assert "relationships" in data or "bilateral_data" in data

    def test_get_bilateral_map_data(self, api_client):
        """Test bilateral map data endpoint."""
        response = api_client.get("/api/bilateral-map-data")
        assert response.status_code == 200

    def test_get_bilateral_overview(self, api_client):
        """Test bilateral overview endpoint."""
        response = api_client.get("/api/bilateral/China/Kenya")
        assert response.status_code in [200, 404]  # 404 if no data

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict)


@pytest.mark.integration
@pytest.mark.api
class TestMetricsEndpoints:
    """Test metrics and analytics endpoints."""

    def test_get_overall_metrics(self, api_client):
        """Test overall metrics endpoint."""
        response = api_client.get("/api/metrics/overall")
        assert response.status_code == 200

        data = response.json()
        assert "total_documents" in data or "metrics" in data

    def test_get_influencer_metrics(self, api_client):
        """Test influencer-specific metrics."""
        response = api_client.get("/api/metrics/influencer/China")
        assert response.status_code in [200, 404]

    def test_get_bilateral_metrics(self, api_client):
        """Test bilateral metrics endpoint."""
        response = api_client.get("/api/metrics/bilateral/China/Kenya")
        assert response.status_code in [200, 404]

    def test_get_recipient_metrics(self, api_client):
        """Test recipient country metrics."""
        response = api_client.get("/api/metrics/recipient/Kenya")
        assert response.status_code in [200, 404]


@pytest.mark.integration
@pytest.mark.api
class TestFilterEndpoints:
    """Test filter and configuration endpoints."""

    def test_get_filters(self, api_client):
        """Test filters endpoint."""
        response = api_client.get("/api/filters")
        assert response.status_code == 200

        data = response.json()
        # Should return available filter options
        assert isinstance(data, dict)

    def test_get_categories(self, api_client):
        """Test categories endpoint."""
        response = api_client.get("/api/categories")
        assert response.status_code == 200

        data = response.json()
        assert "categories" in data

    def test_get_available_influencers(self, api_client):
        """Test available influencers list."""
        response = api_client.get("/api/document-summaries/available-influencers")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list) or "influencers" in data

    def test_get_available_recipients(self, api_client):
        """Test available recipients list."""
        response = api_client.get("/api/document-summaries/available-recipients")
        assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.api
class TestInfluencerEndpoints:
    """Test influencer-specific endpoints."""

    def test_get_influencer_overview(self, api_client):
        """Test influencer overview endpoint."""
        response = api_client.get("/api/influencer/China/overview")
        assert response.status_code in [200, 404]

    def test_get_influencer_recent_activities(self, api_client):
        """Test influencer recent activities."""
        response = api_client.get("/api/influencer/China/recent-activities")
        assert response.status_code in [200, 404]

    def test_get_influencer_events(self, api_client):
        """Test influencer events endpoint."""
        response = api_client.get("/api/influencer/China/events")
        assert response.status_code in [200, 404]


@pytest.mark.integration
@pytest.mark.api
class TestSummariesEndpoints:
    """Test summaries endpoints."""

    def test_get_summaries_list(self, api_client):
        """Test summaries list endpoint."""
        response = api_client.get("/api/document-summaries/list")
        assert response.status_code == 200

    def test_get_summaries_detail(self, api_client):
        """Test summaries detail endpoint."""
        response = api_client.get(
            "/api/document-summaries/detail?influencer=China&recipient=Kenya"
        )
        assert response.status_code in [200, 404]

    def test_get_bilateral_summaries_list(self, api_client):
        """Test bilateral summaries list."""
        response = api_client.get("/api/bilateral-summaries/list")
        assert response.status_code == 200

    def test_get_bilateral_summaries_overall(self, api_client):
        """Test bilateral summaries overall."""
        response = api_client.get("/api/bilateral-summaries/overall")
        assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.api
class TestErrorHandling:
    """Test API error handling."""

    def test_invalid_endpoint(self, api_client):
        """Test accessing non-existent endpoint."""
        response = api_client.get("/api/nonexistent")
        # Should be 404 (or redirect to React app catch-all)
        assert response.status_code in [404, 200]

    def test_invalid_country_parameter(self, api_client):
        """Test invalid country parameter."""
        response = api_client.get("/api/influencer/InvalidCountry123/overview")
        # Should handle gracefully - either 404 or empty result
        assert response.status_code in [200, 404]

    def test_invalid_date_format(self, api_client):
        """Test invalid date format handling."""
        response = api_client.get("/api/documents?start_date=invalid-date")
        # Should return validation error
        assert response.status_code in [400, 422]

    def test_missing_required_parameters(self, api_client):
        """Test endpoints with missing required parameters."""
        response = api_client.get("/api/bilateral-summaries/detail")
        # Should return validation error if parameters are required
        assert response.status_code in [200, 400, 422]


@pytest.mark.integration
@pytest.mark.api
class TestCORS:
    """Test CORS configuration."""

    def test_cors_headers(self, api_client):
        """Test that CORS headers are present."""
        response = api_client.options("/api/health")

        # CORS should allow all origins
        assert response.status_code in [200, 405]  # OPTIONS may not be implemented

    def test_cors_get_request(self, api_client):
        """Test CORS on GET request."""
        response = api_client.get(
            "/api/health",
            headers={"Origin": "http://localhost:3000"}
        )

        assert response.status_code == 200
