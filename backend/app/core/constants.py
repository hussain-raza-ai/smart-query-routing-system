"""
Fixed values shared across the backend.

The database enforces the same values with CHECK constraints
(see database/schema.sql). If you change one side, change the other.
"""
from datetime import timedelta, timezone

# Pakistan Standard Time (UTC+5, no daylight saving). The database stores
# everything in UTC; PKT is only used when dates are shown to or typed by people.
PKT = timezone(timedelta(hours=5), "PKT")


class Role:
    STUDENT = "Student"
    INSTRUCTOR = "Instructor"
    HOD = "HOD"
    DEPARTMENT_STAFF = "DepartmentStaff"
    ADMIN = "Admin"

    ALL = (STUDENT, INSTRUCTOR, HOD, DEPARTMENT_STAFF, ADMIN)
    STAFF = (INSTRUCTOR, HOD, DEPARTMENT_STAFF, ADMIN)


class Status:
    PENDING = "Pending"
    IN_PROGRESS = "In Progress"
    NEEDS_MORE_INFO = "Needs More Info"
    ESCALATED = "Escalated"
    RESOLVED = "Resolved"

    ALL = (PENDING, IN_PROGRESS, NEEDS_MORE_INFO, ESCALATED, RESOLVED)
    # The ball is in the staff's court; only these statuses count towards the SLA.
    AWAITING_STAFF = (PENDING, IN_PROGRESS)


class Category:
    FEE = "Fee"
    RESULT = "Result"
    COURSE = "Course"
    ATTENDANCE = "Attendance"
    DEGREE = "Degree"
    IT = "IT"
    GENERAL = "General"

    ALL = (FEE, RESULT, COURSE, ATTENDANCE, DEGREE, IT, GENERAL)


class DepartmentType:
    ACADEMIC = "Academic"
    EXAM = "Exam"
    REGISTRAR = "Registrar"
    FINANCE = "Finance"
    IT = "IT"

    ALL = (ACADEMIC, EXAM, REGISTRAR, FINANCE, IT)
    SERVICE_DESKS = (EXAM, REGISTRAR, FINANCE, IT)


class Channel:
    WEB = "web"
    EMAIL = "email"


class ReplyStatus:
    DRAFT = "Draft"
    SENT = "Sent"


class RouteMethod:
    """Records which step of the AI pipeline made a routing decision."""
    GEMINI = "gemini"
    CLAUDE = "claude"
    KEYWORD = "keyword"
    MANUAL = "manual"


class NotificationKind:
    UPDATE = "update"
    ANNOUNCEMENT = "announcement"


class NotificationChannel:
    DASHBOARD = "dashboard"
    EMAIL = "email"