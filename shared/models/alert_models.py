"""
Alert system models for configurable notifications.

Provides AlertRule (user-defined alert conditions) and AlertHistory
(triggered alert records) for materiality spikes, volume surges,
new entity appearances, and new event detection.
"""
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Any
from enum import Enum as PyEnum

from sqlalchemy import (
    Integer, String, Text, DateTime, Boolean, ForeignKey,
    UniqueConstraint, Index, Enum
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column

from shared.database.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AlertConditionType(PyEnum):
    """Types of conditions that can trigger an alert."""
    MATERIALITY_SPIKE = "materiality_spike"
    VOLUME_SURGE = "volume_surge"
    NEW_ENTITY = "new_entity"
    NEW_EVENT = "new_event"


class AlertChannel(PyEnum):
    """Notification delivery channels."""
    EMAIL = "email"
    SLACK = "slack"
    IN_APP = "in_app"


class AlertSeverity(PyEnum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AlertRule(Base):
    """
    User-defined alert rule with condition parameters and notification config.

    Each rule specifies:
    - What to watch (condition_type + condition_params)
    - How to notify (channels + channel_config)
    - How often (cooldown_minutes)
    """
    __tablename__ = "alert_rules"

    # Primary key
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Owner
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Rule definition
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    condition_type: Mapped[AlertConditionType] = mapped_column(
        Enum(AlertConditionType), nullable=False
    )
    condition_params: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    # Example condition_params by type:
    #   materiality_spike: {"threshold_z": 2.0, "window_days": 7, "country": "China", "category": "Military"}
    #   volume_surge:      {"threshold_z": 2.0, "window_days": 7, "country": "China"}
    #   new_entity:        {"country": "China", "entity_type": "person"}
    #   new_event:         {"country": "China", "min_materiality": 3.0}

    # Notification config
    channels: Mapped[List[str]] = mapped_column(
        ARRAY(Text), default=list
    )
    channel_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB, default=dict
    )
    # Example: {"slack_webhook_url": "https://hooks.slack.com/...", "email": "analyst@org.gov"}

    severity: Mapped[AlertSeverity] = mapped_column(
        Enum(AlertSeverity), default=AlertSeverity.INFO
    )

    # Scheduling
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=60)
    last_evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Audit
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=datetime.utcnow
    )

    # Soft delete
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationships
    user = relationship("User")
    history = relationship(
        "AlertHistory", back_populates="alert_rule", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_alert_rule_user", "user_id"),
        Index("ix_alert_rule_condition", "condition_type"),
        Index("ix_alert_rule_enabled", "is_enabled", "is_deleted"),
    )

    def __repr__(self) -> str:
        return (
            f"<AlertRule(id='{self.id}', name='{self.name}', "
            f"type='{self.condition_type.value}')>"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "name": self.name,
            "description": self.description,
            "condition_type": self.condition_type.value,
            "condition_params": self.condition_params,
            "channels": self.channels or [],
            "channel_config": self.channel_config or {},
            "severity": self.severity.value,
            "is_enabled": self.is_enabled,
            "cooldown_minutes": self.cooldown_minutes,
            "last_evaluated_at": (
                self.last_evaluated_at.isoformat() if self.last_evaluated_at else None
            ),
            "last_triggered_at": (
                self.last_triggered_at.isoformat() if self.last_triggered_at else None
            ),
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat() if self.updated_at else None
            ),
        }


class AlertHistory(Base):
    """
    Record of a triggered alert with context data and acknowledgment tracking.
    """
    __tablename__ = "alert_history"

    # Primary key
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Parent rule
    alert_rule_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("alert_rules.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Alert content
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        Enum(AlertSeverity), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Contextual data for the trigger
    context_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Example: {"country": "China", "current_value": 45, "baseline": 12, "z_score": 3.2,
    #           "category": "Military", "window_days": 7}

    # Delivery tracking
    channels_notified: Mapped[List[str]] = mapped_column(ARRAY(Text), default=list)

    # Acknowledgment
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=True))
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationship
    alert_rule = relationship("AlertRule", back_populates="history")

    __table_args__ = (
        Index("ix_alert_history_rule", "alert_rule_id"),
        Index("ix_alert_history_triggered", "triggered_at"),
        Index("ix_alert_history_unacked", "acknowledged", "triggered_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AlertHistory(id='{self.id}', title='{self.title[:50]}', "
            f"severity='{self.severity.value}')>"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "alert_rule_id": str(self.alert_rule_id),
            "triggered_at": (
                self.triggered_at.isoformat() if self.triggered_at else None
            ),
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "context_data": self.context_data or {},
            "channels_notified": self.channels_notified or [],
            "acknowledged": self.acknowledged,
            "acknowledged_by": (
                str(self.acknowledged_by) if self.acknowledged_by else None
            ),
            "acknowledged_at": (
                self.acknowledged_at.isoformat() if self.acknowledged_at else None
            ),
        }
