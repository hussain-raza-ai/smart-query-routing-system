"""
Demonstrates the 24-hour SLA escalation (FR-07) without waiting a day.

Makes the newest open query look older than SLA_HOURS, runs the same check
that n8n calls every hour and prints what happened. This DOES change the
database. Emails are not sent by this script.

Run from the backend folder:
    .\\venv\\Scripts\\python.exe -m scripts.try_sla
"""
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.constants import Status
from app.database import SessionLocal
from app.models.models import Query
from app.services.query_service import run_sla_check


def main() -> None:
    with SessionLocal() as db:
        query = (db.query(Query)
                   .filter(Query.status.in_(Status.AWAITING_STAFF))
                   .order_by(Query.query_id.desc())
                   .first())
        if query is None:
            print("No open query to test with. Submit one first (scripts.try_submit).")
            return

        reference = query.reference_code
        handler = query.assignee.name if query.assignee else "nobody"
        long_ago = datetime.now(timezone.utc) - timedelta(hours=settings.SLA_HOURS + 1)
        query.updated_at = long_ago
        db.commit()
        db.refresh(query)
        if query.updated_at > long_ago + timedelta(minutes=1):
            print("The database reset updated_at by itself (probably a trigger). Please send schema.sql.")
            return
        print(f"{reference} (with {handler}) now looks {settings.SLA_HOURS + 1} hours old.")

        escalated, emails = run_sla_check(db)
        db.commit()
        if not escalated:
            print("Nothing was escalated. Is an HOD or Admin available to receive it?")
        for item in escalated:
            print(f"Escalated {item.reference_code} -> {item.assignee.name} ({item.assignee.email})")
        print(f"Emails n8n would send: {[job.event for job in emails]} (not sent by this script)")


if __name__ == "__main__":
    main()