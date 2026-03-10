"""Add search_vector tsvector column to documents for hybrid BM25+vector search

Revision ID: 006_search_vector
Revises: 005_canonical_material
Create Date: 2026-03-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '006_search_vector'
down_revision: Union[str, None] = '005_canonical_material'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add tsvector column for BM25/full-text search
    op.execute("""
        ALTER TABLE documents
        ADD COLUMN IF NOT EXISTS search_vector tsvector
    """)

    # Populate tsvector from title + distilled_text (weighted: title=A, body=B)
    op.execute("""
        UPDATE documents
        SET search_vector =
            setweight(to_tsvector('english', COALESCE(title, '')), 'A') ||
            setweight(to_tsvector('english', COALESCE(distilled_text, '')), 'B')
        WHERE search_vector IS NULL
    """)

    # Create GIN index for fast full-text queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_search_vector
        ON documents USING GIN (search_vector)
    """)

    # Create trigger to auto-update search_vector on INSERT/UPDATE
    op.execute("""
        CREATE OR REPLACE FUNCTION documents_search_vector_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
                setweight(to_tsvector('english', COALESCE(NEW.distilled_text, '')), 'B');
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        DROP TRIGGER IF EXISTS trg_documents_search_vector ON documents
    """)

    op.execute("""
        CREATE TRIGGER trg_documents_search_vector
        BEFORE INSERT OR UPDATE OF title, distilled_text ON documents
        FOR EACH ROW EXECUTE FUNCTION documents_search_vector_update()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_documents_search_vector ON documents")
    op.execute("DROP FUNCTION IF EXISTS documents_search_vector_update()")
    op.execute("DROP INDEX IF EXISTS idx_documents_search_vector")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS search_vector")
