"""
Unit tests for database models.

Tests model creation, relationships, validation, and serialization.
"""
import pytest
from datetime import date, datetime
from sqlalchemy.exc import IntegrityError


@pytest.mark.unit
@pytest.mark.database
class TestDocumentModel:
    """Test Document model functionality."""

    def test_create_document_minimal(self, db_session):
        """Test creating a document with minimal required fields."""
        from shared.models.models import Document

        doc = Document(
            doc_id="TEST001",
            title="Test Document"
        )
        db_session.add(doc)
        db_session.commit()

        assert doc.doc_id == "TEST001"
        assert doc.title == "Test Document"

    def test_create_document_full(self, db_session, sample_document_data):
        """Test creating a document with all fields."""
        from shared.models.models import Document

        doc = Document(**sample_document_data)
        db_session.add(doc)
        db_session.commit()

        assert doc.doc_id == sample_document_data["doc_id"]
        assert doc.title == sample_document_data["title"]
        assert doc.salience == sample_document_data["salience"]
        assert doc.initiating_country == sample_document_data["initiating_country"]

    def test_document_repr(self, create_test_document):
        """Test document string representation."""
        doc = create_test_document(doc_id="TEST002", title="My Test")

        repr_str = repr(doc)
        assert "TEST002" in repr_str
        assert "My Test" in repr_str

    def test_document_to_dict(self, create_test_document):
        """Test document serialization to dictionary."""
        doc = create_test_document(
            doc_id="TEST003",
            title="Test Doc",
            salience=7
        )

        doc_dict = doc.to_dict()
        assert doc_dict["doc_id"] == "TEST003"
        assert doc_dict["title"] == "Test Doc"
        assert doc_dict["salience"] == "7"

    def test_document_projects_property(self, db_session):
        """Test projects property getter/setter."""
        from shared.models.models import Document

        doc = Document(doc_id="TEST004", title="Test")
        doc.projects = "Belt and Road Initiative"

        db_session.add(doc)
        db_session.commit()

        assert doc.projects == "Belt and Road Initiative"

    def test_duplicate_doc_id_raises_error(self, db_session, create_test_document):
        """Test that duplicate doc_id raises integrity error."""
        from shared.models.models import Document

        create_test_document(doc_id="DUPLICATE001")

        # Try to create another with same doc_id
        doc2 = Document(doc_id="DUPLICATE001", title="Another")
        db_session.add(doc2)

        with pytest.raises(IntegrityError):
            db_session.commit()


@pytest.mark.unit
@pytest.mark.database
class TestCategoryModel:
    """Test Category model and relationships."""

    def test_create_category(self, db_session, create_test_document):
        """Test creating a category linked to a document."""
        from shared.models.models import Category

        doc = create_test_document(doc_id="CAT001")

        category = Category(doc_id=doc.doc_id, category="Economic")
        db_session.add(category)
        db_session.commit()

        assert category.doc_id == "CAT001"
        assert category.category == "Economic"

    def test_document_categories_relationship(self, db_session, create_test_document):
        """Test document-to-categories relationship."""
        from shared.models.models import Category

        doc = create_test_document(doc_id="CAT002")

        # Add multiple categories
        cat1 = Category(doc_id=doc.doc_id, category="Economic")
        cat2 = Category(doc_id=doc.doc_id, category="Political")
        db_session.add_all([cat1, cat2])
        db_session.commit()

        # Query categories through relationship
        categories = list(doc.categories.all())
        assert len(categories) == 2
        category_names = [c.category for c in categories]
        assert "Economic" in category_names
        assert "Political" in category_names

    def test_category_document_relationship(self, db_session, create_test_document):
        """Test category-to-document relationship."""
        from shared.models.models import Category

        doc = create_test_document(doc_id="CAT003", title="Test Title")
        category = Category(doc_id=doc.doc_id, category="Cultural")
        db_session.add(category)
        db_session.commit()

        # Access document through category
        assert category.document.doc_id == "CAT003"
        assert category.document.title == "Test Title"

    def test_category_composite_primary_key(self, db_session, create_test_document):
        """Test that category uses composite primary key."""
        from shared.models.models import Category

        doc = create_test_document(doc_id="CAT004")

        # Same doc_id and category should fail
        cat1 = Category(doc_id=doc.doc_id, category="Economic")
        db_session.add(cat1)
        db_session.commit()

        cat2 = Category(doc_id=doc.doc_id, category="Economic")
        db_session.add(cat2)

        with pytest.raises(IntegrityError):
            db_session.commit()


