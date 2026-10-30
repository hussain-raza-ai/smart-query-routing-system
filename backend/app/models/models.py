"""
Database models (SQLAlchemy ORM).

Each class maps to a table in `database/schema.sql`. The SQL file is the
single source of truth for constraints, indexes and seed data; these models
describe the columns and the relationships the code navigates.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import relationship

from app.core.constants import NotificationKind, ReplyStatus, Role, Status
from app.database import Base


class Department(Base):
    __tablename__ = "departments"

    department_id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    type = Column(String(30), nullable=False)
    description = Column(Text)


class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(150), nullable=False, unique=True)
    role = Column(String(20), nullable=False, default=Role.STUDENT)
    department_id = Column(Integer, ForeignKey("departments.department_id"))
    oauth_provider = Column(String(30), nullable=False, default="google")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Instructor leave mode (FR-13). Both columns are NULL when not on leave.
    leave_from = Column(DateTime(timezone=True))
    leave_until = Column(DateTime(timezone=True))
    auto_reply_message = Column(Text)

    department = relationship("Department")

    def is_on_leave(self, moment: Optional[datetime] = None) -> bool:
        """Return True if a leave period covers `moment` (defaults to now)."""
        if self.leave_from is None or self.leave_until is None:
            return False
        moment = moment or datetime.now(timezone.utc)
        return self.leave_from <= moment <= self.leave_until


class Course(Base):
    __tablename__ = "courses"

    course_id = Column(Integer, primary_key=True)
    code = Column(String(12), nullable=False, unique=True)
    title = Column(String(150), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=False)
    instructor_id = Column(Integer, ForeignKey("users.user_id"))

    department = relationship("Department")
    instructor = relationship("User")


class RoutingRule(Base):
    """Maps an AI category to the department and role that should handle it."""

    __tablename__ = "routing_rules"

    category = Column(String(30), primary_key=True)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=False)
    target_role = Column(String(20), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    department = relationship("Department")


class Query(Base):
    __tablename__ = "queries"

    query_id = Column(Integer, primary_key=True)
    reference_code = Column(String(20), nullable=False, unique=True)
    student_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.department_id"))
    course_id = Column(Integer, ForeignKey("courses.course_id"))
    assigned_to = Column(Integer, ForeignKey("users.user_id"))
    category = Column(String(30))
    intent = Column(String(100))  # the AI's short summary of the query, shown to staff
    channel = Column(String(20), nullable=False)
    query_text = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default=Status.PENDING)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Moves forward on every change; the SLA check measures inactivity from here.
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    student = relationship("User", foreign_keys=[student_id])
    assignee = relationship("User", foreign_keys=[assigned_to])
    department = relationship("Department")
    course = relationship("Course")


class QueryStatusHistory(Base):
    """One row per status change, shown to the student as a timeline (FR-06)."""

    __tablename__ = "query_status_history"

    history_id = Column(Integer, primary_key=True)
    query_id = Column(Integer, ForeignKey("queries.query_id"), nullable=False)
    old_status = Column(String(20))
    new_status = Column(String(20), nullable=False)
    changed_by = Column(Integer, ForeignKey("users.user_id"))  # NULL = system
    note = Column(String(255))
    changed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Route(Base):
    """A routing decision. A query may be routed more than once (re-routing, overrides)."""

    __tablename__ = "routes"

    route_id = Column(Integer, primary_key=True)
    query_id = Column(Integer, ForeignKey("queries.query_id"), nullable=False)
    routed_to_role = Column(String(20), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.department_id"))
    assigned_to = Column(Integer, ForeignKey("users.user_id"))
    ai_confidence = Column(Numeric(3, 2))
    method = Column(String(20), nullable=False)  # see RouteMethod
    routed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Reply(Base):
    __tablename__ = "replies"

    reply_id = Column(Integer, primary_key=True)
    query_id = Column(Integer, ForeignKey("queries.query_id"), nullable=False)
    responder_id = Column(Integer, ForeignKey("users.user_id"))  # NULL until a human sends it
    ai_draft_text = Column(Text)
    final_text = Column(Text)
    status = Column(String(20), nullable=False, default=ReplyStatus.DRAFT)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_at = Column(DateTime(timezone=True))


class Notification(Base):
    __tablename__ = "notifications"

    notification_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    query_id = Column(Integer, ForeignKey("queries.query_id"))  # NULL for announcements
    kind = Column(String(20), nullable=False, default=NotificationKind.UPDATE)
    channel = Column(String(20), nullable=False)
    title = Column(String(150))
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, nullable=False, default=False)
    sent_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Escalation(Base):
    __tablename__ = "escalations"

    escalation_id = Column(Integer, primary_key=True)
    query_id = Column(Integer, ForeignKey("queries.query_id"), nullable=False)
    escalated_by = Column(Integer, ForeignKey("users.user_id"))  # NULL = automatic SLA
    escalated_to = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    reason = Column(String(255))
    escalated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AuditLog(Base):
    """Append-only activity trail (FR-14). The database rejects updates and deletes."""

    __tablename__ = "audit_log"

    log_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))  # NULL = system action
    query_id = Column(Integer, ForeignKey("queries.query_id"))
    action = Column(String(100), nullable=False)
    details = Column(Text)
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())