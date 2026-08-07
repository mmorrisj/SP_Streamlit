"""Survey API (`/api/survey/*`).

Backs the in-app feedback survey page used during demos and evaluations.
Any authenticated user can submit a response; viewing collected responses
and aggregates requires analyst or admin role.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from shared.database.database import get_session
from shared.models.models import SurveyResponse

router = APIRouter()

# Free-text answers are truncated server-side so a pasted document can't bloat
# the table; well past what the UI's textareas encourage.
MAX_TEXT_ANSWER_CHARS = 4000


def _current_user(request: Request) -> dict:
    """Authenticated-user gate. Late import: server.main imports this module."""
    from server.main import get_current_user
    return get_current_user(request)


def _require_analyst_or_above(request: Request) -> dict:
    current_user = _current_user(request)
    if current_user.get("role") not in ("admin", "analyst"):
        raise HTTPException(status_code=403, detail="Analyst access required")
    return current_user


class SubmitSurveyRequest(BaseModel):
    overall_rating: Optional[int] = Field(default=None, ge=1, le=5)
    answers: Dict[str, Any] = Field(default_factory=dict)


def _sanitize_answers(answers: Dict[str, Any]) -> Dict[str, Any]:
    """Clamp free-text sizes and drop empty values; keep the payload shape flat."""
    cleaned: Dict[str, Any] = {}
    for key, value in answers.items():
        if isinstance(value, str):
            value = value.strip()[:MAX_TEXT_ANSWER_CHARS]
            if not value:
                continue
        elif isinstance(value, dict):
            value = {k: v for k, v in value.items() if v is not None}
            if not value:
                continue
        cleaned[str(key)[:100]] = value
    return cleaned


@router.post("/api/survey/responses")
def submit_survey_response(
    body: SubmitSurveyRequest,
    current_user: dict = Depends(_current_user),
):
    answers = _sanitize_answers(body.answers)
    if body.overall_rating is None and not answers:
        raise HTTPException(status_code=400, detail="Empty survey response")

    with get_session() as session:
        response = SurveyResponse(
            username=current_user.get("username"),
            display_name=current_user.get("display_name"),
            user_role=current_user.get("role"),
            overall_rating=body.overall_rating,
            answers=answers,
        )
        session.add(response)
        session.flush()
        return {"id": str(response.id), "status": "recorded"}


@router.get("/api/survey/responses")
def list_survey_responses(
    limit: int = 200,
    current_user: dict = Depends(_require_analyst_or_above),
):
    limit = max(1, min(limit, 1000))
    with get_session() as session:
        rows = (
            session.query(SurveyResponse)
            .order_by(SurveyResponse.created_at.desc())
            .limit(limit)
            .all()
        )
        responses = [r.to_dict() for r in rows]

    # Aggregates over the returned window: overall average plus per-question
    # averages for any numeric answers under the 'ratings' key.
    overall = [r["overall_rating"] for r in responses if r["overall_rating"] is not None]
    rating_sums: Dict[str, list] = {}
    would_use_counts: Dict[str, int] = {}
    for r in responses:
        answers = r.get("answers") or {}
        for key, value in (answers.get("ratings") or {}).items():
            if isinstance(value, (int, float)):
                rating_sums.setdefault(key, []).append(value)
        would_use = answers.get("would_use")
        if isinstance(would_use, str):
            would_use_counts[would_use] = would_use_counts.get(would_use, 0) + 1

    return {
        "responses": responses,
        "summary": {
            "count": len(responses),
            "avg_overall": round(sum(overall) / len(overall), 2) if overall else None,
            "rating_averages": {
                key: round(sum(vals) / len(vals), 2) for key, vals in sorted(rating_sums.items())
            },
            "would_use_counts": would_use_counts,
        },
    }
