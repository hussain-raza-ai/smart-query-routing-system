"""
Administration (SRS section 6.5): analytics (FR-10), report export (FR-12),
broadcast announcements (FR-11), the audit log (FR-14), the AI routing
rules and the department list.

HODs may open analytics and reports, but only ever for their own department.
"""
import csv
import io
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from fastapi import Query as QueryParam
from sqlalchemy.orm import Session, joinedload

from app.core.constants import PKT, Category, DepartmentType, NotificationKind, Role
from app.core.security import require_roles
from app.database import get_db
from app.models.models import AuditLog, Department, Query, RoutingRule, User
from app.schemas.admin_schemas import (
    AnalyticsOverview,
    AnnouncementRequest,
    AnnouncementResult,
    AuditEntry,
    AuditPage,
    DepartmentOut,
    RoutingRuleOut,
    RoutingRuleUpdate,
)
from app.services import analytics_service, report_service
from app.services.analytics_service import ReportFilters
from app.services.audit import record_action
from app.services.notification_service import EmailEvent, notify, send_email_event

router = APIRouter(tags=["Administration"])

require_admin = require_roles(Role.ADMIN)
require_admin_or_hod = require_roles(Role.ADMIN, Role.HOD)
require_staff = require_roles(*Role.STAFF)

DEFAULT_PERIOD_DAYS = 30
MAX_PERIOD_DAYS = 366

AUDIENCE_ROLES = {
    "students": (Role.STUDENT,),
    "staff": Role.STAFF,
    "everyone": Role.ALL,
}

EXPORT_TYPES = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


# --- Helpers -----------------------------------------------------------------

def _filters(user: User, date_from: Optional[date], date_to: Optional[date],
             department_id: Optional[int]) -> ReportFilters:
    """Fill in the default period and make sure an HOD only ever sees their own department."""
    date_to = date_to or datetime.now(PKT).date()
    date_from = date_from or date_to - timedelta(days=DEFAULT_PERIOD_DAYS - 1)
    if date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to")
    if (date_to - date_from).days >= MAX_PERIOD_DAYS:
        raise HTTPException(status_code=400, detail=f"Please choose a period of at most {MAX_PERIOD_DAYS} days")
    if user.role == Role.HOD:
        if user.department_id is None:
            raise HTTPException(status_code=403, detail="Your account is not linked to a department yet")
        department_id = user.department_id
    return ReportFilters(date_from, date_to, department_id)


def _scope_label(db: Session, filters: ReportFilters) -> str:
    if filters.department_id is None:
        return "All departments"
    department = db.get(Department, filters.department_id)
    return department.name if department else f"Department {filters.department_id}"


def _rule_out(rule: RoutingRule) -> RoutingRuleOut:
    return RoutingRuleOut(category=rule.category, department_id=rule.department_id,
                          department_name=rule.department.name, target_role=rule.target_role,
                          updated_at=rule.updated_at)


# --- Analytics and reports (FR-10, FR-12) ------------------------------------

@router.get("/analytics/overview", response_model=AnalyticsOverview)
def analytics_overview(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    department_id: Optional[int] = None,
    user: User = Depends(require_admin_or_hod),
    db: Session = Depends(get_db),
):
    """Totals, workload and response time for a period (default: the last 30 days)."""
    return analytics_service.overview(db, _filters(user, date_from, date_to, department_id))


