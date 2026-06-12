"""Ingestion API (`/api/ingestion/*`).

Backs the Data Ingestion page: upload a results.json / atom.csv file, get a
dry-run validation report, start the load/flatten/embed pipeline as a
background task, poll progress, cancel, and download the error report.

All endpoints require analyst or admin role. Workers live in
services/pipeline/ingestion/ingestion_service.py and communicate through the
ingestion_jobs table.
"""
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from shared.database.database import get_session
from shared.models.models import IngestionJob, IngestionJobStatus
from services.pipeline.ingestion import ingestion_service

router = APIRouter()

ACTIVE_STATUSES = {
    IngestionJobStatus.VALIDATING.value,
    IngestionJobStatus.LOADING.value,
    IngestionJobStatus.EMBEDDING.value,
}

UPLOAD_CHUNK_BYTES = 1024 * 1024


def require_analyst_or_above(request: Request) -> dict:
    """Analyst/admin gate. Late import: server.main imports this module."""
    from server.main import get_current_user
    current_user = get_current_user(request)
    if current_user.get("role") not in ("admin", "analyst"):
        raise HTTPException(status_code=403, detail="Analyst access required")
    return current_user


class StartIngestionRequest(BaseModel):
    embed_now: bool = True
    reflatten_duplicates: bool = False
    doc_batch_size: int = 100
    embed_batch_size: int = 50


class JobListResponse(BaseModel):
    jobs: list
    total: int


def _get_job_or_404(session, job_id: str) -> IngestionJob:
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    job = session.get(IngestionJob, job_uuid)
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return job


@router.post("/api/ingestion/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: dict = Depends(require_analyst_or_above),
):
    """Stage an uploaded file, create a job, and kick off validation."""
    head = await file.read(4096)
    try:
        file_type = ingestion_service.detect_file_type(file.filename or "", head)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    job_id = uuid.uuid4()
    os.makedirs(ingestion_service.UPLOAD_DIR, exist_ok=True)
    safe_name = os.path.basename(file.filename or "upload")
    file_path = os.path.join(ingestion_service.UPLOAD_DIR, f"{job_id}_{safe_name}")

    size = 0
    try:
        with open(file_path, "wb") as out:
            out.write(head)
            size = len(head)
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > ingestion_service.MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {ingestion_service.MAX_UPLOAD_BYTES // (1024 * 1024)}MB upload limit",
                    )
                out.write(chunk)
    except HTTPException:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise

    with get_session() as session:
        job = IngestionJob(
            id=job_id,
            filename=safe_name,
            file_type=file_type,
            file_path=file_path,
            file_size_bytes=size,
            status=IngestionJobStatus.UPLOADED.value,
            created_by=current_user.get("username"),
        )
        session.add(job)
        session.commit()

    background_tasks.add_task(ingestion_service.run_validation, str(job_id))
    return {"job_id": str(job_id), "file_type": file_type, "size_bytes": size}


@router.get("/api/ingestion/jobs", response_model=JobListResponse)
def list_jobs(
    limit: int = 25,
    offset: int = 0,
    current_user: dict = Depends(require_analyst_or_above),
):
    with get_session() as session:
        query = session.query(IngestionJob).order_by(IngestionJob.created_at.desc())
        total = query.count()
        jobs = query.offset(offset).limit(min(limit, 100)).all()
        return {"jobs": [job.to_dict() for job in jobs], "total": total}


@router.get("/api/ingestion/jobs/{job_id}")
def get_job(job_id: str, current_user: dict = Depends(require_analyst_or_above)):
    with get_session() as session:
        job = _get_job_or_404(session, job_id)
        return job.to_dict()


@router.post("/api/ingestion/jobs/{job_id}/start")
def start_job(
    job_id: str,
    options: StartIngestionRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_analyst_or_above),
):
    with get_session() as session:
        job = _get_job_or_404(session, job_id)
        if job.status != IngestionJobStatus.READY.value:
            raise HTTPException(
                status_code=409,
                detail=f"Job is '{job.status}' — only validated jobs in 'ready' state can be started",
            )
        # Both file types are runnable (DSR JSON via the loader, atom CSV via
        # the salience+extraction pipeline); the validation report's
        # `runnable` flag is the single gate.
        if not (job.validation_report or {}).get("runnable", False):
            raise HTTPException(
                status_code=409,
                detail=(job.validation_report or {}).get("not_runnable_reason")
                or "Validation marked this file as not runnable",
            )
        if not os.path.exists(job.file_path):
            raise HTTPException(
                status_code=410,
                detail="Staged upload no longer exists on disk — upload the file again",
            )
        job.options = options.model_dump()
        job.cancel_requested = False
        job.status = IngestionJobStatus.LOADING.value
        session.commit()

    background_tasks.add_task(ingestion_service.run_ingestion, job_id)
    return {"job_id": job_id, "status": IngestionJobStatus.LOADING.value}


@router.post("/api/ingestion/jobs/{job_id}/cancel")
def cancel_job(job_id: str, current_user: dict = Depends(require_analyst_or_above)):
    with get_session() as session:
        job = _get_job_or_404(session, job_id)
        if job.status in ACTIVE_STATUSES:
            # Cooperative: the worker stops at its next batch boundary
            job.cancel_requested = True
        elif job.status in (IngestionJobStatus.UPLOADED.value, IngestionJobStatus.READY.value):
            job.status = IngestionJobStatus.CANCELLED.value
        else:
            raise HTTPException(status_code=409, detail=f"Job is already '{job.status}'")
        session.commit()
        return {"job_id": job_id, "status": job.status, "cancel_requested": job.cancel_requested}


@router.get("/api/ingestion/jobs/{job_id}/errors")
def download_errors(job_id: str, current_user: dict = Depends(require_analyst_or_above)):
    with get_session() as session:
        job = _get_job_or_404(session, job_id)
        csv_text = ingestion_service.error_log_csv(job)
        return Response(
            content=csv_text,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="ingestion_errors_{job_id}.csv"'
            },
        )
