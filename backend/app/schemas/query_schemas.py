"""
Request and response shapes for the query endpoints.

Pydantic validates every incoming body before it reaches the business logic
(SDD 10.3), and the response models document exactly what each endpoint
returns on the /docs page.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# --- Requests ----------------------------------------------------------------

class QuerySubmitRequest(BaseModel):
    query_text: str = Field(..., min_length=10, max_length=2000,
                            description="The problem, described in the student's own words")


class StatusChangeRequest(BaseModel):
    # Must match Status.IN_PROGRESS, NEEDS_MORE_INFO and RESOLVED in core/constants.py
    status: Literal["In Progress", "Needs More Info", "Resolved"]
    note: Optional[str] = Field(None, max_length=255,
                                description="Required for 'Needs More Info' and 'Resolved'")


class ReplyRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000,
                      description="The final reply, reviewed and approved by the staff member")


class EscalateRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=255)


class ReassignRequest(BaseModel):
    assignee_id: int = Field(..., description="User ID of the staff member who should take over")
    reason: Optional[str] = Field(None, max_length=255)


class MoreInfoRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class FAQRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


# --- Responses ---------------------------------------------------------------

class HistoryEntry(BaseModel):
    old_status: Optional[str]
    new_status: str
    changed_by: str  # a person's name, or "System"
    note: Optional[str]
    changed_at: datetime


class SentReply(BaseModel):
    text: str
    sent_by: str
    sent_at: datetime


class QuerySummary(BaseModel):
    query_id: int
    reference_code: str
    category: Optional[str]
    intent: Optional[str] = None  # the AI's short summary; hidden from students
    status: str
    channel: str
    query_text: str
    department_name: Optional[str]
    course_code: Optional[str]
    student_name: str
    assigned_to_name: Optional[str]  # hidden from students
    created_at: datetime
    updated_at: datetime


class QueryDetail(QuerySummary):
    history: list[HistoryEntry]
    replies: list[SentReply]
    # Staff only; always null for students.
    ai_draft: Optional[str] = None
    ai_confidence: Optional[float] = None
    routing_method: Optional[str] = None
    can_act: bool = False


class ActionResult(BaseModel):
    query_id: int
    reference_code: str
    status: str
    message: str


class FAQAnswer(BaseModel):
    answer: str