@router.get("/reports/export")
def export_report(
    file_format: Literal["pdf", "xlsx"] = QueryParam("xlsx", alias="format"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    department_id: Optional[int] = None,
    user: User = Depends(require_admin_or_hod),
    db: Session = Depends(get_db),
):
    """Download the same numbers as a PDF summary or a full Excel workbook."""
    filters = _filters(user, date_from, date_to, department_id)
    stats = analytics_service.overview(db, filters)
    scope = _scope_label(db, filters)
    generated_by = f"{user.name} ({user.role})"

    if file_format == "pdf":
        queries = analytics_service.report_queries(db, filters, limit=report_service.PDF_QUERY_LIMIT)
        content = report_service.build_pdf(stats, queries, filters, scope, generated_by)
    else:
        queries = analytics_service.report_queries(db, filters)
        content = report_service.build_excel(stats, queries, filters, scope, generated_by)

    record_action(db, "REPORT_EXPORTED", user_id=user.user_id,
                  details=f"{file_format.upper()} for {scope}, {filters.date_from} to {filters.date_to}")
    db.commit()

    filename = f"query-report-{filters.date_from:%Y%m%d}-{filters.date_to:%Y%m%d}.{file_format}"
    return Response(content=content, media_type=EXPORT_TYPES[file_format],
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# --- Announcements (FR-11) ---------------------------------------------------

@router.post("/announcements", response_model=AnnouncementResult, status_code=201)
def broadcast(
    body: AnnouncementRequest,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Send an announcement to every active user in the audience: on the dashboard, and by email through n8n."""
    recipients = (db.query(User)
                    .filter(User.role.in_(AUDIENCE_ROLES[body.audience]), User.is_active.is_(True))
                    .all())
    if not recipients:
        raise HTTPException(status_code=400, detail="No active users match this audience")

    title, message = body.title.strip(), body.message.strip()
    emails = [person.email for person in recipients]
    for person in recipients:
        notify(db, person.user_id, message, title=title, kind=NotificationKind.ANNOUNCEMENT)
    record_action(db, "ANNOUNCEMENT_SENT", user_id=admin.user_id,
                  details=f"'{title}' to {len(recipients)} user(s) ({body.audience})")
    db.commit()

    if body.send_email:
        background_tasks.add_task(send_email_event, EmailEvent.ANNOUNCEMENT,
                                  {"title": title, "message": message, "recipients": emails})
    return AnnouncementResult(recipients=len(recipients), email_queued=body.send_email)



# --- Routing rules and departments -------------------------------------------

@router.get("/routing-rules", response_model=list[RoutingRuleOut])
def list_routing_rules(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Which department and role receive each AI category."""
    rules = (db.query(RoutingRule).options(joinedload(RoutingRule.department))
               .order_by(RoutingRule.category).all())
    return [_rule_out(rule) for rule in rules]


@router.put("/routing-rules/{category}", response_model=RoutingRuleOut)
def update_routing_rule(category: str, body: RoutingRuleUpdate,
                        admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Change where one category is routed. It applies from the next query submitted."""
    if category not in Category.ALL:
        raise HTTPException(status_code=404, detail=f"Unknown category '{category}'")
    department = db.get(Department, body.department_id)
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    academic_role = body.target_role == Role.INSTRUCTOR
    if academic_role != (department.type == DepartmentType.ACADEMIC):
        raise HTTPException(status_code=400,
                            detail="Instructors work in academic departments; "
                                   "DepartmentStaff work in the service desks")
    rule = db.get(RoutingRule, category)
    if rule is None:
        rule = RoutingRule(category=category)
        db.add(rule)
        before = "no rule"
    else:
        before = f"{rule.department.name} / {rule.target_role}"
    rule.department_id = department.department_id
    rule.target_role = body.target_role
    record_action(db, "ROUTING_RULE_UPDATED", user_id=admin.user_id,
                  details=f"{category}: {before} -> {department.name} / {body.target_role}")
    db.commit()
    return _rule_out(rule)


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(user: User = Depends(require_staff), db: Session = Depends(get_db)):
    """All departments, for the dropdowns in the staff and admin dashboards."""
    return [DepartmentOut.model_validate(d) for d in db.query(Department).order_by(Department.name).all()]

    # --- Audit log (FR-14) -------------------------------------------------------

AUDIT_EXPORT_LIMIT = 10000


def _audit_entries(db: Session, user_id: Optional[int], action: Optional[str],
                   date_from: Optional[date], date_to: Optional[date]):
    """Audit entries matching the filters, newest first, with the actor's name and the query reference."""
    rows = (
        db.query(AuditLog, User.name, Query.reference_code)
        .outerjoin(User, AuditLog.user_id == User.user_id)
        .outerjoin(Query, AuditLog.query_id == Query.query_id)
    )
    if user_id is not None:
        rows = rows.filter(AuditLog.user_id == user_id)
    if action:
        rows = rows.filter(AuditLog.action == action.strip().upper())
    if date_from:
        rows = rows.filter(AuditLog.timestamp >= datetime.combine(date_from, time.min, tzinfo=PKT))
    if date_to:
        rows = rows.filter(AuditLog.timestamp < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=PKT))
    return rows.order_by(AuditLog.log_id.desc())


def _csv_safe(text: str) -> str:
    """Stop spreadsheet programs from treating text such as '=HYPERLINK(...)' as a formula."""
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


@router.get("/audit-log", response_model=AuditPage)
def audit_log(
    user_id: Optional[int] = None,
    action: Optional[str] = QueryParam(None, max_length=100),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = QueryParam(50, ge=1, le=200),
    offset: int = QueryParam(0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """The permanent activity trail, newest first, with optional filters and paging."""
    rows = _audit_entries(db, user_id, action, date_from, date_to)
    total = rows.count()
    page = rows.offset(offset).limit(limit).all()
    return AuditPage(total=total, items=[
        AuditEntry(log_id=log.log_id, timestamp=log.timestamp, actor=name or "System",
                   action=log.action, reference_code=reference, details=log.details)
        for log, name, reference in page
    ])


@router.get("/audit-log/export")
def export_audit_log(
    user_id: Optional[int] = None,
    action: Optional[str] = QueryParam(None, max_length=100),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """The filtered audit log as a CSV file that opens in Excel (SRS UC-11)."""
    rows = _audit_entries(db, user_id, action, date_from, date_to).limit(AUDIT_EXPORT_LIMIT).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Time (PKT)", "Who", "Action", "Query", "Details"])
    for log, name, reference in rows:
        writer.writerow([
            log.timestamp.astimezone(PKT).strftime("%Y-%m-%d %H:%M"),
            _csv_safe(name or "System"),
            log.action,
            reference or "",
            _csv_safe(log.details or ""),
        ])

    record_action(db, "AUDIT_LOG_EXPORTED", user_id=admin.user_id, details=f"{len(rows)} entries")
    db.commit()

    filename = f"audit-log-{datetime.now(PKT):%Y%m%d}.csv"
    return Response(content="\ufeff" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})