@pytest.mark.unit
@pytest.mark.database
class TestInitiatingCountryModel:
    """Test InitiatingCountry model."""

    def test_create_initiating_country(self, db_session, create_test_document):
        """Test creating an initiating country."""
        from shared.models.models import InitiatingCountry

        doc = create_test_document(doc_id="IC001")
        country = InitiatingCountry(doc_id=doc.doc_id, initiating_country="China")

        db_session.add(country)
        db_session.commit()

        assert country.initiating_country == "China"

    def test_multiple_initiating_countries(self, db_session, create_test_document):
        """Test document with multiple initiating countries."""
        from shared.models.models import InitiatingCountry

        doc = create_test_document(doc_id="IC002")

        countries = [
            InitiatingCountry(doc_id=doc.doc_id, initiating_country="China"),
            InitiatingCountry(doc_id=doc.doc_id, initiating_country="Russia")
        ]
        db_session.add_all(countries)
        db_session.commit()

        country_list = [c.initiating_country for c in doc.initiating_countries.all()]
        assert len(country_list) == 2
        assert "China" in country_list
        assert "Russia" in country_list


@pytest.mark.unit
@pytest.mark.database
class TestRecipientCountryModel:
    """Test RecipientCountry model."""

    def test_create_recipient_country(self, db_session, create_test_document):
        """Test creating a recipient country."""
        from shared.models.models import RecipientCountry

        doc = create_test_document(doc_id="RC001")
        country = RecipientCountry(doc_id=doc.doc_id, recipient_country="Kenya")

        db_session.add(country)
        db_session.commit()

        assert country.recipient_country == "Kenya"

    def test_multiple_recipient_countries(self, db_session, create_test_document):
        """Test document with multiple recipient countries."""
        from shared.models.models import RecipientCountry

        doc = create_test_document(doc_id="RC002")

        countries = [
            RecipientCountry(doc_id=doc.doc_id, recipient_country="Kenya"),
            RecipientCountry(doc_id=doc.doc_id, recipient_country="Tanzania"),
            RecipientCountry(doc_id=doc.doc_id, recipient_country="Uganda")
        ]
        db_session.add_all(countries)
        db_session.commit()

        country_list = [c.recipient_country for c in doc.recipient_countries.all()]
        assert len(country_list) == 3


@pytest.mark.unit
@pytest.mark.database
class TestRawEventModel:
    """Test RawEvent model."""

    def test_create_raw_event(self, db_session, create_test_document):
        """Test creating a raw event."""
        from shared.models.models import RawEvent

        doc = create_test_document(doc_id="RE001")

        event = RawEvent(
            doc_id=doc.doc_id,
            event_name="China announces infrastructure project",
            event_date=date(2024, 8, 1),
            lat_long="0.0,0.0",
            location="Nairobi",
            countries="China,Kenya"
        )
        db_session.add(event)
        db_session.commit()

        assert event.event_name == "China announces infrastructure project"
        assert event.event_date == date(2024, 8, 1)

    def test_raw_event_document_relationship(self, db_session, create_test_document):
        """Test raw event to document relationship."""
        from shared.models.models import RawEvent

        doc = create_test_document(doc_id="RE002")

        event = RawEvent(
            doc_id=doc.doc_id,
            event_name="Test Event"
        )
        db_session.add(event)
        db_session.commit()

        # Access document through event
        assert event.document.doc_id == "RE002"

        # Access events through document
        events = list(doc.raw_events.all())
        assert len(events) == 1
        assert events[0].event_name == "Test Event"


