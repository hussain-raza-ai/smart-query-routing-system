"""
Request and response shapes for user management, analytics, reports,
announcements, the audit log, routing rules and notifications.
"""
from datetime import date, datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.core.constants import PKT

RoleName = Literal["Student", "Instructor", "HOD", "DepartmentStaff", "Admin"]


# --- Users -------------------------------------------------------------------

class UserOut(BaseModel):
    user_id: int
    name: str
    email: str
    role: str
    department_id: Optional[int]
    department_name: Optional[str]
    is_active: bool
    on_leave: bool
    leave_from: Optional[datetime]
    leave_until: Optional[datetime]
    auto_reply_message: Optional[str]
    created_at: datetime


class UserCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    role: RoleName
    department_id: Optional[int] = Field(None, description="Required for Instructor, HOD and DepartmentStaff")


class UserUpdateRequest(BaseModel):
    """Every field is optional; only the fields that are sent are changed."""
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    role: Optional[RoleName] = None
    department_id: Optional[int] = None
    is_active: Optional[bool] = None


class LeaveRequest(BaseModel):
    leave_from: datetime
    leave_until: datetime
    auto_reply_message: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def check_period(self):
        # A time typed without a timezone (e.g. from a date picker) is Pakistan time.
        if self.leave_from.tzinfo is None:
            self.leave_from = self.leave_from.replace(tzinfo=PKT)
        if self.leave_until.tzinfo is None:
            self.leave_until = self.leave_until.replace(tzinfo=PKT)
        if self.leave_until <= self.leave_from:
            raise ValueError("The leave must end after it starts.")
        if self.leave_until <= datetime.now(timezone.utc):
            raise ValueError("This leave period has already ended.")
        return self


# --- Analytics ---------------------------------------------------------------

class DepartmentLoad(BaseModel):
    department: str
    total: int
    open: int


class CategoryCount(BaseModel):
    category: str
    count: int


class DailyCount(BaseModel):
    day: date
    count: int


class AnalyticsOverview(BaseModel):
    date_from: date
    date_to: date
    department_id: Optional[int]
    total_queries: int
    status_counts: dict[str, int]
    resolution_rate: float = Field(description="Percent of the period's queries that are resolved")
    avg_response_hours: Optional[float] = Field(description="Average time from submission to the first reply")
    by_department: list[DepartmentLoad]
    by_category: list[CategoryCount]
    daily_volume: list[DailyCount]


# --- Announcements -----------------------------------------------------------

class AnnouncementRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=150)
    message: str = Field(..., min_length=5, max_length=2000)
    audience: Literal["students", "staff", "everyone"] = "students"
    send_email: bool = True


class AnnouncementResult(BaseModel):
    recipients: int
    email_queued: bool


# --- Audit log ---------------------------------------------------------------

class AuditEntry(BaseModel):
    log_id: int
    timestamp: datetime
    actor: str  # a person's name, or "System"
    action: str
    reference_code: Optional[str]
    details: Optional[str]


class AuditPage(BaseModel):
    total: int
    items: list[AuditEntry]


# --- Routing rules and departments -------------------------------------------

class RoutingRuleOut(BaseModel):
    category: str
    department_id: int
    department_name: str
    target_role: str
    updated_at: datetime


class RoutingRuleUpdate(BaseModel):
    department_id: int
    target_role: Literal["Instructor", "DepartmentStaff"]


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    department_id: int
    name: str
    type: str


# --- Notifications -----------------------------------------------------------

class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notification_id: int
    kind: str
    title: Optional[str]
    message: str
    query_id: Optional[int]
    is_read: bool
    sent_at: datetime