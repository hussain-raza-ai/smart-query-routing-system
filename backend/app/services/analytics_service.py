"""
Analytics (FR-10, SRS UC-08): the numbers behind the Admin and HOD
dashboards and the exported reports.

All counting is done by the database with GROUP BY queries, so the
dashboard stays quick however many queries pile up.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import extract, func, literal_column
from sqlalchemy.orm import Session, joinedload

from app.core.constants import PKT, Category, ReplyStatus, Status
from app.models.models import Department, Query, QueryStatusHistory, Reply

# The calendar day a query was submitted on, in Pakistan time (the database stores UTC).
_LOCAL_DAY = func.date(func.timezone(literal_column("'Asia/Karachi'"), Query.created_at))


@dataclass
class ReportFilters:
    """A period in Pakistan dates (both days included) and an optional department."""
    date_from: date
    date_to: date
    department_id: Optional[int] = None

    def conditions(self) -> list:
        start = datetime.combine(self.date_from, time.min, tzinfo=PKT)
        end = datetime.combine(self.date_to + timedelta(days=1), time.min, tzinfo=PKT)
        conditions = [Query.created_at >= start, Query.created_at < end]
        if self.department_id is not None:
            conditions.append(Query.department_id == self.department_id)
        return conditions


def overview(db: Session, filters: ReportFilters) -> dict:
    """Totals, workload and response time for the chosen period."""
    where = filters.conditions()

    status_counts = {status: 0 for status in Status.ALL}
    for status, count in db.query(Query.status, func.count()).filter(*where).group_by(Query.status).all():
        status_counts[status] = count
    total = sum(status_counts.values())

    category_counts = {category: 0 for category in Category.ALL}
    for category, count in db.query(Query.category, func.count()).filter(*where).group_by(Query.category).all():
        key = category or Category.GENERAL
        category_counts[key] = category_counts.get(key, 0) + count

    department_rows = (
        db.query(Department.name,
                 func.count(Query.query_id),
                 func.count(Query.query_id).filter(Query.status != Status.RESOLVED))
        .select_from(Query)
        .outerjoin(Department, Query.department_id == Department.department_id)
        .filter(*where)
        .group_by(Department.name)
        .order_by(func.count(Query.query_id).desc())
        .all()
    )

    per_day = dict(db.query(_LOCAL_DAY, func.count()).filter(*where).group_by(_LOCAL_DAY).all())
    daily_volume = []
    for offset in range((filters.date_to - filters.date_from).days + 1):
        day = filters.date_from + timedelta(days=offset)
        daily_volume.append({"day": day, "count": per_day.get(day, 0)})

    # Response time = submission until the first reply that was actually sent.
    first_reply = (
        db.query(Reply.query_id, func.min(Reply.sent_at).label("sent_at"))
        .filter(Reply.status == ReplyStatus.SENT)
        .group_by(Reply.query_id)
        .subquery()
    )
    avg_seconds = (
        db.query(func.avg(extract("epoch", first_reply.c.sent_at - Query.created_at)))
        .select_from(Query)
        .join(first_reply, first_reply.c.query_id == Query.query_id)
        .filter(*where)
        .scalar()
    )

    return {
        "date_from": filters.date_from,
        "date_to": filters.date_to,
        "department_id": filters.department_id,
        "total_queries": total,
        "status_counts": status_counts,
        "resolution_rate": round(100 * status_counts[Status.RESOLVED] / total, 1) if total else 0.0,
        "avg_response_hours": round(float(avg_seconds) / 3600, 1) if avg_seconds is not None else None,
        "by_department": [{"department": name or "Manual review", "total": count, "open": still_open}
                          for name, count, still_open in department_rows],
        "by_category": [{"category": category, "count": count} for category, count in category_counts.items()],
        "daily_volume": daily_volume,
    }


def report_queries(db: Session, filters: ReportFilters, limit: Optional[int] = None) -> list[Query]:
    """The queries behind a report, newest first, with student, assignee and department preloaded."""
    rows = (
        db.query(Query)
        .options(joinedload(Query.student), joinedload(Query.assignee), joinedload(Query.department))
        .filter(*filters.conditions())
        .order_by(Query.created_at.desc())
    )
    return rows.limit(limit).all() if limit else rows.all()


DAILY_SUMMARY_OLDEST = 5


def daily_summary(db: Session, department_id: Optional[int] = None) -> dict:
    """
    The last 24 hours for one department, or for all of them when department_id
    is None: what came in, what was resolved, and what is still waiting.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    scope = [] if department_id is None else [Query.department_id == department_id]

    received = db.query(func.count(Query.query_id)).filter(Query.created_at >= since, *scope).scalar()
    resolved = (
        db.query(func.count(QueryStatusHistory.history_id))
        .join(Query, Query.query_id == QueryStatusHistory.query_id)
        .filter(QueryStatusHistory.new_status == Status.RESOLVED, QueryStatusHistory.changed_at >= since, *scope)
        .scalar()
    )
    open_queries = db.query(Query).filter(Query.status != Status.RESOLVED, *scope)
    oldest = open_queries.order_by(Query.updated_at).limit(DAILY_SUMMARY_OLDEST).all()

    return {
        "received": received,
        "resolved": resolved,
        "open": open_queries.count(),
        "escalated": open_queries.filter(Query.status == Status.ESCALATED).count(),
        "oldest": [
            {"reference_code": query.reference_code, "category": query.category or "-", "status": query.status,
             "waiting_hours": int((now - query.updated_at).total_seconds() // 3600)}
            for query in oldest
        ],
    }