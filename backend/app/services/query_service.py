"""
Query workflow — the heart of the system.

Every change to a query goes through this module so the same rules always
apply: the status history is recorded, the audit log is written, dashboard
notifications are created and the right emails are queued.

Functions here never commit. The caller (a router) commits once at the end
of the request, so every action is all-or-nothing; only after that commit
are the queued emails handed to n8n in the background.
"""
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import PKT, ReplyStatus, Role, RouteMethod, Status
from app.models.models import Escalation, Query, QueryStatusHistory, Reply, Route, User
from app.services import ai_service
from app.services.audit import record_action
from app.services.notification_service import EmailEvent, notify
from app.services.routing_service import find_supervisor, route_query

FALLBACK_DEPARTMENT_NAME = "University Support Desk"
_REFERENCE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I/L look-alikes

# Statuses staff may set directly. Escalation and replying have their own
# functions because they involve more than a status change.
MANUAL_STATUSES = (Status.IN_PROGRESS, Status.NEEDS_MORE_INFO, Status.RESOLVED)


class WorkflowError(Exception):
    """An action that is not allowed in the query's current state. The message is shown to the user."""


@dataclass
class EmailJob:
    """An email to send through n8n once the database changes are committed."""

    event: str
    data: dict = field(default_factory=dict)


# --- Building blocks ---------------------------------------------------------

def _new_reference_code(db: Session) -> str:
    """A short, readable ticket code such as VU-2026-K7QM3T."""
    year = datetime.now(timezone.utc).year
    while True:
        code = f"VU-{year}-" + "".join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(6))
        if not db.query(Query.query_id).filter(Query.reference_code == code).first():
            return code


def _ensure_open(query: Query) -> None:
    if query.status == Status.RESOLVED:
        raise WorkflowError(f"Query {query.reference_code} is already resolved.")


def set_status(
    db: Session,
    query: Query,
    new_status: str,
    *,
    changed_by: Optional[User],
    note: Optional[str] = None,
) -> None:
    """Change a query's status and record the change in its history (FR-06)."""
    if query.status == new_status:
        return
    db.add(QueryStatusHistory(
        query_id=query.query_id,
        old_status=query.status,
        new_status=new_status,
        changed_by=changed_by.user_id if changed_by else None,  # None = system
        note=note[:255] if note else None,
    ))
    query.status = new_status


# --- Submitting a query (SDD sequence 7.1) -----------------------------------

def submit_query(db: Session, student: User, text: str, channel: str) -> tuple[Query, list[EmailJob]]:
    """
    Create a query from a student's message: classify it, route it, prepare an
    AI draft for the assignee and notify everyone involved.
    """
    classification = ai_service.classify_query(text)
    decision = route_query(db, classification)
    department_name = decision.department.name if decision.department else FALLBACK_DEPARTMENT_NAME

    query = Query(
        reference_code=_new_reference_code(db),
        student_id=student.user_id,
        department_id=decision.department.department_id if decision.department else None,
        course_id=decision.course.course_id if decision.course else None,
        assigned_to=decision.assignee.user_id if decision.assignee else None,
        category=classification.category,
        intent=classification.intent[:100],
        channel=channel,
        query_text=text,
        status=Status.PENDING,
    )
    db.add(query)
    db.flush()  # assigns query_id for the related records below

    db.add(QueryStatusHistory(
        query_id=query.query_id,
        new_status=Status.PENDING,
        changed_by=student.user_id,
        note=f"Submitted via {channel}",
    ))
    db.add(Route(
        query_id=query.query_id,
        routed_to_role=decision.routed_to_role,
        department_id=query.department_id,
        assigned_to=query.assigned_to,
        ai_confidence=classification.confidence,
        method=classification.method,
    ))
    # Prepared now so staff see a ready draft the moment they open the query.
    db.add(Reply(
        query_id=query.query_id,
        ai_draft_text=ai_service.draft_reply(text, classification.category, student.name, department_name),
        status=ReplyStatus.DRAFT,
    ))

    record_action(db, "QUERY_SUBMITTED", user_id=student.user_id, query_id=query.query_id,
                  details=f"Channel: {channel}")
    record_action(db, "QUERY_ROUTED", query_id=query.query_id,
                  details=(f"{classification.category} via {classification.method} "
                           f"({classification.confidence:.0%}) -> {department_name}; {decision.reason}"))

    notify(db, student.user_id,
           f"Your query {query.reference_code} was received and sent to the {department_name}.",
           query_id=query.query_id, title="Query received")
    if decision.assignee:
        notify(db, decision.assignee.user_id,
               f"New {classification.category} query {query.reference_code} has been assigned to you.",
               query_id=query.query_id, title="New query")

    emails = [EmailJob(EmailEvent.QUERY_RECEIVED, {
        "reference_code": query.reference_code,
        "category": classification.category,
        "department": department_name,
        "student_name": student.name,
        "student_email": student.email,
        "assignee_name": decision.assignee.name if decision.assignee else "",
        "assignee_email": decision.assignee.email if decision.assignee else "",
        "query_text": text[:300],
    })]

    # FR-13: the course instructor is on leave, so pass their auto-reply on to the student.
    away = decision.instructor_on_leave
    if away and away.auto_reply_message:
        notify(db, student.user_id, away.auto_reply_message, query_id=query.query_id,
               title=f"Auto-reply from {away.name}")
        emails.append(EmailJob(EmailEvent.INSTRUCTOR_ON_LEAVE, {
            "reference_code": query.reference_code,
            "student_name": student.name,
            "student_email": student.email,
            "instructor_name": away.name,
            "auto_reply_message": away.auto_reply_message,
        }))

    return query, emails


