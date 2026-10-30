"""
User management (SRS section 6.5) and instructor leave mode (FR-13, SRS UC-05).

- Admins list, create and edit accounts: name, role, department, and
  deactivation. A deactivated user keeps their history but cannot sign in.
- Staff can list the colleagues a query may be handed to.
- Instructors set and cancel their own leave period.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Query as QueryParam
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.constants import PKT, DepartmentType, Role, Status
from app.core.security import require_roles
from app.database import get_db
from app.models.models import Department, Query, User
from app.schemas.admin_schemas import LeaveRequest, UserCreateRequest, UserOut, UserUpdateRequest
from app.services.audit import record_action

router = APIRouter(prefix="/users", tags=["Users"])

require_admin = require_roles(Role.ADMIN)
require_staff = require_roles(*Role.STAFF)
require_instructor = require_roles(Role.INSTRUCTOR)

# The kind of department each staff role works in. Students and Admins have none.
ROLE_DEPARTMENT_TYPES = {
    Role.INSTRUCTOR: (DepartmentType.ACADEMIC,),
    Role.HOD: (DepartmentType.ACADEMIC,),
    Role.DEPARTMENT_STAFF: DepartmentType.SERVICE_DESKS,
}


# --- Helpers -----------------------------------------------------------------

def _out(user: User) -> UserOut:
    return UserOut(
        user_id=user.user_id,
        name=user.name,
        email=user.email,
        role=user.role,
        department_id=user.department_id,
        department_name=user.department.name if user.department else None,
        is_active=user.is_active,
        on_leave=user.is_on_leave(),
        leave_from=user.leave_from,
        leave_until=user.leave_until,
        auto_reply_message=user.auto_reply_message,
        created_at=user.created_at,
    )


def _local(moment) -> str:
    return moment.astimezone(PKT).strftime("%d %b %Y %H:%M")


def _department_for(db: Session, role: str, department_id: Optional[int]) -> Optional[Department]:
    """Check that the role and department fit together; return the department to store (or None)."""
    allowed_types = ROLE_DEPARTMENT_TYPES.get(role)
    if allowed_types is None:
        return None  # Students and Admins are not tied to a department
    department = db.get(Department, department_id) if department_id is not None else None
    if department is None or department.type not in allowed_types:
        raise HTTPException(status_code=400,
                            detail=f"{role} accounts must belong to one of these department types: "
                                   f"{', '.join(allowed_types)}.")
    return department


def _open_query_count(db: Session, user_id: int) -> int:
    return (db.query(func.count(Query.query_id))
              .filter(Query.assigned_to == user_id, Query.status != Status.RESOLVED)
              .scalar())


# --- Staff -------------------------------------------------------------------

@router.get("/staff", response_model=list[UserOut])
def list_staff(
    department_id: Optional[int] = None,
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Active staff a query can be reassigned to. Non-admins only see their own department."""
    rows = (db.query(User).options(joinedload(User.department))
              .filter(User.role.in_(Role.STAFF), User.is_active.is_(True)))
    if user.role != Role.ADMIN:
        if user.department_id is None:
            rows = rows.filter(User.user_id == user.user_id)
        else:
            rows = rows.filter(User.department_id == user.department_id)
    elif department_id is not None:
        rows = rows.filter(User.department_id == department_id)
    return [_out(person) for person in rows.order_by(User.role, User.name).all()]


# --- Instructor leave mode (FR-13) -------------------------------------------

@router.patch("/me/auto-reply", response_model=UserOut)
def set_leave(body: LeaveRequest, instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """
    Start or change a leave period. Until it ends, new queries skip this
    instructor and students receive the auto-reply instead.
    """
    message = (body.auto_reply_message or "").strip() or (
        f"I am on leave until {body.leave_until.astimezone(PKT):%d %b %Y}. "
        "Your query has been passed to the department so that it is not delayed."
    )
    instructor.leave_from = body.leave_from
    instructor.leave_until = body.leave_until
    instructor.auto_reply_message = message
    record_action(db, "LEAVE_SET", user_id=instructor.user_id,
                  details=f"{_local(body.leave_from)} to {_local(body.leave_until)}")
    db.commit()
    return _out(instructor)


@router.delete("/me/auto-reply", response_model=UserOut)
def cancel_leave(instructor: User = Depends(require_instructor), db: Session = Depends(get_db)):
    """End the leave early; the instructor receives new queries again straight away."""
    if instructor.leave_until is None:
        raise HTTPException(status_code=400, detail="You are not on leave.")
    instructor.leave_from = instructor.leave_until = instructor.auto_reply_message = None
    record_action(db, "LEAVE_CANCELLED", user_id=instructor.user_id)
    db.commit()
    return _out(instructor)


# --- Admin -------------------------------------------------------------------

@router.get("", response_model=list[UserOut])
def list_users(
    role: Optional[str] = None,
    search: Optional[str] = QueryParam(None, max_length=100, description="Part of a name or email"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(User).options(joinedload(User.department))
    if role:
        rows = rows.filter(User.role == role)
    if search:
        pattern = f"%{search.strip().lower()}%"
        rows = rows.filter(or_(func.lower(User.name).like(pattern), func.lower(User.email).like(pattern)))
    return [_out(user) for user in rows.order_by(User.role, User.name).all()]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreateRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Add an account before its owner signs in for the first time (e.g. staff outside the university domain)."""
    email = body.email.strip().lower()
    if db.query(User.user_id).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=409, detail="A user with this email already exists.")

    department = _department_for(db, body.role, body.department_id)
    user = User(name=body.name.strip(), email=email, role=body.role,
                department_id=department.department_id if department else None)
    db.add(user)
    db.flush()
    record_action(db, "USER_CREATED", user_id=admin.user_id,
                  details=f"{email} as {body.role}" + (f" in {department.name}" if department else ""))
    db.commit()
    return _out(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdateRequest,
                admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Change a user's name, role, department or active state. Only the fields sent are changed."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    sent = body.model_fields_set
    new_role = body.role or user.role
    new_active = user.is_active if body.is_active is None else body.is_active

    if user.user_id == admin.user_id and (new_role != Role.ADMIN or not new_active):
        raise HTTPException(status_code=400,
                            detail="You cannot remove your own Admin role or deactivate your own account.")

    # Someone who stops handling queries must hand their open ones over first, so none are stranded.
    if user.role in Role.STAFF and (new_role not in Role.STAFF or not new_active):
        open_count = _open_query_count(db, user.user_id)
        if open_count:
            raise HTTPException(status_code=409,
                                detail=f"{user.name} still has {open_count} open queries. Reassign them first.")

    changes = []
    if body.name and body.name.strip() != user.name:
        user.name = body.name.strip()
        changes.append(f"name -> {user.name}")
    if "role" in sent or "department_id" in sent:
        wanted_department = body.department_id if "department_id" in sent else user.department_id
        department = _department_for(db, new_role, wanted_department)
        new_department_id = department.department_id if department else None
        if new_role != user.role:
            changes.append(f"role {user.role} -> {new_role}")
        if new_department_id != user.department_id:
            changes.append(f"department -> {department.name if department else 'none'}")
        user.role, user.department_id = new_role, new_department_id
    if new_active != user.is_active:
        user.is_active = new_active
        changes.append("activated" if new_active else "deactivated")

    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to change.")
    record_action(db, "USER_UPDATED", user_id=admin.user_id, details=f"{user.email}: " + ", ".join(changes))
    db.commit()
    return _out(user)