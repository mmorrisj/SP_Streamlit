"""
Alert notification dispatch.

Routes triggered alerts to configured channels (in-app, Slack, email).
All dispatchers are best-effort — failures are logged but never re-raised.
"""
import logging
import os
import smtplib
from email.mime.text import MIMEText
from typing import List

import httpx

from shared.models.alert_models import AlertHistory, AlertRule

logger = logging.getLogger(__name__)

# SMTP configuration from environment (optional)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_FROM = os.getenv("SMTP_FROM", "alerts@softpower.local")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

# Severity → Slack emoji mapping
_SEVERITY_EMOJI = {
    "info": ":information_source:",
    "warning": ":warning:",
    "critical": ":rotating_light:",
}

# Severity → Slack color mapping
_SEVERITY_COLOR = {
    "info": "#2563eb",
    "warning": "#d97706",
    "critical": "#dc2626",
}


def dispatch_alert(alert: AlertHistory, rule: AlertRule) -> List[str]:
    """
    Send alert to all configured channels. Returns list of channels
    that were successfully notified.
    """
    notified: List[str] = []
    channels = rule.channels or ["in_app"]
    config = rule.channel_config or {}

    for channel in channels:
        try:
            if channel == "in_app":
                # In-app alerts are persisted via AlertHistory — no extra work
                notified.append("in_app")

            elif channel == "slack":
                webhook_url = config.get("slack_webhook_url")
                if webhook_url:
                    send_slack_webhook(webhook_url, alert)
                    notified.append("slack")
                else:
                    logger.warning(
                        "Slack channel configured but no webhook URL for rule %s",
                        rule.id,
                    )

            elif channel == "email":
                email_to = config.get("email")
                if email_to:
                    send_email(email_to, alert)
                    notified.append("email")
                else:
                    logger.warning(
                        "Email channel configured but no address for rule %s",
                        rule.id,
                    )

        except Exception:
            logger.exception(
                "Failed to send %s notification for alert %s", channel, alert.id
            )

    return notified


def send_slack_webhook(webhook_url: str, alert: AlertHistory) -> None:
    """POST a formatted message to a Slack incoming webhook."""
    severity = alert.severity.value if hasattr(alert.severity, "value") else str(alert.severity)
    emoji = _SEVERITY_EMOJI.get(severity, ":bell:")
    color = _SEVERITY_COLOR.get(severity, "#6b7280")

    context = alert.context_data or {}
    context_lines = []
    if context.get("country"):
        context_lines.append(f"*Country:* {context['country']}")
    if context.get("z_score"):
        context_lines.append(f"*Z-score:* {context['z_score']}")
    if context.get("current_value"):
        context_lines.append(f"*Current:* {context['current_value']}")
    if context.get("baseline"):
        context_lines.append(f"*Baseline:* {context['baseline']}")

    payload = {
        "attachments": [
            {
                "color": color,
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"{emoji} *{alert.title}*\n{alert.message}",
                        },
                    },
                ],
            }
        ]
    }

    if context_lines:
        payload["attachments"][0]["blocks"].append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": " | ".join(context_lines),
                    }
                ],
            }
        )

    response = httpx.post(webhook_url, json=payload, timeout=10)
    response.raise_for_status()
    logger.info("Slack notification sent for alert %s", alert.id)


def send_email(to: str, alert: AlertHistory) -> None:
    """Send an alert notification via SMTP."""
    if not SMTP_HOST:
        logger.warning("SMTP_HOST not configured — skipping email notification")
        return

    severity = alert.severity.value if hasattr(alert.severity, "value") else str(alert.severity)

    subject = f"[{severity.upper()}] {alert.title}"
    body = f"{alert.message}\n\n"

    context = alert.context_data or {}
    if context:
        body += "Context:\n"
        for k, v in context.items():
            body += f"  {k}: {v}\n"

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        if SMTP_USER:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_FROM, [to], msg.as_string())

    logger.info("Email notification sent to %s for alert %s", to, alert.id)
