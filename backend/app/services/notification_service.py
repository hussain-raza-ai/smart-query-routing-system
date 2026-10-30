"""
Notifications (FR-08).

Two channels:
- Dashboard: a row in the notifications table, shown in the bell menu.
- Email: the backend writes every email (recipient, subject and text) and
  posts them to an n8n webhook, which delivers them through Gmail. Keeping
  the wording here means n8n needs one simple workflow for every kind of email.

Emails are sent after the database commit, as a background task, so a slow
or unavailable n8n never delays or breaks the user's request.
"""
import logging
import time
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import NotificationChannel, NotificationKind
from app.models.models import Notification

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 10
RETRY_DELAYS_SECONDS = (2, 5, 15)  # pauses between attempts while n8n is unreachable
SIGNATURE = "Regards,\nVU Smart Query System"
# Demo accounts use this reserved domain; mail sent there can never arrive.
UNDELIVERABLE_DOMAINS = ("@example.com",)


class EmailEvent:
    """The moments that send an email."""

    QUERY_RECEIVED = "query_submitted"
    REPLY_SENT = "reply_sent"
    QUERY_ESCALATED = "query_escalated"
    MORE_INFO_NEEDED = "more_info_needed"
    INSTRUCTOR_ON_LEAVE = "instructor_on_leave"
    ANNOUNCEMENT = "announcement"
    DAILY_SUMMARY = "daily_summary"


def notify(
    db: Session,
    user_id: int,
    message: str,
    *,
    query_id: Optional[int] = None,
    title: Optional[str] = None,
    kind: str = NotificationKind.UPDATE,
) -> None:
    """Add a dashboard notification. It is saved with the caller's commit."""
    db.add(Notification(
        user_id=user_id,
        query_id=query_id,
        kind=kind,
        channel=NotificationChannel.DASHBOARD,
        title=title,
        message=message,
    ))


# --- Email wording -----------------------------------------------------------

def _email(to: str, subject: str, text: str, signed: bool = True) -> dict:
    body = text.strip() + (f"\n\n{SIGNATURE}" if signed else "")
    return {"to": (to or "").strip(), "subject": subject, "text": body}


def _query_received(d: dict) -> list[dict]:
    emails = [_email(
        d["student_email"],
        f"Query received: {d['reference_code']}",
        f"Dear {d['student_name']},\n\n"
        f"Your query has been received and sent to the {d['department']}.\n"
        f"Reference: {d['reference_code']}\n\n"
        "You can follow its progress on your dashboard. Please quote the reference in any follow-up.",
    )]
    if d.get("assignee_email"):
        emails.append(_email(
            d["assignee_email"],
            f"New {d['category']} query: {d['reference_code']}",
            f"Dear {d['assignee_name']},\n\n"
            f"A new {d['category']} query from {d['student_name']} has been assigned to you.\n\n"
            f"{d['query_text']}\n\n"
            "An AI-drafted reply is ready for your review on the dashboard.",
        ))
    return emails


def _reply_sent(d: dict) -> list[dict]:
    # The staff member's reply already has its own greeting and sign-off.
    return [_email(
        d["student_email"],
        f"Reply to your query {d['reference_code']}",
        f"{d['reply_text']}\n\n---\nReference {d['reference_code']}, resolved by {d['resolved_by']}.",
        signed=False,
    )]


def _query_escalated(d: dict) -> list[dict]:
    return [_email(
        d["supervisor_email"],
        f"Escalated query: {d['reference_code']} ({d['category']})",
        f"Dear {d['supervisor_name']},\n\n"
        f"Query {d['reference_code']} has been escalated to you by {d['escalated_by']}.\n\n"
        f"Reason: {d['reason']}\n\n"
        "Please review it on your dashboard.",
    )]


def _more_info_needed(d: dict) -> list[dict]:
    return [_email(
        d["student_email"],
        f"More information needed: {d['reference_code']}",
        f"Dear {d['student_name']},\n\n"
        f"{d['requested_by']} needs a little more information to resolve your query:\n\n"
        f"{d['message']}\n\n"
        "You can add it from your dashboard, or simply reply to this email without changing the subject.",
    )]


