"""
Prints the analytics overview for the last 30 days and saves both report
files in the backend folder so they can be opened and checked by hand.
Nothing in the database is changed.

Run from the backend folder:
    .\\venv\\Scripts\\python.exe -m scripts.try_reports
"""
from datetime import datetime, timedelta
from pathlib import Path

from app.core.constants import PKT
from app.database import SessionLocal
from app.services import analytics_service, report_service
from app.services.analytics_service import ReportFilters


def main() -> None:
    today = datetime.now(PKT).date()
    filters = ReportFilters(date_from=today - timedelta(days=29), date_to=today)

    with SessionLocal() as db:
        stats = analytics_service.overview(db, filters)
        print(f"{stats['total_queries']} queries, {stats['resolution_rate']}% resolved, "
              f"average response {stats['avg_response_hours']} h\n")
        for status, count in stats["status_counts"].items():
            print(f"  {status:16} {count}")
        print("\nBy department:")
        for row in stats["by_department"]:
            print(f"  {row['department']:26} total {row['total']:4}   still open {row['open']:4}")

        queries = analytics_service.report_queries(db, filters)
        Path("report-test.xlsx").write_bytes(
            report_service.build_excel(stats, queries, filters, "All departments", "try_reports script"))
        Path("report-test.pdf").write_bytes(
            report_service.build_pdf(stats, queries[:report_service.PDF_QUERY_LIMIT], filters,
                                     "All departments", "try_reports script"))

    print("\nSaved report-test.xlsx and report-test.pdf in the backend folder (delete them after checking).")


if __name__ == "__main__":
    main()