# --- Status changes ----------------------------------------------------------

def change_status(
    db: Session,
    query: Query,
    actor: User,
    new_status: str,
    note: Optional[str] = None,
) -> list[EmailJob]:
    """Set In Progress, Needs More Info or Resolved. The last two require a note."""
    _ensure_open(query)
    if new_status not in MANUAL_STATUSES:
        raise WorkflowError(f"Status '{new_status}' cannot be set directly.")
    note = (note or "").strip() or None
    if new_status in (Status.NEEDS_MORE_INFO, Status.RESOLVED) and not note:
        raise WorkflowError(f"Please add a note explaining why the query is '{new_status}'.")

    set_status(db, query, new_status, changed_by=actor, note=note)
    record_action(db, "STATUS_CHANGED", user_id=actor.user_id, query_id=query.query_id,
                  details=f"Now {new_status}" + (f": {note}" if note else ""))

    message = f"Your query {query.reference_code} is now '{new_status}'."
    if note:
        message += f" Note from {actor.name}: {note}"
    notify(db, query.student_id, message, query_id=query.query_id, title="Query update")

    if new_status == Status.NEEDS_MORE_INFO:
        student = query.student
        return [EmailJob(EmailEvent.MORE_INFO_NEEDED, {
            "reference_code": query.reference_code,
            "student_name": student.name,
            "student_email": student.email,
            "message": note,
            "requested_by": actor.name,
        })]
    return []


def add_student_information(db: Session, query: Query, student: User, text: str) -> list[EmailJob]:
    """The student answers a 'Needs More Info' request; the query goes back to the staff queue."""
    if query.status != Status.NEEDS_MORE_INFO:
        raise WorkflowError("This query is not waiting for more information.")
    text = (text or "").strip()
    if not text:
        raise WorkflowError("Please write the information you want to add.")

    stamp = datetime.now(PKT).strftime("%d %b %Y %H:%M PKT")
    query.query_text += f"\n\n--- Additional information from the student ({stamp}) ---\n{text}"
    set_status(db, query, Status.PENDING, changed_by=student, note="Student added more information")
    record_action(db, "STUDENT_ADDED_INFO", user_id=student.user_id, query_id=query.query_id)

    if query.assigned_to:
        notify(db, query.assigned_to, f"The student added more information to {query.reference_code}.",
               query_id=query.query_id, title="Student replied")
    return []


# --- Replying (SDD sequence 7.2) ---------------------------------------------

def send_reply(db: Session, query: Query, actor: User, text: str) -> list[EmailJob]:
    """
    Send the staff member's reply and resolve the query.
    The text always comes from a person: an AI draft is never sent on its own.
    """
    _ensure_open(query)
    text = (text or "").strip()
    if not text:
        raise WorkflowError("The reply cannot be empty. Review the AI draft and write the final text.")

    reply = (
        db.query(Reply)
        .filter(Reply.query_id == query.query_id, Reply.status == ReplyStatus.DRAFT)
        .order_by(Reply.reply_id.desc())
        .first()
    )
    if reply is None:
        reply = Reply(query_id=query.query_id)
        db.add(reply)

    edited = reply.ai_draft_text is None or reply.ai_draft_text.strip() != text
    reply.final_text = text
    reply.responder_id = actor.user_id
    reply.status = ReplyStatus.SENT
    reply.sent_at = datetime.now(timezone.utc)

    set_status(db, query, Status.RESOLVED, changed_by=actor, note="Reply sent")
    record_action(db, "REPLY_SENT", user_id=actor.user_id, query_id=query.query_id,
                  details="Reply written or edited by staff" if edited else "AI draft approved without changes")
    notify(db, query.student_id, f"You have received a reply to {query.reference_code}.",
           query_id=query.query_id, title="Reply received")

    student = query.student
    return [EmailJob(EmailEvent.REPLY_SENT, {
        "reference_code": query.reference_code,
        "student_name": student.name,
        "student_email": student.email,
        "reply_text": text,
        "resolved_by": actor.name,
    })]


# --- Escalation and reassignment ---------------------------------------------

