"""
Load Embeddings by Document ID from Local or S3 Parquet Files

This script loads embeddings from parquet files (local or S3) and populates
the pgvector database for specific document IDs. Useful for repopulating
embeddings for documents that were previously processed.

Usage:
    # Load from local parquet files by doc_id
    python services/pipeline/embeddings/load_embeddings_by_docid.py --source local --doc-ids doc1 doc2 doc3

    # Load from S3 parquet files by doc_id
    python services/pipeline/embeddings/load_embeddings_by_docid.py --source s3 --doc-ids doc1 doc2 doc3

    # Load all embeddings from local directory
    python services/pipeline/embeddings/load_embeddings_by_docid.py --source local --all

    # Load from specific files
    python services/pipeline/embeddings/load_embeddings_by_docid.py --source local --files file1.parquet file2.parquet

    # Dry run mode
    python services/pipeline/embeddings/load_embeddings_by_docid.py --source local --doc-ids doc1 --dry-run
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
import json

# Add project root to path for imports
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent.parent
sys.path.insert(0, str(project_root))

# Database imports
from sqlalchemy import text
from shared.database.database import get_session, get_engine
from shared.models.models import Document
from shared.utils.utils import Config

# LangChain imports
from langchain_community.vectorstores.pgvector import PGVector
from services.pipeline.embeddings.embedding_vectorstore import (
    chunk_store,
    stores
)

# API Client for S3 operations
from services.api.api_client import get_s3_api_client

cfg = Config.from_yaml()


class EmbeddingLoader:
    """Handles loading embeddings from parquet files (local or S3) by document ID."""

    def __init__(
        self,
        source: str = 'local',
        local_dir: str = './data/processed_embeddings',
        s3_bucket: str = 'morris-sp-bucket',
        s3_prefix: str = 'embeddings/',
        collection_name: str = 'chunk_embeddings',
        dry_run: bool = False,
        force_reprocess: bool = False,
        api_url: Optional[str] = None
    ):
        """
        Initialize the embedding loader.

        Args:
            source: Data source ('local' or 's3')
            local_dir: Local directory containing parquet files
            s3_bucket: S3 bucket name
            s3_prefix: S3 prefix/folder containing parquet files
            collection_name: Target LangChain collection name
            dry_run: If True, don't write to database
            force_reprocess: If True, reprocess docs even if already in collection
            api_url: FastAPI URL for S3 operations
        """
        self.source = source
        self.local_dir = Path(local_dir)
        self.s3_bucket = s3_bucket
        self.s3_prefix = s3_prefix.rstrip('/') + '/'
        self.collection_name = collection_name
        self.dry_run = dry_run
        self.force_reprocess = force_reprocess

        # Initialize API client for S3 operations
        if source == 's3':
            self.api_client = get_s3_api_client(api_url)

        # Map collection names to stores
        # The stores dict uses short keys: "chunk", "daily", etc.
        collection_map = {
            'chunk_embeddings': 'chunk',
            'chunk': 'chunk',
            'summary_embeddings': None,  # summary_store not in stores dict
            'daily_event_embeddings': 'daily',
            'daily': 'daily',
            'weekly_event_embeddings': 'weekly',
            'weekly': 'weekly',
            'monthly_event_embeddings': 'monthly',
            'monthly': 'monthly',
            'yearly_event_embeddings': 'yearly',
            'yearly': 'yearly',
        }

        # Get the vector store
        store_key = collection_map.get(collection_name)
        if store_key and store_key in stores:
            self.vector_store = stores[store_key]
        elif collection_name == 'summary_embeddings':
            # summary_store is available but not in stores dict
            from services.pipeline.embeddings.embedding_vectorstore import summary_store
            self.vector_store = summary_store
        else:
            raise ValueError(
                f"Collection '{collection_name}' not found. "
                f"Available: {', '.join(collection_map.keys())}"
            )

        print(f"Initialized EmbeddingLoader:")
        print(f"  Source: {source}")
        if source == 'local':
            print(f"  Local Directory: {self.local_dir.absolute()}")
        else:
            print(f"  S3 Bucket: {s3_bucket}")
            print(f"  S3 Prefix: {self.s3_prefix}")
            print(f"  API URL: {self.api_client.api_url}")
        print(f"  Collection: {collection_name}")
        print(f"  Dry Run: {dry_run}")
        print(f"  Force Reprocess: {force_reprocess}")

    def get_existing_doc_ids_in_collection(self) -> Set[str]:
        """
        Get all doc_ids that already exist in the vector store collection.

        Returns:
            Set of doc_ids that are already in the collection
        """
        if self.force_reprocess:
            return set()

        try:
            engine = get_engine()
            with engine.connect() as conn:
                query = text("""
                    SELECT DISTINCT cmetadata->>'doc_id' AS doc_id
                    FROM langchain_pg_embedding
                    WHERE collection_id = (
                        SELECT uuid FROM langchain_pg_collection WHERE name = :collection_name
                    )
                    AND cmetadata->>'doc_id' IS NOT NULL
                """)
                result = conn.execute(query, {"collection_name": self.collection_name})
                existing_ids = {row[0] for row in result if row[0]}
                print(f"Found {len(existing_ids)} existing documents in collection '{self.collection_name}'")
                return existing_ids
        except Exception as e:
            print(f"Warning: Could not check existing documents: {e}")
            return set()

    def list_local_parquet_files(self) -> List[Path]:
        """
        List all parquet files in the local directory.

        Returns:
            List of Path objects for parquet files
        """
        if not self.local_dir.exists():
            print(f"Error: Local directory does not exist: {self.local_dir}")
            return []

        parquet_files = list(self.local_dir.glob("*.parquet"))
        print(f"Found {len(parquet_files)} parquet files in {self.local_dir}")
        return parquet_files

    def list_s3_parquet_files(self) -> List[Dict[str, Any]]:
        """
        List all parquet files in S3 prefix.

        Returns:
            List of file metadata dictionaries
        """
        try:
            response = self.api_client.list_parquet_files(
                bucket=self.s3_bucket,
                prefix=self.s3_prefix,
                max_keys=10000
            )
            parquet_files = response.get('files', [])
            print(f"Found {len(parquet_files)} parquet files in s3://{self.s3_bucket}/{self.s3_prefix}")
            return parquet_files
        except Exception as e:
            print(f"Error listing S3 files: {e}")
            raise

    def load_local_parquet(self, file_path: Path) -> pd.DataFrame:
        """
        Load a parquet file from local filesystem.

        Args:
            file_path: Path to parquet file

        Returns:
            DataFrame containing parquet data
        """
        try:
            df = pd.read_parquet(file_path)
            print(f"  Loaded {len(df)} rows from {file_path.name}")
            return df
        except Exception as e:
            print(f"Error loading {file_path}: {e}")
            raise

    def load_s3_parquet(self, s3_key: str) -> pd.DataFrame:
        """
        Load a parquet file from S3.

        Args:
            s3_key: S3 object key

        Returns:
            DataFrame containing parquet data
        """
        try:
            df = self.api_client.download_parquet_as_dataframe(
                bucket=self.s3_bucket,
                key=s3_key
            )
            print(f"  Loaded {len(df)} rows from {s3_key}")
            return df
        except Exception as e:
            print(f"Error loading {s3_key}: {e}")
            raise

    def get_document_metadata(self, doc_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch document metadata from the database.

        Args:
            doc_ids: List of document IDs

        Returns:
            Dictionary mapping doc_id to metadata
        """
        metadata_map = {}

        with get_session() as session:
            # Query documents in batches
            batch_size = 1000
            for i in range(0, len(doc_ids), batch_size):
                batch_ids = doc_ids[i:i+batch_size]

                documents = session.query(Document).filter(
                    Document.doc_id.in_(batch_ids)
                ).all()

                for doc in documents:
                    metadata_map[doc.doc_id] = {
                        'doc_id': doc.doc_id,
                        'title': doc.title,
                        'date': doc.date.isoformat() if doc.date else None,
                        'source_name': doc.source_name,
                        'distilled_text': doc.distilled_text,
                        'event_name': doc.event_name,
                        'category': doc.category,
                        'subcategory': doc.subcategory,
                        'initiating_country': doc.initiating_country,
                        'recipient_country': doc.recipient_country,
                        'salience': doc.salience,
                        'salience_bool': doc.salience_bool,
                    }

        print(f"Fetched metadata for {len(metadata_map)} documents (out of {len(doc_ids)} requested)")
        return metadata_map

    def load_embeddings_from_local(
        self,
        doc_ids: Optional[List[str]] = None,
        specific_files: Optional[List[str]] = None,
        load_all: bool = False
    ) -> int:
        """
        Load embeddings from local parquet files by document ID.

        Args:
            doc_ids: List of document IDs to load
            specific_files: Optional list of specific filenames to process
            load_all: If True, load all embeddings from all files

        Returns:
            Number of embeddings inserted
        """
        print(f"\n{'='*80}")
        print("Loading embeddings from LOCAL parquet files")
        print(f"{'='*80}")

        # Get list of files to process
        if specific_files:
            files_to_process = [self.local_dir / filename for filename in specific_files]
        else:
            files_to_process = self.list_local_parquet_files()

        if not files_to_process:
            print("No parquet files found")
            return 0

        # Get existing doc_ids in collection
        existing_doc_ids = self.get_existing_doc_ids_in_collection()

        # Process each file
        total_inserted = 0
        all_embeddings_data = []

        for file_path in files_to_process:
            print(f"\nProcessing: {file_path.name}")

            # Load parquet file
            df = self.load_local_parquet(file_path)

            # Filter by doc_ids if specified
            if doc_ids and not load_all:
                df = df[df['doc_id'].isin(doc_ids)]
                print(f"  Filtered to {len(df)} rows matching requested doc_ids")

            if len(df) == 0:
                print(f"  No matching documents in this file")
                continue

            # Skip already-embedded docs unless force_reprocess
            if not self.force_reprocess and not load_all:
                initial_count = len(df)
                df = df[~df['doc_id'].isin(existing_doc_ids)]
                skipped = initial_count - len(df)
                if skipped > 0:
                    print(f"  Skipped {skipped} documents already in collection")

            if len(df) == 0:
                print(f"  All documents already in collection")
                continue

            # Collect embeddings data
            for _, row in df.iterrows():
                all_embeddings_data.append({
                    'doc_id': row['doc_id'],
                    'embedding': row['embedding'],
                    'text': row.get('text', ''),
                    'title': row.get('title', ''),
                    'chunk_index': row.get('chunk_index'),
                    'chunk_start_word': row.get('chunk_start_word'),
                    'chunk_end_word': row.get('chunk_end_word'),
                })

            print(f"  Prepared {len(df)} embeddings from this file")

        # Get unique doc_ids that need metadata
        unique_doc_ids = list({item['doc_id'] for item in all_embeddings_data})
        print(f"\nFetching metadata for {len(unique_doc_ids)} unique documents...")
        metadata_map = self.get_document_metadata(unique_doc_ids)

        # Prepare data for insertion
        documents_to_insert = []
        embeddings_to_insert = []
        metadatas_to_insert = []

        for item in all_embeddings_data:
            doc_id = item['doc_id']
            embedding = item['embedding']
            text = item['text']

            # Get metadata from database
            doc_metadata = metadata_map.get(doc_id, {})

            if not doc_metadata:
                print(f"Warning: Document {doc_id} not found in database, skipping")
                continue

            # Convert embedding if needed
            if isinstance(embedding, list):
                embedding = np.array(embedding, dtype=np.float32)
            elif isinstance(embedding, str):
                embedding = np.fromstring(embedding.strip('[]'), sep=',', dtype=np.float32)

            # Use text from parquet or distilled_text from database
            document_text = text or doc_metadata.get('distilled_text', '') or doc_metadata.get('title', '')

            # Prepare metadata for LangChain
            metadata = {
                'doc_id': doc_id,
                'title': item.get('title') or doc_metadata.get('title'),
                'date': doc_metadata.get('date'),
                'source_name': doc_metadata.get('source_name'),
                'event_name': doc_metadata.get('event_name'),
                'category': doc_metadata.get('category'),
                'subcategory': doc_metadata.get('subcategory'),
                'initiating_country': doc_metadata.get('initiating_country'),
                'recipient_country': doc_metadata.get('recipient_country'),
                'salience': doc_metadata.get('salience'),
                'salience_bool': doc_metadata.get('salience_bool'),
                'chunk_index': item.get('chunk_index'),
                'chunk_start_word': item.get('chunk_start_word'),
                'chunk_end_word': item.get('chunk_end_word'),
            }

            # Remove None values
            metadata = {k: v for k, v in metadata.items() if v is not None}

            documents_to_insert.append(document_text)
            embeddings_to_insert.append(embedding.tolist())
            metadatas_to_insert.append(metadata)

        print(f"\nPrepared {len(documents_to_insert)} embeddings for insertion")

        # Insert into pgvector
        if not self.dry_run and documents_to_insert:
            try:
                print(f"Inserting {len(documents_to_insert)} embeddings into {self.collection_name}...")
                self.vector_store.add_embeddings(
                    texts=documents_to_insert,
                    embeddings=embeddings_to_insert,
                    metadatas=metadatas_to_insert
                )
                print(f"✓ Successfully inserted {len(documents_to_insert)} embeddings")
                total_inserted = len(documents_to_insert)
            except Exception as e:
                print(f"✗ Error inserting embeddings: {e}")
                raise
        elif self.dry_run:
            print(f"[DRY RUN] Would insert {len(documents_to_insert)} embeddings")

        return total_inserted

    def load_embeddings_from_s3(
        self,
        doc_ids: Optional[List[str]] = None,
        specific_files: Optional[List[str]] = None,
        load_all: bool = False
    ) -> int:
        """
        Load embeddings from S3 parquet files by document ID.

        Args:
            doc_ids: List of document IDs to load
            specific_files: Optional list of specific filenames to process
            load_all: If True, load all embeddings from all files

        Returns:
            Number of embeddings inserted
        """
        print(f"\n{'='*80}")
        print("Loading embeddings from S3 parquet files")
        print(f"{'='*80}")

        # Get list of files to process
        if specific_files:
            files_to_process = []
            for filename in specific_files:
                s3_key = f"{self.s3_prefix}{filename}"
                files_to_process.append({'key': s3_key, 'filename': filename})
        else:
            files_to_process = self.list_s3_parquet_files()

        if not files_to_process:
            print("No parquet files found")
            return 0

        # Get existing doc_ids in collection
        existing_doc_ids = self.get_existing_doc_ids_in_collection()

        # Process each file
        total_inserted = 0
        all_embeddings_data = []

        for file_info in files_to_process:
            s3_key = file_info['key']
            filename = file_info['filename']
            print(f"\nProcessing: {filename}")

            # Load parquet file
            df = self.load_s3_parquet(s3_key)

            # Filter by doc_ids if specified
            if doc_ids and not load_all:
                df = df[df['doc_id'].isin(doc_ids)]
                print(f"  Filtered to {len(df)} rows matching requested doc_ids")

            if len(df) == 0:
                print(f"  No matching documents in this file")
                continue

            # Skip already-embedded docs unless force_reprocess
            if not self.force_reprocess and not load_all:
                initial_count = len(df)
                df = df[~df['doc_id'].isin(existing_doc_ids)]
                skipped = initial_count - len(df)
                if skipped > 0:
                    print(f"  Skipped {skipped} documents already in collection")

            if len(df) == 0:
                print(f"  All documents already in collection")
                continue

            # Collect embeddings data
            for _, row in df.iterrows():
                all_embeddings_data.append({
                    'doc_id': row['doc_id'],
                    'embedding': row['embedding'],
                    'text': row.get('text', ''),
                    'title': row.get('title', ''),
                    'chunk_index': row.get('chunk_index'),
                    'chunk_start_word': row.get('chunk_start_word'),
                    'chunk_end_word': row.get('chunk_end_word'),
                })

            print(f"  Prepared {len(df)} embeddings from this file")

        # Get unique doc_ids that need metadata
        unique_doc_ids = list({item['doc_id'] for item in all_embeddings_data})
        print(f"\nFetching metadata for {len(unique_doc_ids)} unique documents...")
        metadata_map = self.get_document_metadata(unique_doc_ids)

        # Prepare data for insertion
        documents_to_insert = []
        embeddings_to_insert = []
        metadatas_to_insert = []

        for item in all_embeddings_data:
            doc_id = item['doc_id']
            embedding = item['embedding']
            text = item['text']

            # Get metadata from database
            doc_metadata = metadata_map.get(doc_id, {})

            if not doc_metadata:
                print(f"Warning: Document {doc_id} not found in database, skipping")
                continue

            # Convert embedding if needed
            if isinstance(embedding, list):
                embedding = np.array(embedding, dtype=np.float32)
            elif isinstance(embedding, str):
                embedding = np.fromstring(embedding.strip('[]'), sep=',', dtype=np.float32)

            # Use text from parquet or distilled_text from database
            document_text = text or doc_metadata.get('distilled_text', '') or doc_metadata.get('title', '')

            # Prepare metadata for LangChain
            metadata = {
                'doc_id': doc_id,
                'title': item.get('title') or doc_metadata.get('title'),
                'date': doc_metadata.get('date'),
                'source_name': doc_metadata.get('source_name'),
                'event_name': doc_metadata.get('event_name'),
                'category': doc_metadata.get('category'),
                'subcategory': doc_metadata.get('subcategory'),
                'initiating_country': doc_metadata.get('initiating_country'),
                'recipient_country': doc_metadata.get('recipient_country'),
                'salience': doc_metadata.get('salience'),
                'salience_bool': doc_metadata.get('salience_bool'),
                'chunk_index': item.get('chunk_index'),
                'chunk_start_word': item.get('chunk_start_word'),
                'chunk_end_word': item.get('chunk_end_word'),
            }

            # Remove None values
            metadata = {k: v for k, v in metadata.items() if v is not None}

            documents_to_insert.append(document_text)
            embeddings_to_insert.append(embedding.tolist())
            metadatas_to_insert.append(metadata)

        print(f"\nPrepared {len(documents_to_insert)} embeddings for insertion")

        # Insert into pgvector
        if not self.dry_run and documents_to_insert:
            try:
                print(f"Inserting {len(documents_to_insert)} embeddings into {self.collection_name}...")
                self.vector_store.add_embeddings(
                    texts=documents_to_insert,
                    embeddings=embeddings_to_insert,
                    metadatas=metadatas_to_insert
                )
                print(f"✓ Successfully inserted {len(documents_to_insert)} embeddings")
                total_inserted = len(documents_to_insert)
            except Exception as e:
                print(f"✗ Error inserting embeddings: {e}")
                raise
        elif self.dry_run:
            print(f"[DRY RUN] Would insert {len(documents_to_insert)} embeddings")

        return total_inserted


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description='Load embeddings from local or S3 parquet files by document ID',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Load specific doc_ids from local parquet files
  python services/pipeline/embeddings/load_embeddings_by_docid.py --source local --doc-ids doc1 doc2 doc3

  # Load specific doc_ids from S3 parquet files
  python services/pipeline/embeddings/load_embeddings_by_docid.py --source s3 --doc-ids doc1 doc2 doc3

  # Load from specific files only
  python services/pipeline/embeddings/load_embeddings_by_docid.py --source local --files file1.parquet file2.parquet

  # Load all embeddings from local directory
  python services/pipeline/embeddings/load_embeddings_by_docid.py --source local --all

  # Dry run mode (no database writes)
  python services/pipeline/embeddings/load_embeddings_by_docid.py --source local --doc-ids doc1 --dry-run

  # Force reprocess (even if already in collection)
  python services/pipeline/embeddings/load_embeddings_by_docid.py --source local --doc-ids doc1 --force
        """
    )

    # Data source
    parser.add_argument(
        '--source',
        choices=['local', 's3'],
        required=True,
        help='Data source: local directory or S3 bucket'
    )

    # Document selection
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--doc-ids',
        nargs='+',
        help='Specific document IDs to load embeddings for'
    )
    group.add_argument(
        '--files',
        nargs='+',
        help='Specific parquet files to process'
    )
    group.add_argument(
        '--all',
        action='store_true',
        help='Load all embeddings from all files'
    )

    # Local source options
    parser.add_argument(
        '--local-dir',
        default='./data/processed_embeddings',
        help='Local directory containing parquet files (default: ./data/processed_embeddings)'
    )

    # S3 source options
    parser.add_argument(
        '--s3-bucket',
        default='morris-sp-bucket',
        help='S3 bucket name (default: morris-sp-bucket)'
    )
    parser.add_argument(
        '--s3-prefix',
        default='embeddings/',
        help='S3 prefix/folder containing parquet files (default: embeddings/)'
    )
    parser.add_argument(
        '--api-url',
        help='FastAPI URL for S3 operations (default: from env API_URL)'
    )

    # General options
    available_collections = [
        'chunk_embeddings', 'chunk',
        'summary_embeddings',
        'daily_event_embeddings', 'daily',
        'weekly_event_embeddings', 'weekly',
        'monthly_event_embeddings', 'monthly',
        'yearly_event_embeddings', 'yearly'
    ]
    parser.add_argument(
        '--collection',
        default='chunk_embeddings',
        choices=available_collections,
        help='Target LangChain collection name (default: chunk_embeddings)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run without inserting into database'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Reprocess documents even if already in collection'
    )

    args = parser.parse_args()

    # Initialize loader
    loader = EmbeddingLoader(
        source=args.source,
        local_dir=args.local_dir,
        s3_bucket=args.s3_bucket,
        s3_prefix=args.s3_prefix,
        collection_name=args.collection,
        dry_run=args.dry_run,
        force_reprocess=args.force,
        api_url=args.api_url
    )

    # Execute loading based on source
    start_time = datetime.now()

    try:
        if args.source == 'local':
            total_inserted = loader.load_embeddings_from_local(
                doc_ids=args.doc_ids,
                specific_files=args.files,
                load_all=args.all
            )
        else:  # s3
            total_inserted = loader.load_embeddings_from_s3(
                doc_ids=args.doc_ids,
                specific_files=args.files,
                load_all=args.all
            )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Print summary
        print(f"\n{'='*80}")
        print("LOADING SUMMARY")
        print(f"{'='*80}")
        print(f"Source: {args.source}")
        print(f"Collection: {args.collection}")
        print(f"Total embeddings inserted: {total_inserted}")
        print(f"Duration: {duration:.2f} seconds")
        print(f"Dry run: {args.dry_run}")

        sys.exit(0)

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