def _instructor_on_leave(d: dict) -> list[dict]:
    return [_email(
        d["student_email"],
        f"Auto-reply from {d['instructor_name']} ({d['reference_code']})",
        f"Dear {d['student_name']},\n\n"
        f"{d['auto_reply_message']}\n\n"
        f"Your query {d['reference_code']} is being handled by the department in the meantime.",
    )]


def _announcement(d: dict) -> list[dict]:
    return [_email(address, f"Announcement: {d['title']}", d["message"]) for address in d["recipients"]]


def _daily_summary(d: dict) -> list[dict]:
    waiting = "\n".join(
        f"  - {q['reference_code']} ({q['category']}, {q['status']}): waiting {q['waiting_hours']} h"
        for q in d["oldest"]
    ) or "  Nothing is waiting."
    return [_email(
        d["email"],
        f"Daily summary for {d['scope']}: {d['date']}",
        f"Dear {d['name']},\n\n"
        f"Here is the last 24 hours for {d['scope']}.\n\n"
        f"New queries:  {d['received']}\n"
        f"Resolved:     {d['resolved']}\n"
        f"Still open:   {d['open']} (escalated: {d['escalated']})\n\n"
        f"Waiting the longest:\n{waiting}\n\n"
        "Open the dashboard for the details.",
    )]


_TEMPLATES = {
    EmailEvent.QUERY_RECEIVED: _query_received,
    EmailEvent.REPLY_SENT: _reply_sent,
    EmailEvent.QUERY_ESCALATED: _query_escalated,
    EmailEvent.MORE_INFO_NEEDED: _more_info_needed,
    EmailEvent.INSTRUCTOR_ON_LEAVE: _instructor_on_leave,
    EmailEvent.ANNOUNCEMENT: _announcement,
    EmailEvent.DAILY_SUMMARY: _daily_summary,
}


def _deliverable(address: str) -> bool:
    address = address.lower()
    return "@" in address and not address.endswith(UNDELIVERABLE_DOMAINS)


def compose_emails(event: str, data: dict) -> list[dict]:
    """The emails for one event, leaving out addresses that cannot receive mail."""
    template = _TEMPLATES.get(event)
    if template is None:
        logger.warning("No email template for event '%s'", event)
        return []
    return [email for email in template(data) if _deliverable(email["to"])]


# --- Delivery through n8n ----------------------------------------------------

def send_email_event(event: str, data: dict) -> bool:
    """
    Hand the emails for `event` to n8n. Returns True once n8n has accepted them.

    Runs as a background task after the response has been sent. Network
    problems are retried a few times; failures are logged, never raised,
    because the change itself is already saved and visible on the dashboard.
    """
    emails = compose_emails(event, data)
    if not emails:
        return True  # nothing deliverable, e.g. only demo accounts were involved
    if not settings.N8N_WEBHOOK_URL:
        logger.info("N8N_WEBHOOK_URL is not set; skipping %d '%s' email(s)", len(emails), event)
        return False

    payload = {"event": event, "emails": emails}
    headers = {"X-Webhook-Secret": settings.N8N_WEBHOOK_SECRET}
    attempts = (0, *RETRY_DELAYS_SECONDS)
    for number, delay in enumerate(attempts, start=1):
        time.sleep(delay)
        try:
            response = httpx.post(settings.N8N_WEBHOOK_URL, json=payload, headers=headers,
                                  timeout=WEBHOOK_TIMEOUT_SECONDS)
            response.raise_for_status()
            return True
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:  # wrong secret or inactive workflow; retrying will not help
                logger.error("n8n rejected the '%s' emails: HTTP %s", event, exc.response.status_code)
                return False
            logger.warning("n8n error for '%s' (attempt %d): %s", event, number, exc)
        except httpx.HTTPError as exc:
            logger.warning("Could not reach n8n for '%s' (attempt %d): %s", event, number, exc)

    logger.error("Gave up on %d '%s' email(s) after %d attempts", len(emails), event, len(attempts))
    return False