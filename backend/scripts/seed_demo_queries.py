"""
Adds two weeks of realistic sample queries for the demo.

They cover every department, both channels and every outcome (resolved, in
progress, waiting for the student, escalated, new), each with a status
timeline, routing record, reply and audit entries dated to match. The
analytics dashboard and the reports then have real shape.

Categories are fixed here instead of asking the AI, so the script is quick and
repeatable, and it spends none of the daily AI quota; live queries show the real AI drafts.
Sample students use @example.com addresses, so nobody receives an email.

Run scripts.reset_demo_data first for a clean start, then from the backend folder:
    .\\venv\\Scripts\\python.exe -m scripts.seed_demo_queries
"""
from datetime import datetime, timedelta, timezone

from app.core.constants import ReplyStatus, Role, RouteMethod, Status
from app.database import SessionLocal
from app.models.models import AuditLog, Escalation, Query, QueryStatusHistory, Reply, Route, User
from app.services.ai_service import ClassificationResult
from app.services.query_service import FALLBACK_DEPARTMENT_NAME, _new_reference_code
from app.services.routing_service import find_supervisor, route_query

SAMPLE_STUDENTS = [
    ("Ayesha Siddiqui", "ayesha.siddiqui@example.com"),
    ("Hamza Iqbal", "hamza.iqbal@example.com"),
    ("Fatima Noor", "fatima.noor@example.com"),
    ("Bilal Hussain", "bilal.hussain@example.com"),
    ("Zainab Akhtar", "zainab.akhtar@example.com"),
]

# (hours ago, student, category, course code, channel, outcome, text)
# Open queries are kept under 24 hours old so the SLA check does not escalate them at once.
SAMPLES = [
    (312, 0, "Fee", None, "web", "resolved",
     "My fee challan for Fall 2026 is not showing on the student portal. I need it before the due date."),
    (300, 1, "Result", None, "email", "resolved",
     "My CS201 final result shows 38 marks but I expected much more. I would like to apply for rechecking."),
    (287, 2, "IT", None, "web", "resolved",
     "I cannot log in to the LMS. It says my password is incorrect even after I reset it."),
    (270, 3, "Degree", None, "email", "resolved",
     "I need an official transcript for a job application. How long does it take?"),
    (255, 4, "Attendance", "CS101", "web", "resolved",
     "My CS101 attendance for week 6 shows absent although I attended the session."),
    (232, 0, "Course", "CS619", "web", "resolved",
     "Can the CS619 prototype be submitted two days late because of a medical emergency?"),
    (220, 1, "Fee", None, "web", "escalated",
     "I want to pay my semester fee in two instalments because of a family emergency. Is that possible?"),
    (196, 2, "Result", None, "web", "resolved",
     "My DMC has my name spelled wrong. Please correct it before I apply for my degree."),
    (170, 3, "IT", None, "email", "resolved",
     "My university email account is locked and I am not receiving any emails."),
    (146, 4, "General", None, "web", "resolved",
     "What are the regional campus office timings during the winter break?"),
    (120, 0, "Degree", None, "web", "needs_info",
     "I want to freeze my semester for Spring 2027. What is the procedure?"),
    (98, 1, "Course", "CS201", "email", "resolved",
     "The handout links for CS201 lectures 20 to 25 are broken on the LMS."),
    (75, 2, "Fee", None, "web", "resolved",
     "I paid the late fee fine twice by mistake. Please refund one of the payments."),
    (50, 3, "Result", None, "web", "resolved",
     "My midterm marks for CS101 are not uploaded while other students can see theirs."),
    (16, 4, "Attendance", "CS619", "web", "in_progress",
     "I was marked absent in the CS619 viva session although I joined it on time."),
    (9, 0, "IT", None, "email", "pending",
     "The computers in Lab 2 of the Lahore campus are not starting since this morning."),
    (5, 1, "Fee", None, "web", "pending",
     "I want to apply for the need-based scholarship. Which documents are required?"),
    (2, 2, "Degree", None, "web", "pending",
     "I need my degree verification letter for HEC attestation. How do I apply?"),
]

REPLY_MIDDLE = {
    "Fee": "We have checked your fee record and corrected it. The updated status is now visible on the student portal.",
    "Result": "We have reviewed your result record and made the correction. The updated record is now on the student portal.",
    "Course": "Your instructor has reviewed your request and the updated information is now available on the LMS.",
    "Attendance": "Your attendance has been checked against the session log and corrected.",
    "Degree": "Your request has been processed and the document will be ready within five working days.",
    "IT": "Your account has been reset and the problem is fixed. Please try again and tell us if it happens again.",
    "General": "The regional campus offices stay open from 9 am to 3 pm on working days during the winter break.",
}
MORE_INFO_NOTE = "Please share your student ID and any document that supports your request."
SLA_REASON = "No response within 24 hours (automatic SLA escalation)"
CONFIDENCE = 0.92


