"""
S3 to pgvector Migration Script

This script pulls parquet files containing document embeddings from S3,
looks up document metadata from the database, and populates LangChain
pgvector tables for semantic search and retrieval.

Usage:
    python backend/scripts/s3_to_pgvector.py --s3-prefix embeddings/ --collection-name chunk_embeddings

    # Dry run mode (no database writes)
    python backend/scripts/s3_to_pgvector.py --s3-prefix embeddings/ --dry-run

    # Process specific files
    python backend/scripts/s3_to_pgvector.py --files file1.parquet file2.parquet
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import json

# Database imports
from sqlalchemy import text
from shared.database.database import get_session, get_engine
from shared.models.models import Document

# LangChain imports
from langchain_community.vectorstores.pgvector import PGVector
from langchain_huggingface import HuggingFaceEmbeddings
from services.pipeline.embeddings.embedding_vectorstore import (
    build_connection_string,
    chunk_store,
    summary_store,
    daily_store,
    weekly_store,
    monthly_store,
    yearly_store,
    stores
)

# API Client for S3 operations (runs outside Docker)
from services.api.api_client import get_s3_api_client


class S3ToPgVectorMigrator:
    """Handles migration of embeddings from S3 parquet files to pgvector database."""

    def __init__(
        self,
        bucket_name: str = 'morris-sp-bucket',
        s3_prefix: str = 'embeddings/',
        collection_name: str = 'chunk_embeddings',
        dry_run: bool = False,
        force_reprocess: bool = False,
        tracker_dir: str = './data/processed_embeddings',
        api_url: Optional[str] = None
    ):
        """
        Initialize the migrator.

        Args:
            bucket_name: S3 bucket name
            s3_prefix: S3 prefix/folder containing parquet files
            collection_name: Target LangChain collection name
            dry_run: If True, don't write to database
            force_reprocess: If True, reprocess files even if already processed
            tracker_dir: Local directory to store processed file tracker
            api_url: FastAPI URL for S3 operations (default: from env or localhost:8000)
        """
        self.bucket_name = bucket_name
        self.s3_prefix = s3_prefix.rstrip('/') + '/'
        self.collection_name = collection_name
        self.dry_run = dry_run
        self.force_reprocess = force_reprocess

        # Local tracker file
        self.tracker_dir = Path(tracker_dir)
        self.tracker_dir.mkdir(parents=True, exist_ok=True)
        self.tracker_file = self.tracker_dir / f"{collection_name}_processed.json"

        # Initialize API client for S3 operations
        self.api_client = get_s3_api_client(api_url)

        # Load processed files tracker
        self.processed_files = self._load_tracker()

        # Get the appropriate vector store
        if collection_name in stores:
            self.vector_store = stores[collection_name]
        else:
            # Create custom store if not predefined
            embedding_function = HuggingFaceEmbeddings(
                model_name="sentence-transformers/all-MiniLM-L6-v2"
            )
            self.vector_store = PGVector(
                collection_name=collection_name,
                connection_string=build_connection_string(),
                embedding_function=embedding_function,
            )

        print(f"Initialized S3ToPgVectorMigrator:")
        print(f"  Bucket: {bucket_name}")
        print(f"  S3 Prefix: {self.s3_prefix}")
        print(f"  Collection: {collection_name}")
        print(f"  API URL: {self.api_client.api_url}")
        print(f"  Tracker Dir: {self.tracker_dir.absolute()}")
        print(f"  Tracker File: {self.tracker_file.absolute()}")
        print(f"  Tracker Exists: {self.tracker_file.exists()}")
        print(f"  Previously Processed: {len(self.processed_files.get('files', []))} files")
        print(f"  Dry Run: {dry_run}")
        print(f"  Force Reprocess: {force_reprocess}")

    def _load_tracker(self) -> Dict[str, Any]:
        """Load the processed files tracker from local file."""
        if self.tracker_file.exists():
            try:
                with open(self.tracker_file, 'r') as f:
                    data = json.load(f)
                print(f"Loaded tracker with {len(data.get('files', []))} processed files")
                return data
            except Exception as e:
                print(f"Warning: Could not load tracker file: {e}")
                return {'files': [], 'last_updated': None}
        else:
            print("No existing tracker file found, creating new one")
            return {'files': [], 'last_updated': None}

    def _save_tracker(self):
        """Save the processed files tracker to local file."""
        try:
            self.processed_files['last_updated'] = datetime.utcnow().isoformat()

            # Ensure the directory exists
            self.tracker_dir.mkdir(parents=True, exist_ok=True)

            # Write to file
            with open(self.tracker_file, 'w') as f:
                json.dump(self.processed_files, f, indent=2)

            # Verify the file was written
            if not self.tracker_file.exists():
                raise FileNotFoundError(f"Tracker file was not created at {self.tracker_file}")

            # Verify content
            with open(self.tracker_file, 'r') as f:
                json.load(f)  # Just to verify it's valid JSON

            print(f"✓ Saved tracker to {self.tracker_file.absolute()}")

        except Exception as e:
            print(f"✗ Error: Could not save tracker file to {self.tracker_file.absolute()}: {e}")
            import traceback
            traceback.print_exc()

    def _mark_file_processed(self, filename: str, document_count: int):
        """Mark a file as processed in the tracker."""
        if 'files' not in self.processed_files:
            self.processed_files['files'] = []

        # Add file with metadata
        file_entry = {
            'filename': filename,
            'processed_at': datetime.utcnow().isoformat(),
            'document_count': document_count
        }

        # Remove if already exists (for reprocessing)
        self.processed_files['files'] = [
            f for f in self.processed_files['files']
            if f.get('filename') != filename
        ]

        self.processed_files['files'].append(file_entry)
        self._save_tracker()

    def _is_file_processed(self, filename: str) -> bool:
        """Check if a file has already been processed."""
        if self.force_reprocess:
            return False

        processed_filenames = [
            f.get('filename')
            for f in self.processed_files.get('files', [])
        ]
        return filename in processed_filenames

    def list_parquet_files(self, skip_processed: bool = True) -> List[Dict[str, Any]]:
        """
        List all parquet files in the S3 prefix via FastAPI.

        Args:
            skip_processed: If True, filter out already processed files

        Returns:
            List of file metadata dictionaries
        """
        try:
            # Use API client to list files
            response = self.api_client.list_parquet_files(
                bucket=self.bucket_name,
                prefix=self.s3_prefix,
                max_keys=10000
            )

            parquet_files = []
            for file_info in response.get('files', []):
                filename = file_info['filename']

                # Skip if already processed
                if skip_processed and self._is_file_processed(filename):
                    continue

                parquet_files.append(file_info)

            total_files = len(parquet_files)
            if skip_processed:
                processed_count = len(self.processed_files.get('files', []))
                print(f"Found {total_files} unprocessed parquet files (skipped {processed_count} already processed)")
            else:
                print(f"Found {total_files} parquet files in s3://{self.bucket_name}/{self.s3_prefix}")

            return parquet_files

        except Exception as e:
            print(f"Error listing S3 files: {e}")
            raise

    def download_parquet_file(self, s3_key: str, local_path: Optional[str] = None) -> pd.DataFrame:
        """
        Download and read a parquet file from S3 via FastAPI with full embeddings.

        Args:
            s3_key: S3 object key
            local_path: Not used (kept for compatibility)

        Returns:
            DataFrame containing complete parquet data including full embeddings
        """
        try:
            # Use API client to download full parquet file
            print(f"Downloading {s3_key} via API...")
            df = self.api_client.download_parquet_as_dataframe(
                bucket=self.bucket_name,
                key=s3_key
            )
            print(f"  Loaded {len(df)} rows from {s3_key}")

            return df

        except Exception as e:
            print(f"Error downloading {s3_key}: {e}")
            raise

    def get_existing_doc_ids_in_collection(self) -> set:
        """
        Get all doc_ids that already exist in the vector store collection.

        Returns:
            Set of doc_ids that are already in the collection
        """
        try:
            engine = get_engine()
            with engine.connect() as conn:
                # Query for doc_ids in the collection
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

    def validate_parquet_schema(self, df: pd.DataFrame) -> bool:
        """
        Validate that the parquet file has the required schema.

        Expected columns:
        - doc_id (or similar document identifier)
        - embedding (array/list of floats)
        - Optional: text, metadata fields

        Args:
            df: DataFrame to validate

        Returns:
            True if valid, False otherwise
        """
        # Check for required columns (flexible naming)
        id_cols = ['doc_id', 'document_id', 'id', 'atom_id', 'ATOM ID']
        embedding_cols = ['embedding', 'embeddings', 'vector']

        has_id = any(col in df.columns for col in id_cols)
        has_embedding = any(col in df.columns for col in embedding_cols)

        if not has_id:
            print(f"Error: No ID column found. Expected one of: {id_cols}")
            print(f"Found columns: {list(df.columns)}")
            return False

        if not has_embedding:
            print(f"Error: No embedding column found. Expected one of: {embedding_cols}")
            print(f"Found columns: {list(df.columns)}")
            return False

        return True

    def normalize_parquet_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize parquet data to standard schema.

        Args:
            df: Input DataFrame

        Returns:
            Normalized DataFrame with columns: doc_id, embedding, text
        """
        normalized = pd.DataFrame()

        # Find and rename ID column
        id_cols = ['doc_id', 'document_id', 'id', 'atom_id', 'ATOM ID']
        for col in id_cols:
            if col in df.columns:
                normalized['doc_id'] = df[col].astype(str)
                break

        # Find and rename embedding column
        embedding_cols = ['embedding', 'embeddings', 'vector']
        for col in embedding_cols:
            if col in df.columns:
                normalized['embedding'] = df[col]
                break

        # Find text column
        text_cols = ['text', 'distilled_text', 'content', 'body', 'BODY']
        for col in text_cols:
            if col in df.columns:
                normalized['text'] = df[col]
                break

        # If no text column, use empty string
        if 'text' not in normalized.columns:
            normalized['text'] = ''

        return normalized

    def process_parquet_file(self, s3_key: str) -> int:
        """
        Process a single parquet file: download, extract, and insert into pgvector.

        Args:
            s3_key: S3 object key

        Returns:
            Number of documents processed
        """
        filename = s3_key.split('/')[-1]

        print(f"\n{'='*80}")
        print(f"Processing: {s3_key}")
        print(f"{'='*80}")

        # Check if already processed (unless force_reprocess is True)
        if self._is_file_processed(filename):
            print(f"⊘ Skipping {filename} - already processed")
            print(f"  Use --force to reprocess this file")
            return 0

        # Download parquet file
        df = self.download_parquet_file(s3_key)

        # Validate schema
        if not self.validate_parquet_schema(df):
            print(f"Skipping {s3_key} due to invalid schema")
            return 0

        # Normalize data
        df = self.normalize_parquet_data(df)
        print(f"Normalized {len(df)} records")

        # Check for existing documents in the collection (skip if force_reprocess)
        existing_doc_ids = set()
        if not self.force_reprocess:
            existing_doc_ids = self.get_existing_doc_ids_in_collection()
            if existing_doc_ids:
                initial_count = len(df)
                df = df[~df['doc_id'].isin(existing_doc_ids)]
                skipped_count = initial_count - len(df)
                if skipped_count > 0:
                    print(f"⊘ Skipping {skipped_count} documents already in collection")
                if len(df) == 0:
                    print(f"All documents in {filename} already exist in collection, skipping file")
                    # Still mark as processed since all documents are accounted for
                    self._mark_file_processed(filename, 0)
                    return 0

        # Get document metadata
        doc_ids = df['doc_id'].unique().tolist()
        metadata_map = self.get_document_metadata(doc_ids)

        # Prepare documents for insertion
        documents_to_insert = []
        embeddings_to_insert = []
        metadatas_to_insert = []

        for idx, row in df.iterrows():
            doc_id = row['doc_id']
            embedding = row['embedding']
            text = row.get('text', '')

            # Get metadata from database
            doc_metadata = metadata_map.get(doc_id, {})

            # Skip if document not found in database
            if not doc_metadata:
                print(f"Warning: Document {doc_id} not found in database, skipping")
                continue

            # Convert embedding to numpy array if needed
            if isinstance(embedding, list):
                embedding = np.array(embedding, dtype=np.float32)
            elif isinstance(embedding, str):
                embedding = np.fromstring(embedding.strip('[]'), sep=',', dtype=np.float32)

            # Use distilled_text from database if available, otherwise use text from parquet
            document_text = doc_metadata.get('distilled_text') or text or doc_metadata.get('title', '')

            # Prepare metadata for LangChain
            metadata = {
                'doc_id': doc_id,
                'title': doc_metadata.get('title'),
                'date': doc_metadata.get('date'),
                'source_name': doc_metadata.get('source_name'),
                'event_name': doc_metadata.get('event_name'),
                'category': doc_metadata.get('category'),
                'subcategory': doc_metadata.get('subcategory'),
                'initiating_country': doc_metadata.get('initiating_country'),
                'recipient_country': doc_metadata.get('recipient_country'),
                'salience': doc_metadata.get('salience'),
                'salience_bool': doc_metadata.get('salience_bool'),
            }

            # Remove None values
            metadata = {k: v for k, v in metadata.items() if v is not None}

            documents_to_insert.append(document_text)
            embeddings_to_insert.append(embedding.tolist())
            metadatas_to_insert.append(metadata)

        print(f"Prepared {len(documents_to_insert)} documents for insertion")

        # Insert into pgvector
        if not self.dry_run and documents_to_insert:
            try:
                print(f"Inserting {len(documents_to_insert)} documents into {self.collection_name}...")
                self.vector_store.add_embeddings(
                    texts=documents_to_insert,
                    embeddings=embeddings_to_insert,
                    metadatas=metadatas_to_insert
                )
                print(f"✓ Successfully inserted {len(documents_to_insert)} documents")

                # Mark file as processed
                self._mark_file_processed(filename, len(documents_to_insert))

            except Exception as e:
                print(f"✗ Error inserting documents: {e}")
                raise
        elif self.dry_run:
            print(f"[DRY RUN] Would insert {len(documents_to_insert)} documents")
            print(f"[DRY RUN] Would mark {filename} as processed")

        return len(documents_to_insert)

    def process_all_files(self, specific_files: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Process all parquet files (or specific files).

        Args:
            specific_files: Optional list of specific filenames to process

        Returns:
            Summary statistics
        """
        start_time = datetime.now()

        # Get list of files to process
        if specific_files:
            files_to_process = []
            for filename in specific_files:
                s3_key = f"{self.s3_prefix}{filename}"
                files_to_process.append({'key': s3_key, 'filename': filename})
            print(f"Processing {len(specific_files)} specific files")
        else:
            all_files = self.list_parquet_files()
            files_to_process = all_files

        # Process each file
        total_processed = 0
        successful_files = 0
        failed_files = []

        for file_info in files_to_process:
            try:
                count = self.process_parquet_file(file_info['key'])
                total_processed += count
                successful_files += 1
            except Exception as e:
                print(f"Failed to process {file_info['filename']}: {e}")
                failed_files.append({'filename': file_info['filename'], 'error': str(e)})
                continue

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Print summary
        print(f"\n{'='*80}")
        print("MIGRATION SUMMARY")
        print(f"{'='*80}")
        print(f"Total files processed: {successful_files}/{len(files_to_process)}")
        print(f"Total documents inserted: {total_processed}")
        print(f"Failed files: {len(failed_files)}")
        print(f"Duration: {duration:.2f} seconds")

        if failed_files:
            print("\nFailed files:")
            for failed in failed_files:
                print(f"  - {failed['filename']}: {failed['error']}")

        return {
            'total_files': len(files_to_process),
            'successful_files': successful_files,
            'failed_files': len(failed_files),
            'total_documents': total_processed,
            'duration_seconds': duration,
            'failed_file_details': failed_files
        }


def view_tracker(collection_name: str, tracker_dir: str = './data/processed_embeddings'):
    """View processed files for a collection."""
    tracker_file = Path(tracker_dir) / f"{collection_name}_processed.json"

    if not tracker_file.exists():
        print(f"No tracker file found for collection '{collection_name}'")
        return

    with open(tracker_file, 'r') as f:
        data = json.load(f)

    files = data.get('files', [])
    print(f"\nProcessed Files for Collection: {collection_name}")
    print(f"Tracker File: {tracker_file}")
    print(f"Last Updated: {data.get('last_updated', 'Unknown')}")
    print(f"Total Files: {len(files)}\n")

    if files:
        print(f"{'Filename':<50} {'Processed At':<25} {'Doc Count':<10}")
        print("=" * 85)
        for file_entry in sorted(files, key=lambda x: x.get('processed_at', ''), reverse=True):
            filename = file_entry.get('filename', 'Unknown')
            processed_at = file_entry.get('processed_at', 'Unknown')
            doc_count = file_entry.get('document_count', 0)
            print(f"{filename:<50} {processed_at:<25} {doc_count:<10}")


def reset_tracker(collection_name: str, tracker_dir: str = './data/processed_embeddings', confirm: bool = False):
    """Reset processed files tracker for a collection."""
    tracker_file = Path(tracker_dir) / f"{collection_name}_processed.json"

    if not confirm:
        print("This will reset the tracker and allow all files to be reprocessed.")
        print("Use --confirm to proceed.")
        return

    if tracker_file.exists():
        tracker_file.unlink()
        print(f"✓ Deleted tracker file: {tracker_file}")
    else:
        print(f"No tracker file found for collection '{collection_name}'")


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description='Migrate embeddings from S3 parquet files to pgvector database',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Migrate command (default)
    migrate_parser = subparsers.add_parser('migrate', help='Migrate parquet files to pgvector')
    migrate_parser.add_argument(
        '--bucket',
        default='morris-sp-bucket',
        help='S3 bucket name (default: morris-sp-bucket)'
    )
    migrate_parser.add_argument(
        '--s3-prefix',
        default='embeddings/',
        help='S3 prefix/folder containing parquet files (default: embeddings/)'
    )
    migrate_parser.add_argument(
        '--collection',
        default='chunk_embeddings',
        choices=list(stores.keys()) + ['custom'],
        help='Target LangChain collection name'
    )
    migrate_parser.add_argument(
        '--files',
        nargs='+',
        help='Specific parquet files to process (optional)'
    )
    migrate_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run without inserting into database'
    )
    migrate_parser.add_argument(
        '--force',
        action='store_true',
        help='Reprocess files even if already processed'
    )
    migrate_parser.add_argument(
        '--tracker-dir',
        default='./data/processed_embeddings',
        help='Directory to store processed file tracker (default: ./data/processed_embeddings)'
    )
    migrate_parser.add_argument(
        '--api-url',
        default='http://host.docker.internal:5001',
        help='FastAPI URL for S3 operations (default: from env API_URL or http://localhost:8000)'
    )

    # View tracker command
    view_parser = subparsers.add_parser('view', help='View processed files tracker')
    view_parser.add_argument(
        'collection',
        help='Collection name to view'
    )
    view_parser.add_argument(
        '--tracker-dir',
        default='./data/processed_embeddings',
        help='Directory containing tracker files (default: ./data/processed_embeddings)'
    )

    # Reset tracker command
    reset_parser = subparsers.add_parser('reset', help='Reset processed files tracker')
    reset_parser.add_argument(
        'collection',
        help='Collection name to reset'
    )
    reset_parser.add_argument(
        '--tracker-dir',
        default='./data/processed_embeddings',
        help='Directory containing tracker files (default: ./data/processed_embeddings)'
    )
    reset_parser.add_argument(
        '--confirm',
        action='store_true',
        help='Confirm reset operation'
    )

    # If no command specified, default to migrate with old-style args
    if len(sys.argv) == 1 or (len(sys.argv) > 1 and not sys.argv[1] in ['migrate', 'view', 'reset']):
        # Old-style usage without subcommands - default to migrate
        parser.add_argument(
            '--bucket',
            default='morris-sp-bucket',
            help='S3 bucket name (default: morris-sp-bucket)'
        )
        parser.add_argument(
            '--s3-prefix',
            default='embeddings/',
            help='S3 prefix/folder containing parquet files (default: embeddings/)'
        )
        parser.add_argument(
            '--collection',
            default='chunk_embeddings',
            choices=list(stores.keys()) + ['custom'],
            help='Target LangChain collection name'
        )
        parser.add_argument(
            '--files',
            nargs='+',
            help='Specific parquet files to process (optional)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without inserting into database'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Reprocess files even if already processed'
        )
        parser.add_argument(
            '--tracker-dir',
            default='./data/processed_embeddings',
            help='Directory to store processed file tracker (default: ./data/processed_embeddings)'
        )
        parser.add_argument(
            '--api-url',
            default='http://host.docker.internal:5001',
            help='FastAPI URL for S3 operations (default: from env API_URL or http://localhost:8000)'
        )

        args = parser.parse_args()

        # Initialize migrator
        migrator = S3ToPgVectorMigrator(
            bucket_name=args.bucket,
            s3_prefix=args.s3_prefix,
            collection_name=args.collection,
            dry_run=args.dry_run,
            force_reprocess=args.force,
            tracker_dir=args.tracker_dir,
            api_url=getattr(args, 'api_url', None)
        )

        # Process files
        summary = migrator.process_all_files(specific_files=args.files)

        # Exit with appropriate code
        sys.exit(0 if summary['failed_files'] == 0 else 1)
    else:
        # New subcommand-based usage
        args = parser.parse_args()

        if args.command == 'view':
            view_tracker(args.collection, args.tracker_dir)
        elif args.command == 'reset':
            reset_tracker(args.collection, args.tracker_dir, args.confirm)
        elif args.command == 'migrate':
            # Initialize migrator
            migrator = S3ToPgVectorMigrator(
                bucket_name=args.bucket,
                s3_prefix=args.s3_prefix,
                collection_name=args.collection,
                dry_run=args.dry_run,
                force_reprocess=args.force,
                tracker_dir=args.tracker_dir,
                api_url=getattr(args, 'api_url', None)
            )

            # Process files
            summary = migrator.process_all_files(specific_files=args.files)

            # Exit with appropriate code
            sys.exit(0 if summary['failed_files'] == 0 else 1)
        else:
            parser.print_help()
            sys.exit(1)


if __name__ == '__main__':
    main()
