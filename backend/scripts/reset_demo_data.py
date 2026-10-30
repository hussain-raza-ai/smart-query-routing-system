"""
Clears every query and everything attached to it (status history, routes,
replies, notifications, escalations) and empties the audit log, so a demo
starts from a clean slate. Users, departments, courses and routing rules stay.

The audit log is append-only: a trigger rejects UPDATE and DELETE on its rows.
TRUNCATE empties a whole table at once and is not affected by row triggers,
so this deliberate reset is the only way to clear it. Never run it on a live system.

Run from the backend folder:
    .\\venv\\Scripts\\python.exe -m scripts.reset_demo_data
"""
from sqlalchemy import text

from app.database import engine

TABLES = "audit_log, escalations, notifications, replies, routes, query_status_history, queries"


def main() -> None:
    answer = input("This permanently deletes all queries, notifications and the audit log.\n"
                   "Type RESET to continue: ")
    if answer.strip() != "RESET":
        print("Nothing was changed.")
        return

    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY"))
        connection.execute(text(
            "INSERT INTO audit_log (action, details) "
            "VALUES ('DEMO_DATA_RESET', 'All queries and activity cleared for a fresh demo')"
        ))
    print("Done. Users, departments, courses and routing rules were kept.")


if __name__ == "__main__":
    main()