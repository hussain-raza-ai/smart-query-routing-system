"""
Query endpoints (FR-02 to FR-09).

A thin HTTP layer: each endpoint checks who is calling, loads the query
through access control, calls the workflow in services/query_service.py,
commits once, and then hands any emails to n8n in the background.
"""
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi import Query as QueryParam
from sqlalchemy.orm import Session, joinedload

from app.core.constants import Channel, ReplyStatus, Role, Status
from app.core.rate_limit import rate_limit
from app.core.security import get_current_user, require_roles
from app.database import get_db
from app.models.models import Query, QueryStatusHistory, Reply, Route, User
from app.schemas.query_schemas import (
    ActionResult,
    EscalateRequest,
    FAQAnswer,
    FAQRequest,
    HistoryEntry,
    MoreInfoRequest,
    QueryDetail,
    QuerySubmitRequest,
    QuerySummary,
    ReassignRequest,
    ReplyRequest,
    SentReply,
    StatusChangeRequest,
)
from app.services.access_control import can_act, ensure_can_assign, get_query_for, visible_queries
from app.services.ai_service import answer_faq
from app.services.notification_service import send_email_event
from app.services.query_service import (
    EmailJob,
    add_student_information,
    change_status,
    escalate,
    reassign,
    send_reply,
    submit_query,
)

router = APIRouter(prefix="/queries", tags=["Queries"])
assistant_router = APIRouter(prefix="/assistant", tags=["AI Assistant"])

require_student = require_roles(Role.STUDENT)
require_staff = require_roles(*Role.STAFF)


# --- Helpers -----------------------------------------------------------------

def _commit_and_send(db: Session, background_tasks: BackgroundTasks, emails: list[EmailJob]) -> None:
    """Save the action, then queue its emails so they go out after the response is sent."""
    db.commit()
    for job in emails:
        background_tasks.add_task(send_email_event, job.event, job.data)


def _summary(query: Query, viewer: User) -> QuerySummary:
    is_student = viewer.role == Role.STUDENT
    return QuerySummary(
        query_id=query.query_id,
        reference_code=query.reference_code,
        category=query.category,
        intent=None if is_student else query.intent,
        status=query.status,
        channel=query.channel,
        query_text=query.query_text,
        department_name=query.department.name if query.department else None,
        course_code=query.course.code if query.course else None,
        student_name=query.student.name,
        assigned_to_name=None if is_student or query.assignee is None else query.assignee.name,
        created_at=query.created_at,
        updated_at=query.updated_at,
    )


def _changed_by_label(user_id: Optional[int], name: Optional[str], viewer: User) -> str:
    """Students see 'You' or 'University staff' instead of individual staff names."""
    if user_id is None:
        return "System"
    if viewer.role == Role.STUDENT:
        return "You" if user_id == viewer.user_id else "University staff"
    return name or "Unknown"


def _detail(db: Session, query: Query, viewer: User) -> QueryDetail:
    history_rows = (
        db.query(QueryStatusHistory, User.name)
        .outerjoin(User, QueryStatusHistory.changed_by == User.user_id)
        .filter(QueryStatusHistory.query_id == query.query_id)
        .order_by(QueryStatusHistory.history_id)
        .all()
    )
    reply_rows = (
        db.query(Reply, User.name)
        .join(User, Reply.responder_id == User.user_id)
        .filter(Reply.query_id == query.query_id, Reply.status == ReplyStatus.SENT)
        .order_by(Reply.sent_at)
        .all()
    )
    detail = QueryDetail(
        **_summary(query, viewer).model_dump(),
        history=[
            HistoryEntry(
                old_status=entry.old_status,
                new_status=entry.new_status,
                changed_by=_changed_by_label(entry.changed_by, name, viewer),
                note=entry.note,
                changed_at=entry.changed_at,
            )
            for entry, name in history_rows
        ],
        replies=[SentReply(text=reply.final_text, sent_by=name, sent_at=reply.sent_at)
                 for reply, name in reply_rows],
    )

    if viewer.role != Role.STUDENT:
        draft = (
            db.query(Reply)
            .filter(Reply.query_id == query.query_id, Reply.status == ReplyStatus.DRAFT)
            .order_by(Reply.reply_id.desc())
            .first()
        )
        ai_route = (  # the AI's own decision, ignoring later manual reassignments
            db.query(Route)
            .filter(Route.query_id == query.query_id, Route.ai_confidence.isnot(None))
            .order_by(Route.route_id.desc())
            .first()
        )
        detail.ai_draft = draft.ai_draft_text if draft else None
        detail.ai_confidence = float(ai_route.ai_confidence) if ai_route else None
        detail.routing_method = ai_route.method if ai_route else None
        detail.can_act = can_act(viewer, query)
    return detail


