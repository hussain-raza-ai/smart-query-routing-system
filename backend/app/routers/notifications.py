"""
Dashboard notifications (FR-08): what the bell menu shows.
Every user only ever sees and changes their own notifications.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Query as QueryParam
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database import get_db
from app.models.models import Notification, User
from app.schemas.admin_schemas import NotificationOut

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=list[NotificationOut])
def my_notifications(
    unread_only: bool = False,
    limit: int = QueryParam(30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(Notification).filter(Notification.user_id == user.user_id)
    if unread_only:
        rows = rows.filter(Notification.is_read.is_(False))
    rows = rows.order_by(Notification.notification_id.desc()).limit(limit).all()
    return [NotificationOut.model_validate(row) for row in rows]


@router.patch("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.is_read = True
    db.commit()
    return NotificationOut.model_validate(notification)


@router.post("/read-all")
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    updated = (db.query(Notification)
                 .filter(Notification.user_id == user.user_id, Notification.is_read.is_(False))
                 .update({Notification.is_read: True}, synchronize_session=False))
    db.commit()
    return {"updated": updated}