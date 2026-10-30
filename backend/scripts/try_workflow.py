"""
Walks the latest pending demo query through the staff workflow and prints
its timeline: In Progress -> Escalated (to the HOD) -> Resolved with a reply.
Run scripts.try_submit first to create a fresh query. This DOES save changes.

Run from the backend folder:
    .\\venv\\Scripts\\python.exe -m scripts.try_workflow
"""
from app.core.constants import Status
from app.database import SessionLocal
from app.models.models import Query, QueryStatusHistory, User
from app.services.query_service import change_status, escalate, send_reply

DEMO_STUDENT_EMAIL = "demo.student@example.com"


def main() -> None:
    with SessionLocal() as db:
        query = (
            db.query(Query)
            .join(User, Query.student_id == User.user_id)
            .filter(User.email == DEMO_STUDENT_EMAIL, Query.status == Status.PENDING)
            .order_by(Query.query_id.desc())
            .first()
        )
        if query is None or query.assignee is None:
            print("No pending demo query with an assignee. Run scripts.try_submit first.")
            return

        handler = query.assignee
        print(f"Query {query.reference_code} starts with {handler.email}")

        change_status(db, query, handler, Status.IN_PROGRESS, note="Checking the attendance register")
        db.commit()

        escalate(db, query, handler, "Attendance correction needs HOD approval")
        db.commit()
        supervisor = query.assignee
        print(f"Escalated to {supervisor.email}")

        send_reply(db, query, supervisor,
                   "Dear Demo Student,\n\nYour attendance has been verified and corrected.\n\n"
                   "Regards,\nComputer Science")
        db.commit()

        print(f"Final status: {query.status}\n\nTimeline:")
        history = (
            db.query(QueryStatusHistory)
            .filter(QueryStatusHistory.query_id == query.query_id)
            .order_by(QueryStatusHistory.history_id)
            .all()
        )
        for entry in history:
            who = db.get(User, entry.changed_by).name if entry.changed_by else "System"
            print(f"  {entry.old_status or '-':12} -> {entry.new_status:12} by {who:18} {entry.note or ''}")


if __name__ == "__main__":
    main()