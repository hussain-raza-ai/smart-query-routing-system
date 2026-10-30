"""
Shows what each user can see and do, to verify record-level access control.
Read-only: nothing is changed.

Run from the backend folder:
    .\\venv\\Scripts\\python.exe -m scripts.try_access
"""
from app.database import SessionLocal
from app.models.models import Query, User
from app.services.access_control import can_act, visible_queries


def main() -> None:
    with SessionLocal() as db:
        sample = db.query(Query).order_by(Query.query_id.desc()).first()
        if sample is None:
            print("No queries yet. Run scripts.try_submit first.")
            return

        department = sample.department.name if sample.department else "-"
        print(f"Checking against {sample.reference_code} ({sample.category}, {department}, "
              f"assigned to {sample.assignee.name if sample.assignee else 'nobody'})\n")
        print(f"{'User':22} {'Role':16} {'Can see':>8}   Can act on it")
        print("-" * 64)
        for user in db.query(User).order_by(User.role, User.user_id).all():
            count = visible_queries(db, user).count()
            print(f"{user.name[:22]:22} {user.role:16} {count:>8}   {'yes' if can_act(user, sample) else 'no'}")


if __name__ == "__main__":
    main()