def escalate(db: Session, query: Query, actor: Optional[User], reason: str) -> list[EmailJob]:
    """
    Hand the query to the next level: the HOD for academic queries, an Admin
    otherwise. `actor=None` means the automatic SLA check did it.
    """
    _ensure_open(query)
    if query.status == Status.ESCALATED:
        raise WorkflowError(f"Query {query.reference_code} is already escalated.")

    supervisor = find_supervisor(db, query.department)
    if supervisor and supervisor.user_id == query.assigned_to:
        supervisor = find_supervisor(db, None)  # already with the HOD, so go up to an Admin
    if supervisor is None or supervisor.user_id == query.assigned_to:
        raise WorkflowError("There is nobody above the current handler to escalate to.")

    previous_assignee_id = query.assigned_to
    db.add(Escalation(
        query_id=query.query_id,
        escalated_by=actor.user_id if actor else None,
        escalated_to=supervisor.user_id,
        reason=reason[:255],
    ))
    query.assigned_to = supervisor.user_id
    set_status(db, query, Status.ESCALATED, changed_by=actor, note=reason)

    escalated_by = actor.name if actor else f"System ({settings.SLA_HOURS}-hour SLA)"
    record_action(db, "QUERY_ESCALATED", user_id=actor.user_id if actor else None, query_id=query.query_id,
                  details=f"To {supervisor.email} by {escalated_by}: {reason}")

    notify(db, supervisor.user_id, f"Query {query.reference_code} was escalated to you. Reason: {reason}",
           query_id=query.query_id, title="Escalated query")
    if previous_assignee_id and previous_assignee_id != supervisor.user_id:
        notify(db, previous_assignee_id, f"Query {query.reference_code} was escalated to {supervisor.name}.",
               query_id=query.query_id, title="Query escalated")
    notify(db, query.student_id,
           f"Your query {query.reference_code} has been passed to senior staff for faster attention.",
           query_id=query.query_id, title="Query escalated")

    return [EmailJob(EmailEvent.QUERY_ESCALATED, {
        "reference_code": query.reference_code,
        "category": query.category,
        "reason": reason,
        "supervisor_name": supervisor.name,
        "supervisor_email": supervisor.email,
        "escalated_by": escalated_by,
    })]


def reassign(
    db: Session,
    query: Query,
    actor: User,
    new_assignee: User,
    reason: Optional[str] = None,
) -> list[EmailJob]:
    """
    Move a query to another staff member (SRS UC-06, UC-07). Assigning it to
    yourself is "taking ownership" and starts work on it straight away.
    """
    _ensure_open(query)
    if new_assignee.role not in Role.STAFF or not new_assignee.is_active:
        raise WorkflowError("Queries can only be assigned to active staff members.")
    if new_assignee.user_id == query.assigned_to:
        raise WorkflowError(f"{new_assignee.name} is already handling this query.")

    previous_assignee_id = query.assigned_to
    taking_ownership = new_assignee.user_id == actor.user_id
    query.assigned_to = new_assignee.user_id
    if new_assignee.department_id is not None:
        query.department_id = new_assignee.department_id

    db.add(Route(
        query_id=query.query_id,
        routed_to_role=new_assignee.role,
        department_id=query.department_id,
        assigned_to=new_assignee.user_id,
        method=RouteMethod.MANUAL,
    ))
    note = f"Taken over by {actor.name}" if taking_ownership else f"Reassigned to {new_assignee.name}"
    if reason:
        note += f": {reason}"
    set_status(db, query, Status.IN_PROGRESS if taking_ownership else Status.PENDING,
               changed_by=actor, note=note)
    record_action(db, "QUERY_REASSIGNED", user_id=actor.user_id, query_id=query.query_id, details=note)

    if not taking_ownership:
        notify(db, new_assignee.user_id,
               f"Query {query.reference_code} has been assigned to you by {actor.name}.",
               query_id=query.query_id, title="Query assigned")
    if previous_assignee_id and previous_assignee_id not in (new_assignee.user_id, actor.user_id):
        notify(db, previous_assignee_id, f"Query {query.reference_code} was moved to {new_assignee.name}.",
               query_id=query.query_id, title="Query reassigned")
    notify(db, query.student_id,
           f"Your query {query.reference_code} is now being handled by another member of staff.",
           query_id=query.query_id, title="Query update")
    return []


# --- Automatic SLA escalation (FR-07) ----------------------------------------

def run_sla_check(db: Session) -> tuple[list[Query], list[EmailJob]]:
    """
    Escalate every query that has waited on staff for longer than SLA_HOURS.
    Called hourly by n8n. A query that cannot be escalated right now (for
    example, nobody is available) is skipped and retried on the next run.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.SLA_HOURS)
    overdue = (
        db.query(Query)
        .filter(Query.status.in_(Status.AWAITING_STAFF), Query.updated_at < cutoff)
        .order_by(Query.updated_at)
        .all()
    )
    reason = f"No response within {settings.SLA_HOURS} hours (automatic SLA escalation)"

    escalated, emails = [], []
    for query in overdue:
        try:
            emails += escalate(db, query, actor=None, reason=reason)
            escalated.append(query)
        except WorkflowError:
            continue
    return escalated, emails