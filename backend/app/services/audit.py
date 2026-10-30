"""
Audit trail helper (FR-14).

Every state-changing action is recorded through `record_action`, so all
audit entries look the same. Entries join the caller's database session and
are saved with the caller's commit: if the main action is rolled back, its
audit entry is rolled back with it.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import AuditLog


def record_action(
    db: Session,
    action: str,
    *,
    user_id: Optional[int] = None,
    query_id: Optional[int] = None,
    details: Optional[str] = None,
) -> None:
    """Add an audit entry. `user_id=None` means the system performed the action."""
    db.add(AuditLog(user_id=user_id, query_id=query_id, action=action, details=details))