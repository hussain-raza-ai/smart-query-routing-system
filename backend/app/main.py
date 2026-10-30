"""
Application entry point.

Creates the FastAPI app, applies cross-cutting settings (CORS, error
handling), registers the routers and serves the frontend, which lives in
its own folder next to the backend (smart-query-routing-system/frontend).

Run locally (from the backend folder) with:
    python -m uvicorn app.main:app --reload --reload-dir app --port 8001
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.routers import admin, auth, automation, notifications, queries, users
from app.services.query_service import WorkflowError

# backend/app/main.py -> parents[2] is the project folder that holds frontend/
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(
    title="Smart Query Routing & Email Automation System",
    description="University Intelligent Communication Hub - CS619 Final Year Project",
    version="2.0.0",
)

# The frontend is normally served by this same server. If it is hosted elsewhere
# (e.g. Vercel), list its address in CORS_ORIGINS so the browser may call the API.
if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.exception_handler(WorkflowError)
async def handle_workflow_error(request: Request, exc: WorkflowError):
    """A broken business rule (e.g. replying to a resolved query) becomes a clear 409 response."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})


app.include_router(auth.router)
app.include_router(queries.router)
app.include_router(queries.assistant_router)
app.include_router(users.router)
app.include_router(notifications.router)
app.include_router(admin.router)
app.include_router(automation.router)

# The dashboard's scripts: core.js, student.js, staff.js, admin.js and app.js.
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="frontend")


@app.get("/health", tags=["System"])
def health_check():
    """Lightweight endpoint for uptime monitoring and hosting health checks."""
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
@app.get("/dashboard", include_in_schema=False)
def serve_dashboard():
    return FileResponse(FRONTEND_DIR / "index.html")