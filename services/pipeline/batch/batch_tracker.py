"""
Batch job tracker for database operations.

Provides a high-level interface for creating, updating, and querying
batch jobs in the database. Handles all batch_jobs table operations.
"""
import uuid
from datetime import datetime, date as DateType
from typing import Dict, Optional, List, Any
from sqlalchemy.orm import Session

from shared.models.models import BatchJob, BatchJobStatus
from shared.database.database import get_session


class BatchJobTracker:
    """
    High-level interface for batch job tracking operations.

    Handles all CRUD operations for BatchJob records and provides
    convenience methods for common batch processing workflows.
    """

    def __init__(self, session: Optional[Session] = None):
        """
        Initialize batch job tracker.

        Args:
            session: Optional database session. If not provided, will use get_session()
        """
        self.session = session
        self._owns_session = session is None

    def __enter__(self):
        """Context manager entry."""
        if self._owns_session:
            self.session = get_session().__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self._owns_session and self.session:
            self.session.__exit__(exc_type, exc_val, exc_tb)

    def create_batch_job(
        self,
        job_type: str,
        batch_size: int,
        initiating_country: Optional[str] = None,
        date_range_start: Optional[DateType] = None,
        date_range_end: Optional[DateType] = None,
        input_file_path: Optional[str] = None,
        estimated_cost: Optional[float] = None,
        created_by: Optional[str] = None
    ) -> BatchJob:
        """
        Create a new batch job record.

        Args:
            job_type: Job type ('cluster_deconflict', 'canonical_deconflict', etc.)
            batch_size: Number of requests in the batch
            initiating_country: Country filter (optional)
            date_range_start: Start date for processing (optional)
            date_range_end: End date for processing (optional)
            input_file_path: Path to input JSONL file (optional)
            estimated_cost: Estimated cost in USD (optional)
            created_by: Username or system that created the job (optional)

        Returns:
            BatchJob object
        """
        batch_job = BatchJob(
            job_type=job_type,
            batch_size=batch_size,
            initiating_country=initiating_country,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            input_file_path=input_file_path,
            estimated_cost=estimated_cost,
            created_by=created_by,
            status=BatchJobStatus.PREPARING.value
        )

        self.session.add(batch_job)
        self.session.commit()
        self.session.refresh(batch_job)

        return batch_job

    def get_batch_job(self, batch_job_id: uuid.UUID) -> Optional[BatchJob]:
        """
        Get batch job by ID.

        Args:
            batch_job_id: Batch job UUID

        Returns:
            BatchJob object or None if not found
        """
        return self.session.get(BatchJob, batch_job_id)

    def update_status(
        self,
        batch_job_id: uuid.UUID,
        status: BatchJobStatus,
        error_message: Optional[str] = None
    ) -> BatchJob:
        """
        Update batch job status.

        Args:
            batch_job_id: Batch job UUID
            status: New status
            error_message: Error message (optional, for failed jobs)

        Returns:
            Updated BatchJob object

        Raises:
            ValueError: If batch job not found
        """
        batch_job = self.get_batch_job(batch_job_id)
        if not batch_job:
            raise ValueError(f"Batch job not found: {batch_job_id}")

        batch_job.status = status.value if isinstance(status, BatchJobStatus) else status

        if error_message:
            batch_job.error_message = error_message

        # Set timestamps based on status
        if status == BatchJobStatus.SUBMITTED and not batch_job.submitted_at:
            batch_job.submitted_at = datetime.utcnow()
        elif status == BatchJobStatus.COMPLETED and not batch_job.completed_at:
            batch_job.completed_at = datetime.utcnow()
        elif status == BatchJobStatus.PROCESSING_RESULTS and not batch_job.processed_at:
            batch_job.processed_at = datetime.utcnow()

        self.session.commit()
        self.session.refresh(batch_job)

        return batch_job

    def update_openai_batch_id(
        self,
        batch_job_id: uuid.UUID,
        openai_batch_id: str,
        input_file_id: Optional[str] = None
    ) -> BatchJob:
        """
        Update batch job with OpenAI batch ID after submission.

        Args:
            batch_job_id: Batch job UUID
            openai_batch_id: OpenAI's batch ID
            input_file_id: OpenAI's file ID for input (optional)

        Returns:
            Updated BatchJob object
        """
        batch_job = self.get_batch_job(batch_job_id)
        if not batch_job:
            raise ValueError(f"Batch job not found: {batch_job_id}")

        batch_job.openai_batch_id = openai_batch_id
        if input_file_id:
            batch_job.input_file_id = input_file_id

        batch_job.status = BatchJobStatus.SUBMITTED.value
        batch_job.submitted_at = datetime.utcnow()

        self.session.commit()
        self.session.refresh(batch_job)

        return batch_job

    def update_progress(
        self,
        batch_job_id: uuid.UUID,
        requests_total: int,
        requests_completed: int,
        requests_failed: int
    ) -> BatchJob:
        """
        Update batch job progress metadata.

        Args:
            batch_job_id: Batch job UUID
            requests_total: Total requests in batch
            requests_completed: Requests completed
            requests_failed: Requests failed

        Returns:
            Updated BatchJob object
        """
        batch_job = self.get_batch_job(batch_job_id)
        if not batch_job:
            raise ValueError(f"Batch job not found: {batch_job_id}")

        batch_job.progress_metadata = {
            'requests_total': requests_total,
            'requests_completed': requests_completed,
            'requests_failed': requests_failed,
            'updated_at': datetime.utcnow().isoformat()
        }

        self.session.commit()
        self.session.refresh(batch_job)

        return batch_job

    def update_file_paths(
        self,
        batch_job_id: uuid.UUID,
        input_file_path: Optional[str] = None,
        output_file_path: Optional[str] = None,
        error_file_path: Optional[str] = None,
        input_file_id: Optional[str] = None,
        output_file_id: Optional[str] = None,
        error_file_id: Optional[str] = None
    ) -> BatchJob:
        """
        Update batch job file paths and IDs.

        Args:
            batch_job_id: Batch job UUID
            input_file_path: Local/S3 path to input file
            output_file_path: Local/S3 path to output file
            error_file_path: Local/S3 path to error file
            input_file_id: OpenAI file ID for input
            output_file_id: OpenAI file ID for output
            error_file_id: OpenAI file ID for errors

        Returns:
            Updated BatchJob object
        """
        batch_job = self.get_batch_job(batch_job_id)
        if not batch_job:
            raise ValueError(f"Batch job not found: {batch_job_id}")

        if input_file_path:
            batch_job.input_file_path = input_file_path
        if output_file_path:
            batch_job.output_file_path = output_file_path
        if error_file_path:
            batch_job.error_file_path = error_file_path
        if input_file_id:
            batch_job.input_file_id = input_file_id
        if output_file_id:
            batch_job.output_file_id = output_file_id
        if error_file_id:
            batch_job.error_file_id = error_file_id

        self.session.commit()
        self.session.refresh(batch_job)

        return batch_job

    def update_cost(
        self,
        batch_job_id: uuid.UUID,
        actual_cost: float
    ) -> BatchJob:
        """
        Update batch job actual cost after completion.

        Args:
            batch_job_id: Batch job UUID
            actual_cost: Actual cost in USD from OpenAI

        Returns:
            Updated BatchJob object
        """
        batch_job = self.get_batch_job(batch_job_id)
        if not batch_job:
            raise ValueError(f"Batch job not found: {batch_job_id}")

        batch_job.actual_cost = actual_cost

        self.session.commit()
        self.session.refresh(batch_job)

        return batch_job

    def increment_retry_count(self, batch_job_id: uuid.UUID) -> BatchJob:
        """
        Increment retry count for a batch job.

        Args:
            batch_job_id: Batch job UUID

        Returns:
            Updated BatchJob object
        """
        batch_job = self.get_batch_job(batch_job_id)
        if not batch_job:
            raise ValueError(f"Batch job not found: {batch_job_id}")

        batch_job.retry_count += 1

        self.session.commit()
        self.session.refresh(batch_job)

        return batch_job

    def list_batch_jobs(
        self,
        job_type: Optional[str] = None,
        status: Optional[BatchJobStatus] = None,
        initiating_country: Optional[str] = None,
        limit: int = 100
    ) -> List[BatchJob]:
        """
        List batch jobs with optional filters.

        Args:
            job_type: Filter by job type
            status: Filter by status
            initiating_country: Filter by country
            limit: Maximum number of results

        Returns:
            List of BatchJob objects
        """
        query = self.session.query(BatchJob)

        if job_type:
            query = query.filter(BatchJob.job_type == job_type)
        if status:
            query = query.filter(BatchJob.status == status)
        if initiating_country:
            query = query.filter(BatchJob.initiating_country == initiating_country)

        query = query.order_by(BatchJob.created_at.desc()).limit(limit)

        return query.all()

    def get_active_batch_jobs(self) -> List[BatchJob]:
        """
        Get all active batch jobs (submitted or in_progress).

        Returns:
            List of BatchJob objects
        """
        return self.session.query(BatchJob).filter(
            BatchJob.status.in_([BatchJobStatus.SUBMITTED, BatchJobStatus.IN_PROGRESS])
        ).order_by(BatchJob.submitted_at.desc()).all()

    def get_batch_jobs_by_openai_id(self, openai_batch_id: str) -> Optional[BatchJob]:
        """
        Get batch job by OpenAI batch ID.

        Args:
            openai_batch_id: OpenAI's batch ID

        Returns:
            BatchJob object or None if not found
        """
        return self.session.query(BatchJob).filter(
            BatchJob.openai_batch_id == openai_batch_id
        ).first()

    def get_batch_job_stats(
        self,
        job_type: Optional[str] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get statistics for batch jobs.

        Args:
            job_type: Filter by job type (optional)
            days: Number of days to look back

        Returns:
            Dictionary with statistics
        """
        from datetime import timedelta

        cutoff_date = datetime.utcnow() - timedelta(days=days)

        query = self.session.query(BatchJob).filter(
            BatchJob.created_at >= cutoff_date
        )

        if job_type:
            query = query.filter(BatchJob.job_type == job_type)

        batch_jobs = query.all()

        stats = {
            'total_jobs': len(batch_jobs),
            'by_status': {},
            'total_requests': 0,
            'total_estimated_cost': 0.0,
            'total_actual_cost': 0.0,
            'average_batch_size': 0
        }

        for batch_job in batch_jobs:
            # Count by status
            status_str = batch_job.status.value if isinstance(batch_job.status, BatchJobStatus) else batch_job.status
            stats['by_status'][status_str] = stats['by_status'].get(status_str, 0) + 1

            # Sum costs and requests
            stats['total_requests'] += batch_job.batch_size
            if batch_job.estimated_cost:
                stats['total_estimated_cost'] += float(batch_job.estimated_cost)
            if batch_job.actual_cost:
                stats['total_actual_cost'] += float(batch_job.actual_cost)

        if stats['total_jobs'] > 0:
            stats['average_batch_size'] = stats['total_requests'] // stats['total_jobs']

        return stats

    def delete_batch_job(self, batch_job_id: uuid.UUID) -> bool:
        """
        Delete a batch job record.

        Args:
            batch_job_id: Batch job UUID

        Returns:
            True if deleted, False if not found
        """
        batch_job = self.get_batch_job(batch_job_id)
        if not batch_job:
            return False

        self.session.delete(batch_job)
        self.session.commit()

        return True