def _student(db, name: str, email: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(name=name, email=email, role=Role.STUDENT)
        db.add(user)
        db.flush()
    return user


def _history(db, query, when, old, new, by=None, note=None) -> None:
    db.add(QueryStatusHistory(query_id=query.query_id, old_status=old, new_status=new,
                              changed_by=by.user_id if by else None, note=note, changed_at=when))


def _log(db, query, when, action, by=None, details=None) -> None:
    db.add(AuditLog(user_id=by.user_id if by else None, query_id=query.query_id,
                    action=action, details=details, timestamp=when))


def _add_query(db, submitted, student, category, course_code, channel, outcome, text) -> Query:
    decision = route_query(db, ClassificationResult(category, f"{category} request", CONFIDENCE,
                                                    RouteMethod.GEMINI, course_code))
    department_name = decision.department.name if decision.department else FALLBACK_DEPARTMENT_NAME
    handler = decision.assignee

    query = Query(
        reference_code=_new_reference_code(db),
        student_id=student.user_id,
        department_id=decision.department.department_id if decision.department else None,
        course_id=decision.course.course_id if decision.course else None,
        assigned_to=handler.user_id if handler else None,
        category=category, channel=channel, query_text=text,
        status=Status.PENDING, created_at=submitted, updated_at=submitted,
    )
    db.add(query)
    db.flush()

    _history(db, query, submitted, None, Status.PENDING, student, f"Submitted via {channel}")
    db.add(Route(query_id=query.query_id, routed_to_role=decision.routed_to_role,
                 department_id=query.department_id, assigned_to=query.assigned_to,
                 ai_confidence=CONFIDENCE, method=RouteMethod.GEMINI, routed_at=submitted))
    _log(db, query, submitted, "QUERY_SUBMITTED", student, f"Channel: {channel}")
    _log(db, query, submitted, "QUERY_ROUTED",
         details=f"{category} via gemini ({CONFIDENCE:.0%}) -> {department_name}; {decision.reason}")

    answer = f"Dear {student.name},\n\n{REPLY_MIDDLE[category]}\n\nRegards,\n{department_name}"
    draft = answer if outcome == "resolved" else (
        f"Dear {student.name},\n\nThank you for contacting us. Your request has been received and the "
        f"{department_name} will review it and get back to you shortly.\n\nRegards,\n{department_name}"
    )
    reply = Reply(query_id=query.query_id, ai_draft_text=draft, status=ReplyStatus.DRAFT, created_at=submitted)
    db.add(reply)

    last = submitted
    if outcome in ("resolved", "in_progress") and handler:
        last = submitted + timedelta(hours=2)
        _history(db, query, last, Status.PENDING, Status.IN_PROGRESS, handler, "Looking into it")
        _log(db, query, last, "STATUS_CHANGED", handler, "Now In Progress: Looking into it")
        query.status = Status.IN_PROGRESS

    if outcome == "resolved" and handler:
        last = submitted + timedelta(hours=6)
        reply.final_text, reply.responder_id = answer, handler.user_id
        reply.status, reply.sent_at = ReplyStatus.SENT, last
        _history(db, query, last, Status.IN_PROGRESS, Status.RESOLVED, handler, "Reply sent")
        _log(db, query, last, "REPLY_SENT", handler, "AI draft approved without changes")
        query.status = Status.RESOLVED

    elif outcome == "needs_info" and handler:
        last = submitted + timedelta(hours=3)
        _history(db, query, last, Status.PENDING, Status.NEEDS_MORE_INFO, handler, MORE_INFO_NOTE)
        _log(db, query, last, "STATUS_CHANGED", handler, f"Now Needs More Info: {MORE_INFO_NOTE}")
        query.status = Status.NEEDS_MORE_INFO

    elif outcome == "escalated":
        supervisor = find_supervisor(db, decision.department)
        if supervisor:
            last = submitted + timedelta(hours=25)
            db.add(Escalation(query_id=query.query_id, escalated_to=supervisor.user_id,
                              reason=SLA_REASON, escalated_at=last))
            _history(db, query, last, Status.PENDING, Status.ESCALATED, None, SLA_REASON)
            _log(db, query, last, "QUERY_ESCALATED",
                 details=f"To {supervisor.email} by System (24-hour SLA): {SLA_REASON}")
            query.assigned_to = supervisor.user_id
            query.status = Status.ESCALATED

    query.updated_at = last
    return query


def main() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        students = [_student(db, name, email) for name, email in SAMPLE_STUDENTS]
        for hours_ago, who, category, course_code, channel, outcome, text in SAMPLES:
            query = _add_query(db, now - timedelta(hours=hours_ago), students[who],
                               category, course_code, channel, outcome, text)
            print(f"{query.reference_code}  {category:10} {outcome:12} {hours_ago:>4} h ago")
        db.commit()
    print(f"\nAdded {len(SAMPLES)} sample queries from {len(SAMPLE_STUDENTS)} sample students.")


if __name__ == "__main__":
    main()