@pytest.mark.unit
@pytest.mark.database
class TestEventSummaryModel:
    """Test EventSummary consolidated model."""

    def test_create_daily_event_summary(self, db_session):
        """Test creating a daily event summary."""
        from shared.models.models import EventSummary, PeriodType, EventStatus

        event = EventSummary(
            event_name="China-Kenya Infrastructure Summit",
            event_summary="Test summary",
            period_type=PeriodType.DAILY,
            start_date=date(2024, 8, 1),
            end_date=date(2024, 8, 1),
            initiating_country="China",
            count_by_category={"Economic": 5, "Political": 2},
            count_by_recipient={"Kenya": 7},
            status=EventStatus.ACTIVE
        )
        db_session.add(event)
        db_session.commit()

        assert event.id is not None
        assert event.period_type == PeriodType.DAILY
        assert event.initiating_country == "China"
        assert event.status == EventStatus.ACTIVE

    def test_event_summary_jsonb_fields(self, db_session):
        """Test JSONB field storage and retrieval."""
        from shared.models.models import EventSummary, PeriodType, EventStatus

        event = EventSummary(
            event_name="Test Event",
            period_type=PeriodType.WEEKLY,
            start_date=date(2024, 8, 1),
            end_date=date(2024, 8, 7),
            initiating_country="China",
            count_by_category={"Economic": 10, "Cultural": 5},
            count_by_subcategory={"Infrastructure": 8, "Education": 2},
            count_by_recipient={"Kenya": 15},
            status=EventStatus.ACTIVE
        )
        db_session.add(event)
        db_session.commit()

        # Refresh from database
        db_session.refresh(event)

        assert event.count_by_category["Economic"] == 10
        assert event.count_by_category["Cultural"] == 5
        assert event.count_by_recipient["Kenya"] == 15

    def test_event_summary_with_embeddings(self, db_session):
        """Test event summary with embedding vector."""
        from shared.models.models import EventSummary, PeriodType, EventStatus

        embedding = [0.1] * 384  # 384-dimensional vector

        event = EventSummary(
            event_name="Test Event with Embedding",
            period_type=PeriodType.DAILY,
            start_date=date(2024, 8, 1),
            end_date=date(2024, 8, 1),
            initiating_country="China",
            embedding=embedding,
            status=EventStatus.ACTIVE
        )
        db_session.add(event)
        db_session.commit()

        db_session.refresh(event)
        assert event.embedding is not None
        assert len(event.embedding) == 384


@pytest.mark.unit
@pytest.mark.database
class TestEventSourceLinkModel:
    """Test EventSourceLink traceability model."""

    def test_create_event_source_link(self, db_session, create_test_document):
        """Test creating event-to-document link."""
        from shared.models.models import (
            EventSummary, EventSourceLink, PeriodType, EventStatus
        )

        doc = create_test_document(doc_id="ESL001")

        event = EventSummary(
            event_name="Test Event",
            period_type=PeriodType.DAILY,
            start_date=date(2024, 8, 1),
            end_date=date(2024, 8, 1),
            initiating_country="China",
            status=EventStatus.ACTIVE
        )
        db_session.add(event)
        db_session.commit()

        link = EventSourceLink(
            event_summary_id=event.id,
            doc_id=doc.doc_id,
            mention_date=date(2024, 8, 1)
        )
        db_session.add(link)
        db_session.commit()

        assert link.event_summary_id == event.id
        assert link.doc_id == doc.doc_id

    def test_event_source_link_relationships(self, db_session, create_test_document):
        """Test bidirectional relationships for event source links."""
        from shared.models.models import (
            EventSummary, EventSourceLink, PeriodType, EventStatus
        )

        doc = create_test_document(doc_id="ESL002")

        event = EventSummary(
            event_name="Test Event",
            period_type=PeriodType.DAILY,
            start_date=date(2024, 8, 1),
            end_date=date(2024, 8, 1),
            initiating_country="China",
            status=EventStatus.ACTIVE
        )
        db_session.add(event)
        db_session.commit()

        link = EventSourceLink(
            event_summary_id=event.id,
            doc_id=doc.doc_id,
            mention_date=date(2024, 8, 1)
        )
        db_session.add(link)
        db_session.commit()

        # Access event through link
        assert link.event_summary.event_name == "Test Event"

        # Access document through link
        assert link.document.doc_id == "ESL002"

        # Access links through event
        assert len(list(event.source_links.all())) == 1

        # Access links through document
        assert len(list(doc.event_source_links.all())) == 1