def _result(query: Query, message: str) -> ActionResult:
    return ActionResult(query_id=query.query_id, reference_code=query.reference_code,
                        status=query.status, message=message)


# --- Students ----------------------------------------------------------------

@router.post("", response_model=QuerySummary, status_code=201,
             dependencies=[Depends(rate_limit("query", max_calls=5, per_seconds=600))])
def submit(
    body: QuerySubmitRequest,
    background_tasks: BackgroundTasks,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """Submit a new query in plain language; the AI classifies and routes it."""
    query, emails = submit_query(db, student, body.query_text.strip(), Channel.WEB)
    _commit_and_send(db, background_tasks, emails)
    return _summary(query, student)


@router.post("/{query_id}/more-info", response_model=ActionResult)
def add_more_info(
    query_id: int,
    body: MoreInfoRequest,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """Answer a 'Needs More Info' request; the query returns to the staff queue."""
    query = get_query_for(db, student, query_id)
    add_student_information(db, query, student, body.text)
    db.commit()
    return _result(query, "Information added; the query is back with the staff")


# --- Everyone ----------------------------------------------------------------

@router.get("", response_model=list[QuerySummary])
def list_queries(
    status: Optional[str] = QueryParam(None, description="Only return queries with this status"),
    limit: int = QueryParam(50, ge=1, le=200),
    offset: int = QueryParam(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Queries the current user is allowed to see, most recently updated first."""
    rows = visible_queries(db, user).options(
        joinedload(Query.department),
        joinedload(Query.course),
        joinedload(Query.student),
        joinedload(Query.assignee),
    )
    if status:
        if status not in Status.ALL:
            raise HTTPException(status_code=400, detail=f"Unknown status '{status}'")
        rows = rows.filter(Query.status == status)
    rows = rows.order_by(Query.updated_at.desc()).offset(offset).limit(limit).all()
    return [_summary(query, user) for query in rows]


@router.get("/{query_id}", response_model=QueryDetail)
def get_query(query_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Full details of one query: timeline, replies and, for staff, the AI draft."""
    query = get_query_for(db, user, query_id)
    return _detail(db, query, user)


# --- Staff -------------------------------------------------------------------

@router.patch("/{query_id}/status", response_model=ActionResult)
def update_status(
    query_id: int,
    body: StatusChangeRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Set In Progress, Needs More Info (note required) or Resolved (note required)."""
    query = get_query_for(db, user, query_id, to_act=True)
    emails = change_status(db, query, user, body.status, body.note)
    _commit_and_send(db, background_tasks, emails)
    return _result(query, f"Status changed to {query.status}")


@router.post("/{query_id}/reply", response_model=ActionResult)
def reply(
    query_id: int,
    body: ReplyRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Send the reviewed reply to the student and resolve the query."""
    query = get_query_for(db, user, query_id, to_act=True)
    emails = send_reply(db, query, user, body.text)
    _commit_and_send(db, background_tasks, emails)
    return _result(query, "Reply sent and query resolved")


@router.post("/{query_id}/escalate", response_model=ActionResult)
def escalate_query(
    query_id: int,
    body: EscalateRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Pass the query up to the HOD (academic) or an Admin (service desks)."""
    query = get_query_for(db, user, query_id, to_act=True)
    emails = escalate(db, query, user, body.reason)
    _commit_and_send(db, background_tasks, emails)
    return _result(query, f"Escalated to {query.assignee.name}")


@router.post("/{query_id}/reassign", response_model=ActionResult)
def reassign_query(
    query_id: int,
    body: ReassignRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Hand the query to another staff member (Admins: anyone; others: own department)."""
    query = get_query_for(db, user, query_id, to_act=True)
    target = db.get(User, body.assignee_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    ensure_can_assign(user, target)
    emails = reassign(db, query, user, target, body.reason)
    _commit_and_send(db, background_tasks, emails)
    return _result(query, f"Reassigned to {target.name}")


@router.post("/{query_id}/take-ownership", response_model=ActionResult)
def take_ownership(
    query_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles(Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    """HOD or Admin takes the query over personally (SRS UC-06)."""
    query = get_query_for(db, user, query_id, to_act=True)
    emails = reassign(db, query, user, user)
    _commit_and_send(db, background_tasks, emails)
    return _result(query, "You now own this query")


# --- AI assistant ------------------------------------------------------------

@assistant_router.post("/ask", response_model=FAQAnswer,
                       dependencies=[Depends(rate_limit("assistant", max_calls=20, per_seconds=600))])
def ask_assistant(body: FAQRequest, student: User = Depends(require_student)):
    """Instant answers to common questions, before a formal query is submitted."""
    return FAQAnswer(answer=answer_faq(body.question))