"""
Creates a small set of demo staff accounts so routing, escalation and the
dashboards can be tried out without real staff. Safe to run more than once:
accounts that already exist are left untouched.

Demo accounts use @example.com addresses, so nobody can sign in with them;
they only receive routed queries. To try a staff dashboard yourself, let the
Admin assign a role to a real Google account instead.

Run from the backend folder:
    .\\venv\\Scripts\\python.exe -m scripts.seed_demo_users
"""
from app.core.constants import DepartmentType, Role
from app.database import SessionLocal
from app.models.models import Course, Department, User
from app.services.audit import record_action

# (name, email, role, department type)
DEMO_USERS = [
    ("Sana Malik", "finance.staff@example.com", Role.DEPARTMENT_STAFF, DepartmentType.FINANCE),
    ("Bilal Ahmed", "exam.staff@example.com", Role.DEPARTMENT_STAFF, DepartmentType.EXAM),
    ("Ayesha Khan", "registrar.staff@example.com", Role.DEPARTMENT_STAFF, DepartmentType.REGISTRAR),
    ("Usman Tariq", "it.staff@example.com", Role.DEPARTMENT_STAFF, DepartmentType.IT),
    ("Dr. Farah Javed", "instructor.one@example.com", Role.INSTRUCTOR, DepartmentType.ACADEMIC),
    ("Mr. Hamza Ali", "instructor.two@example.com", Role.INSTRUCTOR, DepartmentType.ACADEMIC),
    ("Dr. Imran Qureshi", "hod.cs@example.com", Role.HOD, DepartmentType.ACADEMIC),
]

# Which demo instructor teaches which seeded course.
COURSE_INSTRUCTORS = {
    "CS619": "instructor.one@example.com",
    "CS101": "instructor.one@example.com",
    "CS201": "instructor.two@example.com",
}


def main() -> None:
    with SessionLocal() as db:
        # The seed data has exactly one department of each type.
        departments = {d.type: d for d in db.query(Department).all()}

        created = 0
        for name, email, role, dept_type in DEMO_USERS:
            if db.query(User).filter(User.email == email).first():
                continue
            db.add(User(name=name, email=email, role=role,
                        department_id=departments[dept_type].department_id))
            created += 1
        db.flush()

        for code, email in COURSE_INSTRUCTORS.items():
            course = db.query(Course).filter(Course.code == code).first()
            instructor = db.query(User).filter(User.email == email).first()
            if course and instructor:
                course.instructor_id = instructor.user_id

        if created:
            record_action(db, "DEMO_DATA_SEEDED", details=f"{created} demo staff account(s) created")
        db.commit()

    print(f"Demo users ready ({created} new). Course instructors linked for: "
          f"{', '.join(COURSE_INSTRUCTORS)}")


if __name__ == "__main__":
    main()