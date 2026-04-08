"""Add HNSW index on langchain_pg_embedding for vector similarity search

With 659K+ embeddings and no vector index, every similarity search performs
a full sequential scan. HNSW provides sub-linear approximate nearest neighbor
search with minimal recall loss.

Revision ID: 20260403_hnsw_index
Revises: 20260403_enterprise_jwt
Create Date: 2026-04-03

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '20260403_hnsw_index'
down_revision: Union[str, None] = '20260403_enterprise_jwt'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # LangChain creates the embedding column as untyped `vector` (no dimensions).
    # HNSW indexes require a fixed-dimension type. First alter the column to
    # vector(768) to match the nomic-embed-text-v1.5 model output, then create
    # the index.
    op.execute(
        """
        ALTER TABLE langchain_pg_embedding
        ALTER COLUMN embedding TYPE vector(768);
        """
    )

    # HNSW index for cosine similarity on the embedding column.
    # m=16: connections per node (default, good balance of recall vs build time)
    # ef_construction=64: build-time search width (higher = better recall, slower build)
    # Expected build time: ~5-15 minutes for 659K vectors at 768 dimensions.
    op.execute(
        """
        CREATE INDEX ix_langchain_pg_embedding_hnsw
        ON langchain_pg_embedding
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
        """
    )


def downgrade() -> None:
    op.drop_index('ix_langchain_pg_embedding_hnsw', table_name='langchain_pg_embedding')
    op.execute(
        """
        ALTER TABLE langchain_pg_embedding
        ALTER COLUMN embedding TYPE vector;
        """
    )
