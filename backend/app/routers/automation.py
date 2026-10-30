"""
Endpoints the n8n workflows call (FR-02 email channel, FR-07 SLA escalation,
and the daily summary for HODs from the project proposal).

    POST /automation/email-query              a student's email becomes a query
    POST /automation/sla-check                hourly: escalate queries waiting too long
    POST /automation/daily-summary            every morning: summary email to HODs and Admins
    POST /automation/sla-check/run-now        the SLA check, started by an Admin
    POST /automation/daily-summary/run-now    the daily summary, started by an Admin

The n8n endpoints are protected by the X-Service-Key header, which only n8n
knows (SDD 10.4). They never accept a user's login token.
"""
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.constants import PKT, Channel, Role, Status
from app.core.security import require_roles, require_service_key
from app.database import get_db
from app.models.models import Query, User
from app.services import analytics_service
from app.services.audit import record_action
from app.services.notification_service import EmailEvent, send_email_event
from app.services.query_service import add_student_information, run_sla_check, submit_query

router = APIRouter(prefix="/automation", tags=["Automation (n8n)"])
require_admin = require_roles(Role.ADMIN)

MIN_QUERY_CHARS = 10
MAX_QUERY_CHARS = 2000
_REFERENCE = re.compile(r"VU-\d{4}-[A-Z0-9]{6}")


class InboundEmail(BaseModel):
    from_email: EmailStr
    from_name: Optional[str] = Field(None, max_length=150)
    subject: Optional[str] = Field(None, max_length=500)
    body: Optional[str] = Field(None, max_length=100_000)


class EmailQueryResult(BaseModel):
    accepted: bool
    message: str
    reference_code: Optional[str] = None


class SlaCheckResult(BaseModel):
    escalated: int
    reference_codes: list[str]


class DailySummaryResult(BaseModel):
    recipients: int


# --- Email channel (FR-02) ---------------------------------------------------

def _clean_email_body(text: str) -> str:
    """Keep only what the student wrote: drop quoted earlier messages and the signature."""
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        if stripped == "--" or stripped.endswith("wrote:"):
            if not stripped.startswith("On ") and kept and kept[-1].startswith("On "):
                kept.pop()  # the "On ... wrote:" header was split over two lines
            break
        kept.append(stripped)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def _student_for(db: Session, email: str, name: Optional[str]) -> Optional[User]:
    """The sender's student account. University addresses are registered on first contact."""
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is None:
        if email.rsplit("@", 1)[-1] not in settings.ALLOWED_EMAIL_DOMAINS:
            return None
        user = User(name=(name or email.split("@")[0])[:100], email=email, role=Role.STUDENT)
        db.add(user)
        db.flush()
        record_action(db, "USER_REGISTERED", user_id=user.user_id, details="Registered from an email query")
    if not user.is_active or user.role != Role.STUDENT:
        return None
    return user


@router.post("/email-query", response_model=EmailQueryResult, dependencies=[Depends(require_service_key)])
def email_query(body: InboundEmail, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Turn a student's email into a query. A reply to a "more information
    needed" email adds the answer to that query instead. Emails that cannot
    be accepted return accepted=false, so n8n does not treat them as errors.
    """
    email = body.from_email.strip().lower()
    student = _student_for(db, email, body.from_name)
    if student is None:
        return EmailQueryResult(accepted=False, message=f"{email} is not a registered student")

    subject = (body.subject or "").strip()
    text = _clean_email_body(body.body or "")

    # A reply that quotes the reference of a query waiting for information answers that query.
    match = _REFERENCE.search(subject.upper())
    if match and text:
        query = (db.query(Query)
                   .filter(Query.reference_code == match.group(0), Query.student_id == student.user_id)
                   .first())
        if query is not None and query.status == Status.NEEDS_MORE_INFO:
            add_student_information(db, query, student, text[:MAX_QUERY_CHARS])
            db.commit()
            return EmailQueryResult(accepted=True, reference_code=query.reference_code,
                                    message="The information was added to the existing query")

    content = f"{subject}\n\n{text}".strip()
    if len(content) < MIN_QUERY_CHARS:
        return EmailQueryResult(accepted=False, message="The email is too short to be a query")

    query, emails = submit_query(db, student, content[:MAX_QUERY_CHARS], Channel.EMAIL)
    db.commit()
    for job in emails:
        background_tasks.add_task(send_email_event, job.event, job.data)
    return EmailQueryResult(accepted=True, reference_code=query.reference_code,
                            message="A new query was created")


# --- SLA escalation (FR-07) --------------------------------------------------

def _escalate_overdue(db: Session, background_tasks: BackgroundTasks) -> SlaCheckResult:
    escalated, emails = run_sla_check(db)
    references = [query.reference_code for query in escalated]
    db.commit()
    for job in emails:
        background_tasks.add_task(send_email_event, job.event, job.data)
    return SlaCheckResult(escalated=len(references), reference_codes=references)


@router.post("/sla-check", response_model=SlaCheckResult, dependencies=[Depends(require_service_key)])
def sla_check(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Called every hour by n8n: escalate queries left waiting longer than SLA_HOURS."""
    return _escalate_overdue(db, background_tasks)


@router.post("/sla-check/run-now", response_model=SlaCheckResult)
def sla_check_now(background_tasks: BackgroundTasks, admin: User = Depends(require_admin),
                  db: Session = Depends(get_db)):
    """The same check, started by an Admin (for example from the dashboard during a demo)."""
    record_action(db, "SLA_CHECK_RUN", user_id=admin.user_id)
    return _escalate_overdue(db, background_tasks)


# --- Daily summary (project proposal: HOD daily report) ----------------------

def _send_daily_summaries(db: Session, background_tasks: BackgroundTasks,
                          actor: Optional[User] = None) -> DailySummaryResult:
    """Email each active HOD their department's last 24 hours, and each Admin the whole university's."""
    people = (db.query(User).options(joinedload(User.department))
                .filter(User.role.in_((Role.HOD, Role.ADMIN)), User.is_active.is_(True))
                .all())
    today = datetime.now(PKT).strftime("%d %b %Y")

    sent = 0
    for person in people:
        if person.role == Role.HOD and person.department is None:
            continue  # an HOD without a department has nothing to summarise
        department = person.department if person.role == Role.HOD else None
        summary = analytics_service.daily_summary(db, department.department_id if department else None)
        background_tasks.add_task(send_email_event, EmailEvent.DAILY_SUMMARY, {
            **summary,
            "name": person.name,
            "email": person.email,
            "scope": department.name if department else "all departments",
            "date": today,
        })
        sent += 1

    record_action(db, "DAILY_SUMMARY_SENT", user_id=actor.user_id if actor else None,
                  details=f"Summary emailed to {sent} HOD/Admin account(s)")
    db.commit()
    return DailySummaryResult(recipients=sent)


@router.post("/daily-summary", response_model=DailySummaryResult, dependencies=[Depends(require_service_key)])
def daily_summary_job(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Called every morning by n8n."""
    return _send_daily_summaries(db, background_tasks)


@router.post("/daily-summary/run-now", response_model=DailySummaryResult)
def daily_summary_now(background_tasks: BackgroundTasks, admin: User = Depends(require_admin),
                      db: Session = Depends(get_db)):
    """The same summary, started by an Admin (useful in a demo)."""
    return _send_daily_summaries(db, background_tasks, actor=admin)