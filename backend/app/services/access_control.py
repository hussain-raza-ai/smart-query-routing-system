"""
Who can see and act on which queries (SDD section 10.2, record-level isolation).

Visibility:
    Student          their own queries
    Instructor       queries assigned to them or about a course they teach
    DepartmentStaff  every query in their department's queue
    HOD              every query in their department, plus anything escalated to them
    Admin            everything

Acting (status changes, replies, escalation, reassignment):
    Admin            any query
    Instructor       queries assigned to them
    DepartmentStaff  queries assigned to them or in their department's queue
    HOD              same as DepartmentStaff

A staff account that is not linked to a department yet only sees what is
assigned to it personally. These checks run on every request, so changing
an ID in the URL never exposes or alters another user's data.
"""
from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.constants import Role
from app.models.models import Course, Query, User


def _same_department(user: User, query: Query) -> bool:
    """True only for a real, shared department. Without the None check, None == None would match every unrouted query."""
    return user.department_id is not None and query.department_id == user.department_id


def visible_queries(db: Session, user: User):
    """A database query over `queries`, already limited to what `user` may see."""
    base = db.query(Query)
    if user.role == Role.ADMIN:
        return base
    if user.role == Role.STUDENT:
        return base.filter(Query.student_id == user.user_id)
    if user.role == Role.INSTRUCTOR:
        my_courses = select(Course.course_id).where(Course.instructor_id == user.user_id)
        return base.filter(or_(Query.assigned_to == user.user_id, Query.course_id.in_(my_courses)))
    # DepartmentStaff and HOD
    if user.department_id is None:
        return base.filter(Query.assigned_to == user.user_id)
    return base.filter(or_(Query.assigned_to == user.user_id,
                           Query.department_id == user.department_id))


def can_view(user: User, query: Query) -> bool:
    if user.role == Role.ADMIN:
        return True
    if user.role == Role.STUDENT:
        return query.student_id == user.user_id
    if query.assigned_to == user.user_id:
        return True
    if user.role == Role.INSTRUCTOR:
        return query.course is not None and query.course.instructor_id == user.user_id
    return _same_department(user, query)  # DepartmentStaff and HOD


def can_act(user: User, query: Query) -> bool:
    if user.role == Role.ADMIN:
        return True
    if user.role == Role.STUDENT:
        return False  # students use their own endpoint to add information
    if query.assigned_to == user.user_id:
        return True
    if user.role in (Role.DEPARTMENT_STAFF, Role.HOD):
        return _same_department(user, query)
    return False


def get_query_for(db: Session, user: User, query_id: int, *, to_act: bool = False) -> Query:
    """
    Load a query the user is allowed to see, or raise 404 so its existence is
    not revealed. With `to_act=True`, also require permission to change it (403).
    """
    query = db.get(Query, query_id)
    if query is None or not can_view(user, query):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    if to_act and not can_act(user, query):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You are not allowed to change this query")
    return query


def ensure_can_assign(actor: User, target: User) -> None:
    """Admins may assign anyone; everyone else only themselves or someone in their own department."""
    if actor.role == Role.ADMIN or target.user_id == actor.user_id:
        return
    if actor.department_id is None or target.department_id != actor.department_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You can only reassign queries within your own department")