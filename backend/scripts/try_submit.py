"""
Submits one sample query through the real workflow (AI, routing, draft)
on behalf of a demo student and prints what happened. This DOES save to
the database, exactly like a real submission. Emails are not sent.

Run from the backend folder:
    .\\venv\\Scripts\\python.exe -m scripts.try_submit
"""
from app.core.constants import Channel, Role
from app.database import SessionLocal
from app.models.models import Reply, User
from app.services.query_service import submit_query

DEMO_STUDENT_EMAIL = "demo.student@example.com"
SAMPLE_TEXT = ("Assalam o Alaikum, my CS619 attendance for last week shows absent "
               "although I attended the session. Please check.")


def main() -> None:
    with SessionLocal() as db:
        student = db.query(User).filter(User.email == DEMO_STUDENT_EMAIL).first()
        if student is None:
            student = User(name="Demo Student", email=DEMO_STUDENT_EMAIL, role=Role.STUDENT)
            db.add(student)
            db.flush()

        query, emails = submit_query(db, student, SAMPLE_TEXT, Channel.WEB)
        db.commit()

        draft = db.query(Reply).filter(Reply.query_id == query.query_id).first()
        print(f"Reference : {query.reference_code}")
        print(f"Category  : {query.category}")
        print(f"Department: {query.department.name if query.department else '-'}")
        print(f"Course    : {query.course.code if query.course else '-'}")
        print(f"Assigned  : {query.assignee.email if query.assignee else 'department queue'}")
        print(f"Status    : {query.status}")
        print(f"Emails    : {[job.event for job in emails]}  (queued, not sent by this script)")
        print("\nAI draft prepared for the assignee:\n")
        print(draft.ai_draft_text if draft else "-")


if __name__ == "__main__":
    main()