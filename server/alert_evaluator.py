"""
Alert evaluation engine.

Periodically evaluates all enabled AlertRules and creates AlertHistory
records when conditions are met. Runs on APScheduler inside FastAPI.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from shared.database.database import get_session
from shared.models.alert_models import (
    AlertRule, AlertHistory, AlertConditionType, AlertSeverity,
)
from shared.models.models import Document, EventSummary, PeriodType

logger = logging.getLogger(__name__)

# APScheduler instance (initialized in start_alert_scheduler)
_scheduler = None


# ---------------------------------------------------------------------------
# Condition evaluators
# ---------------------------------------------------------------------------

def evaluate_materiality_spike(
    rule: AlertRule, session: Session
) -> Optional[AlertHistory]:
    """
    Detect when average daily materiality score for a country exceeds
    a z-score threshold over a rolling window.
    """
    params = rule.condition_params or {}
    threshold_z = params.get("threshold_z", 2.0)
    window_days = params.get("window_days", 30)
    country = params.get("country")
    category = params.get("category")

    # Build query for daily average materiality scores over the window
    cutoff = datetime.utcnow().date() - timedelta(days=window_days)

    query = (
        session.query(
            EventSummary.period_start,
            func.avg(EventSummary.material_score).label("avg_score"),
        )
        .filter(
            EventSummary.period_type == PeriodType.DAILY,
            EventSummary.is_deleted == False,
            EventSummary.material_score.isnot(None),
            EventSummary.period_start >= cutoff,
        )
    )
    if country:
        query = query.filter(EventSummary.initiating_country == country)
    # Category filtering via JSONB count_by_category
    if category:
        query = query.filter(
            EventSummary.count_by_category.has_key(category)  # noqa: W601
        )

    query = query.group_by(EventSummary.period_start).order_by(
        EventSummary.period_start
    )
    rows = query.all()

    if len(rows) < 5:
        return None  # Not enough data

    scores = [float(r.avg_score) for r in rows]
    mean = np.mean(scores[:-1])  # baseline = all but latest
    std = np.std(scores[:-1])
    if std == 0:
        return None

    latest = scores[-1]
    z = (latest - mean) / std

    if z < threshold_z:
        return None

    return AlertHistory(
        alert_rule_id=rule.id,
        severity=rule.severity,
        title=f"Materiality spike detected{' for ' + country if country else ''}",
        message=(
            f"Average materiality score of {latest:.2f} on {rows[-1].period_start} "
            f"is {z:.1f} standard deviations above the {window_days}-day baseline "
            f"of {mean:.2f}."
        ),
        context_data={
            "country": country,
            "category": category,
            "current_value": round(latest, 2),
            "baseline": round(mean, 2),
            "std_dev": round(std, 2),
            "z_score": round(z, 2),
            "window_days": window_days,
            "date": str(rows[-1].period_start),
        },
    )


def evaluate_volume_surge(
    rule: AlertRule, session: Session
) -> Optional[AlertHistory]:
    """
    Detect when daily document count exceeds a z-score threshold
    over a rolling window.
    """
    params = rule.condition_params or {}
    threshold_z = params.get("threshold_z", 2.0)
    window_days = params.get("window_days", 30)
    country = params.get("country")

    cutoff = datetime.utcnow().date() - timedelta(days=window_days)

    query = (
        session.query(
            Document.date,
            func.count(Document.doc_id).label("doc_count"),
        )
        .filter(
            Document.date >= cutoff,
            Document.date.isnot(None),
        )
    )
    if country:
        query = query.filter(Document.initiating_country == country)

    query = query.group_by(Document.date).order_by(Document.date)
    rows = query.all()

    if len(rows) < 5:
        return None

    counts = [int(r.doc_count) for r in rows]
    mean = np.mean(counts[:-1])
    std = np.std(counts[:-1])
    if std == 0:
        return None

    latest = counts[-1]
    z = (latest - mean) / std

    if z < threshold_z:
        return None

    return AlertHistory(
        alert_rule_id=rule.id,
        severity=rule.severity,
        title=f"Document volume surge{' for ' + country if country else ''}",
        message=(
            f"{latest} documents on {rows[-1].date} — "
            f"{z:.1f} standard deviations above the {window_days}-day average "
            f"of {mean:.0f}."
        ),
        context_data={
            "country": country,
            "current_value": latest,
            "baseline": round(mean, 1),
            "std_dev": round(std, 1),
            "z_score": round(z, 2),
            "window_days": window_days,
            "date": str(rows[-1].date),
        },
    )


def evaluate_new_entity(
    rule: AlertRule, session: Session
) -> Optional[AlertHistory]:
    """
    Detect new CanonicalEntity records created since the rule was last evaluated.
    """
    from shared.models.models import CanonicalEntity

    params = rule.condition_params or {}
    country = params.get("country")
    entity_type = params.get("entity_type")

    since = rule.last_evaluated_at or (datetime.utcnow() - timedelta(hours=1))

    query = session.query(CanonicalEntity).filter(
        CanonicalEntity.created_at >= since,
        CanonicalEntity.master_entity_id.is_(None),  # Only master entities
    )
    if country:
        query = query.filter(CanonicalEntity.initiating_country == country)
    if entity_type:
        query = query.filter(
            CanonicalEntity.entity_type == entity_type.upper()
        )

    new_entities = query.all()
    if not new_entities:
        return None

    names = [e.canonical_name for e in new_entities[:10]]
    more = len(new_entities) - len(names)

    return AlertHistory(
        alert_rule_id=rule.id,
        severity=rule.severity,
        title=f"{len(new_entities)} new entit{'y' if len(new_entities) == 1 else 'ies'} detected{' for ' + country if country else ''}",
        message=(
            f"New entities: {', '.join(names)}"
            + (f" (+{more} more)" if more > 0 else "")
        ),
        context_data={
            "country": country,
            "entity_type": entity_type,
            "count": len(new_entities),
            "entity_names": names,
            "since": since.isoformat(),
        },
    )


def evaluate_new_event(
    rule: AlertRule, session: Session
) -> Optional[AlertHistory]:
    """
    Detect new EventSummary records created since the rule was last evaluated,
    optionally filtered by minimum materiality score.
    """
    params = rule.condition_params or {}
    country = params.get("country")
    min_materiality = params.get("min_materiality")

    since = rule.last_evaluated_at or (datetime.utcnow() - timedelta(hours=1))

    query = session.query(EventSummary).filter(
        EventSummary.created_at >= since,
        EventSummary.period_type == PeriodType.DAILY,
        EventSummary.is_deleted == False,
    )
    if country:
        query = query.filter(EventSummary.initiating_country == country)
    if min_materiality is not None:
        query = query.filter(EventSummary.material_score >= min_materiality)

    new_events = query.all()
    if not new_events:
        return None

    names = [e.event_name for e in new_events[:10]]
    more = len(new_events) - len(names)

    return AlertHistory(
        alert_rule_id=rule.id,
        severity=rule.severity,
        title=f"{len(new_events)} new event{'s' if len(new_events) != 1 else ''} detected{' for ' + country if country else ''}",
        message=(
            f"New events: {', '.join(names)}"
            + (f" (+{more} more)" if more > 0 else "")
        ),
        context_data={
            "country": country,
            "min_materiality": min_materiality,
            "count": len(new_events),
            "event_names": names,
            "since": since.isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_EVALUATORS = {
    AlertConditionType.MATERIALITY_SPIKE: evaluate_materiality_spike,
    AlertConditionType.VOLUME_SURGE: evaluate_volume_surge,
    AlertConditionType.NEW_ENTITY: evaluate_new_entity,
    AlertConditionType.NEW_EVENT: evaluate_new_event,
}


def evaluate_rule(rule: AlertRule, session: Session) -> Optional[AlertHistory]:
    """Evaluate a single rule and return AlertHistory if triggered."""
    evaluator = _EVALUATORS.get(rule.condition_type)
    if not evaluator:
        logger.warning("No evaluator for condition type: %s", rule.condition_type)
        return None
    return evaluator(rule, session)


def run_evaluation_cycle():
    """
    Main evaluation loop — called by APScheduler every 5 minutes.
    Evaluates all enabled, non-deleted rules that are past their cooldown.
    """
    from server.alert_notifier import dispatch_alert

    logger.info("Starting alert evaluation cycle")
    now = datetime.utcnow()
    triggered_count = 0

    try:
        with get_session() as session:
            rules = (
                session.query(AlertRule)
                .filter(
                    AlertRule.is_enabled == True,
                    AlertRule.is_deleted == False,
                )
                .all()
            )

            for rule in rules:
                # Check cooldown
                if rule.last_triggered_at:
                    cooldown_end = rule.last_triggered_at + timedelta(
                        minutes=rule.cooldown_minutes or 60
                    )
                    if now < cooldown_end:
                        continue

                try:
                    alert = evaluate_rule(rule, session)
                    rule.last_evaluated_at = now

                    if alert:
                        session.add(alert)
                        rule.last_triggered_at = now
                        session.flush()  # Get alert.id for notification

                        # Dispatch notifications (best-effort)
                        try:
                            notified = dispatch_alert(alert, rule)
                            alert.channels_notified = notified
                        except Exception:
                            logger.exception(
                                "Failed to dispatch alert %s", alert.id
                            )

                        triggered_count += 1

                except Exception:
                    logger.exception(
                        "Error evaluating rule %s (%s)", rule.id, rule.name
                    )

            session.commit()

    except Exception:
        logger.exception("Alert evaluation cycle failed")

    logger.info(
        "Alert evaluation cycle complete: %d rules evaluated, %d triggered",
        len(rules) if 'rules' in locals() else 0,
        triggered_count,
    )


# ---------------------------------------------------------------------------
# Scheduler management
# ---------------------------------------------------------------------------

def start_alert_scheduler():
    """Start APScheduler background thread for alert evaluation."""
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        _scheduler = BackgroundScheduler()
        _scheduler.add_job(
            run_evaluation_cycle,
            "interval",
            minutes=5,
            id="alert_evaluation",
            replace_existing=True,
        )
        _scheduler.start()
        logger.info("Alert scheduler started (5-minute interval)")
    except ImportError:
        logger.warning(
            "APScheduler not installed — alert evaluation disabled. "
            "Install with: pip install apscheduler>=3.10.4"
        )
    except Exception:
        logger.exception("Failed to start alert scheduler")


def stop_alert_scheduler():
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("Alert scheduler stopped")
        _scheduler = None
