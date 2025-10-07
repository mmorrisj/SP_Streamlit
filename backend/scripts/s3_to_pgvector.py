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

import boto3
from botocore.exceptions import ClientError
import pyarrow.parquet as pq

# Database imports
from sqlalchemy import text
from backend.database import get_session, get_engine
from backend.models import Document

# LangChain imports
from langchain_community.vectorstores.pgvector import PGVector
from langchain_huggingface import HuggingFaceEmbeddings
from backend.scripts.embedding_vectorstore import (
    build_connection_string,
    chunk_store,
    summary_store,
    daily_store,
    weekly_store,
    monthly_store,
    yearly_store,
    stores
)


class S3ToPgVectorMigrator:
    """Handles migration of embeddings from S3 parquet files to pgvector database."""

    def __init__(
        self,
        bucket_name: str = 'morris-sp-bucket',
        s3_prefix: str = 'embeddings/',
        collection_name: str = 'chunk_embeddings',
        dry_run: bool = False
    ):
        """
        Initialize the migrator.

        Args:
            bucket_name: S3 bucket name
            s3_prefix: S3 prefix/folder containing parquet files
            collection_name: Target LangChain collection name
            dry_run: If True, don't write to database
        """
        self.bucket_name = bucket_name
        self.s3_prefix = s3_prefix.rstrip('/') + '/'
        self.collection_name = collection_name
        self.dry_run = dry_run

        # Initialize S3 client
        self.s3_client = boto3.client('s3')

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
        print(f"  Dry Run: {dry_run}")

    def list_parquet_files(self) -> List[Dict[str, Any]]:
        """
        List all parquet files in the S3 prefix.

        Returns:
            List of file metadata dictionaries
        """
        parquet_files = []

        try:
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix=self.s3_prefix)

            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        key = obj['Key']
                        if key.endswith('.parquet'):
                            parquet_files.append({
                                'key': key,
                                'filename': key.split('/')[-1],
                                'size': obj['Size'],
                                'last_modified': obj['LastModified']
                            })

            print(f"Found {len(parquet_files)} parquet files in s3://{self.bucket_name}/{self.s3_prefix}")
            return parquet_files

        except Exception as e:
            print(f"Error listing S3 files: {e}")
            raise

    def download_parquet_file(self, s3_key: str, local_path: Optional[str] = None) -> pd.DataFrame:
        """
        Download and read a parquet file from S3.

        Args:
            s3_key: S3 object key
            local_path: Optional local path to save file

        Returns:
            DataFrame containing parquet data
        """
        try:
            if local_path is None:
                local_path = f"/tmp/{s3_key.split('/')[-1]}"

            # Download file
            print(f"Downloading {s3_key}...")
            self.s3_client.download_file(self.bucket_name, s3_key, local_path)

            # Read parquet file
            df = pd.read_parquet(local_path)
            print(f"  Loaded {len(df)} rows from {s3_key}")

            # Clean up local file
            if os.path.exists(local_path):
                os.remove(local_path)

            return df

        except Exception as e:
            print(f"Error downloading {s3_key}: {e}")
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
        print(f"\n{'='*80}")
        print(f"Processing: {s3_key}")
        print(f"{'='*80}")

        # Download parquet file
        df = self.download_parquet_file(s3_key)

        # Validate schema
        if not self.validate_parquet_schema(df):
            print(f"Skipping {s3_key} due to invalid schema")
            return 0

        # Normalize data
        df = self.normalize_parquet_data(df)
        print(f"Normalized {len(df)} records")

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
                self.vector_store.add_texts(
                    texts=documents_to_insert,
                    metadatas=metadatas_to_insert,
                    embeddings=embeddings_to_insert
                )
                print(f"✓ Successfully inserted {len(documents_to_insert)} documents")
            except Exception as e:
                print(f"✗ Error inserting documents: {e}")
                raise
        elif self.dry_run:
            print(f"[DRY RUN] Would insert {len(documents_to_insert)} documents")

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


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description='Migrate embeddings from S3 parquet files to pgvector database'
    )
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

    args = parser.parse_args()

    # Initialize migrator
    migrator = S3ToPgVectorMigrator(
        bucket_name=args.bucket,
        s3_prefix=args.s3_prefix,
        collection_name=args.collection,
        dry_run=args.dry_run
    )

    # Process files
    summary = migrator.process_all_files(specific_files=args.files)

    # Exit with appropriate code
    sys.exit(0 if summary['failed_files'] == 0 else 1)


if __name__ == '__main__':
    main()
