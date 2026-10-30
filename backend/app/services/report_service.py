"""
Report files (FR-12, SRS UC-10).

Turns the analytics numbers and the matching queries into a PDF (a summary
for printing) or an Excel workbook (every row, for further analysis).
"""
import io
from datetime import datetime
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.constants import PKT, Status
from app.models.models import Query
from app.services.analytics_service import ReportFilters

PDF_QUERY_LIMIT = 300  # the PDF is a summary; the Excel file carries every row

QUERY_COLUMNS = [  # (heading, Excel column width)
    ("Reference", 16), ("Submitted (PKT)", 18), ("Student", 22), ("Student email", 30),
    ("Category", 12), ("Department", 24), ("Assigned to", 22), ("Status", 16),
    ("Channel", 9), ("Query", 90),
]

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="0F172A")


# --- Shared helpers ----------------------------------------------------------

def _period(filters: ReportFilters) -> str:
    return f"{filters.date_from:%d %b %Y} to {filters.date_to:%d %b %Y}"


def _local(moment) -> str:
    return moment.astimezone(PKT).strftime("%d %b %Y %H:%M") if moment else ""


def _plain(text) -> str:
    """One line of text, without the control characters Excel refuses to store."""
    return ILLEGAL_CHARACTERS_RE.sub("", " ".join((text or "").split()))


def _query_row(query: Query) -> list:
    return [
        query.reference_code,
        _local(query.created_at),
        _plain(query.student.name) if query.student else "",
        query.student.email if query.student else "",
        query.category or "",
        query.department.name if query.department else "Manual review",
        query.assignee.name if query.assignee else "Unassigned",
        query.status,
        query.channel,
        _plain(query.query_text),
    ]


# --- PDF ---------------------------------------------------------------------

def _pdf_text(text, limit: int) -> str:
    """The built-in PDF fonts only cover Latin text, so other characters print as '?'."""
    return _plain(text).encode("latin-1", "replace").decode("latin-1")[:limit]


def _pdf_table(rows, widths=None) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    return table


def build_pdf(stats: dict, queries: list[Query], filters: ReportFilters, scope: str, generated_by: str) -> bytes:
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10)
    avg = stats["avg_response_hours"]
    subtitle = (f"{scope}  |  {_period(filters)}  |  generated {datetime.now(PKT):%d %b %Y %H:%M} "
                f"by {_pdf_text(generated_by, 80)}")

    story = [
        Paragraph("Smart Query Routing System - Query Report", styles["Title"]),
        Paragraph(escape(subtitle), styles["Normal"]),
        Spacer(1, 0.5 * cm),
        _pdf_table([
            ["Total", *Status.ALL, "Resolved %", "Avg response"],
            [stats["total_queries"], *(stats["status_counts"][s] for s in Status.ALL),
             f"{stats['resolution_rate']}%", f"{avg} h" if avg is not None else "N/A"],
        ]),
        Spacer(1, 0.4 * cm),
        Paragraph("Queries by category", styles["Heading3"]),
        _pdf_table([[row["category"] for row in stats["by_category"]],
                    [row["count"] for row in stats["by_category"]]]),
        Spacer(1, 0.4 * cm),
        Paragraph("Department workload", styles["Heading3"]),
        _pdf_table([["Department", "Total", "Still open"]]
                   + [[row["department"], row["total"], row["open"]] for row in stats["by_department"]]),
        Spacer(1, 0.4 * cm),
        Paragraph(f"Queries (latest {len(queries)} of {stats['total_queries']})", styles["Heading3"]),
    ]

    rows = [["Reference", "Submitted", "Category", "Department", "Status", "Query"]]
    for query in queries:
        rows.append([
            query.reference_code,
            _local(query.created_at),
            query.category or "-",
            query.department.name if query.department else "Manual review",
            query.status,
            Paragraph(escape(_pdf_text(query.query_text, 300)), small),
        ])
    story.append(_pdf_table(rows, [3.0 * cm, 3.0 * cm, 2.2 * cm, 4.0 * cm, 2.6 * cm, 11.8 * cm]))

    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=landscape(A4), title="Query Report",
                      leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                      topMargin=1.5 * cm, bottomMargin=1.5 * cm).build(story)
    return buffer.getvalue()


# --- Excel -------------------------------------------------------------------

def _append_header(sheet, headings) -> None:
    sheet.append(list(headings))
    for cell in sheet[sheet.max_row]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL


def build_excel(stats: dict, queries: list[Query], filters: ReportFilters, scope: str, generated_by: str) -> bytes:
    workbook = Workbook()

    summary = workbook.active
    summary.title = "Summary"
    summary.append(["Smart Query Routing System - Query Report"])
    summary["A1"].font = Font(bold=True, size=14)
    summary.append(["Scope", scope])
    summary.append(["Period", _period(filters)])
    summary.append(["Generated", f"{datetime.now(PKT):%d %b %Y %H:%M} by {generated_by}"])
    summary.append([])

    _append_header(summary, ["Measure", "Value"])
    summary.append(["Total queries", stats["total_queries"]])
    for status in Status.ALL:
        summary.append([status, stats["status_counts"][status]])
    summary.append(["Resolved (%)", stats["resolution_rate"]])
    avg = stats["avg_response_hours"]
    summary.append(["Average response (hours)", avg if avg is not None else "N/A"])
    summary.append([])

    _append_header(summary, ["Category", "Queries"])
    for row in stats["by_category"]:
        summary.append([row["category"], row["count"]])
    summary.append([])

    _append_header(summary, ["Department", "Total", "Still open"])
    for row in stats["by_department"]:
        summary.append([row["department"], row["total"], row["open"]])

    for column, width in (("A", 32), ("B", 40), ("C", 12)):
        summary.column_dimensions[column].width = width

    sheet = workbook.create_sheet("Queries")
    _append_header(sheet, [heading for heading, _ in QUERY_COLUMNS])
    for query in queries:
        sheet.append(_query_row(query))
        for cell in sheet[sheet.max_row]:
            if cell.data_type == "f":  # text a student typed starting with "=" stays text, never a formula
                cell.data_type = "s"
    for index, (_, width) in enumerate(QUERY_COLUMNS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    daily = workbook.create_sheet("Daily volume")
    _append_header(daily, ["Date", "Queries"])
    for row in stats["daily_volume"]:
        daily.append([row["day"], row["count"]])
    daily.column_dimensions["A"].width = 14

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()