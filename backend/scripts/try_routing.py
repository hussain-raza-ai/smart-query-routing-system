"""
Shows where the routing engine would send different kinds of queries,
using the users currently in the database. Nothing is saved.

Run from the backend folder:
    .\\venv\\Scripts\\python.exe -m scripts.try_routing
"""
from app.database import SessionLocal
from app.services.ai_service import ClassificationResult
from app.services.routing_service import route_query

SAMPLES = [
    ClassificationResult("Fee", "Fee challan", 0.95, "gemini"),
    ClassificationResult("Result", "Result recheck", 0.95, "gemini"),
    ClassificationResult("Course", "Midterm syllabus", 0.95, "gemini", course_code="CS619"),
    ClassificationResult("Attendance", "Marked absent", 0.95, "gemini"),
    ClassificationResult("IT", "LMS login problem", 0.95, "gemini"),
    ClassificationResult("General", "Needs manual review", 0.0, "keyword", needs_review=True),
]


def main() -> None:
    with SessionLocal() as db:
        for sample in SAMPLES:
            decision = route_query(db, sample)
            label = sample.category + (f" ({sample.course_code})" if sample.course_code else "")
            department = decision.department.name if decision.department else "-"
            assignee = decision.assignee.email if decision.assignee else "department queue"
            print(f"{label:18} -> {department:24} {decision.routed_to_role:16} {assignee}")
            print(f"{'':21} reason: {decision.reason}")


if __name__ == "__main__":
    main()