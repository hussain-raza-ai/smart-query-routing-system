"""
Routing engine (FR-04, SRS UC-13).

Turns an AI classification into a destination: a department and, when
possible, a specific person. Rules come from the routing_rules table, so the
Admin can change them without touching the code.

How a person is chosen:
    1. Course and Attendance queries that mention a known course code go to
       that course's instructor, if they are active and not on leave.
    2. Otherwise the least busy available member of the target role in the
       target department is chosen (load-based assignment).
    3. If nobody is available, the query goes to the department's supervisor:
       the HOD for academic departments, an Admin for service desks.
    4. Queries the AI could not classify go straight to an Admin for review.
"""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.constants import Category, DepartmentType, Role, Status
from app.models.models import Course, Department, Query, RoutingRule, User
from app.services.ai_service import ClassificationResult


@dataclass
class RoutingDecision:
    department: Optional[Department]
    assignee: Optional[User]          # None means "waiting in the department queue"
    routed_to_role: str
    course: Optional[Course] = None
    reason: str = ""
    instructor_on_leave: Optional[User] = None  # set when the course instructor was skipped


def _available():
    """SQL condition: the account is active and not inside a leave period right now."""
    now = func.now()
    return and_(
        User.is_active.is_(True),
        or_(User.leave_from.is_(None), User.leave_from > now, User.leave_until < now),
    )


def _least_busy(db: Session, role: str, department_id: Optional[int] = None) -> Optional[User]:
    """The available user in `role` with the fewest open queries (ties go to the oldest account)."""
    open_load = (
        db.query(Query.assigned_to.label("user_id"), func.count(Query.query_id).label("load"))
        .filter(Query.status != Status.RESOLVED)
        .group_by(Query.assigned_to)
        .subquery()
    )
    candidates = (
        db.query(User)
        .outerjoin(open_load, open_load.c.user_id == User.user_id)
        .filter(User.role == role, _available())
    )
    if department_id is not None:
        candidates = candidates.filter(User.department_id == department_id)
    return candidates.order_by(func.coalesce(open_load.c.load, 0), User.user_id).first()


def find_supervisor(db: Session, department: Optional[Department]) -> Optional[User]:
    """Who supervises a department: its HOD if it is academic, otherwise an Admin."""
    if department is not None and department.type == DepartmentType.ACADEMIC:
        hod = _least_busy(db, Role.HOD, department.department_id)
        if hod:
            return hod
    return _least_busy(db, Role.ADMIN)


def route_query(db: Session, result: ClassificationResult) -> RoutingDecision:
    """Decide where a classified query should go. Nothing is saved here."""
    if result.needs_review:
        return RoutingDecision(
            department=None,
            assignee=_least_busy(db, Role.ADMIN),
            routed_to_role=Role.ADMIN,
            reason="The AI could not classify this query; sent to an Admin for manual review",
        )

    rule = db.get(RoutingRule, result.category) or db.get(RoutingRule, Category.GENERAL)
    if rule is None:
        return RoutingDecision(
            department=None,
            assignee=_least_busy(db, Role.ADMIN),
            routed_to_role=Role.ADMIN,
            reason=f"No routing rule for '{result.category}'; sent to an Admin",
        )

    department = rule.department
    course = None
    instructor_on_leave = None

    # 1. A known course code sends Course/Attendance queries to that course's instructor.
    if rule.target_role == Role.INSTRUCTOR and result.course_code:
        course = db.query(Course).filter(Course.code == result.course_code).first()
        if course:
            department = course.department
            instructor = course.instructor
            if instructor and instructor.is_active and not instructor.is_on_leave():
                return RoutingDecision(department, instructor, Role.INSTRUCTOR, course,
                                       reason=f"Instructor of {course.code}")
            if instructor and instructor.is_on_leave():
                instructor_on_leave = instructor

    # 2. Otherwise the least busy available person in the target role.
    person = _least_busy(db, rule.target_role, department.department_id)
    if person:
        return RoutingDecision(department, person, rule.target_role, course,
                               reason=f"Least busy {rule.target_role} in {department.name}",
                               instructor_on_leave=instructor_on_leave)

    # 3. Nobody available: hand the query to whoever supervises this department.
    supervisor = find_supervisor(db, department)
    return RoutingDecision(
        department=department,
        assignee=supervisor,
        routed_to_role=supervisor.role if supervisor else Role.ADMIN,
        course=course,
        reason=f"No {rule.target_role} available in {department.name}; sent to supervisor",
        instructor_on_leave=instructor_on_leave,
    )