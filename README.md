# Smart Query Routing & Email Automation System

University Intelligent Communication Hub: CS619 Final Year Project, Virtual University of Pakistan.
Supervisor: Saima Jamil · Group: S26PROJECT6D3F7 · Student: BC210411367

Students describe a problem in their own words, through a web form or by email. The system
classifies it with AI, sends it to the right office, drafts a reply that a staff member reviews
and approves, tracks it until it is resolved, and escalates anything left waiting for 24 hours.

## Features

- Google sign-in with five roles (Student, Instructor, HOD, Department Staff, Admin) and record-level access control
- AI classification into seven categories with a short AI summary of each query
  (Gemini, with Claude and keyword fallbacks)
- Rule-based routing to the least busy available person, with instructor leave and auto-reply
- AI-drafted replies that reach the student only after a staff member approves them
- Three channels: web form, email (Gmail through n8n) and an AI FAQ assistant
- Status timeline, "more information needed" loop, escalation, reassignment and ownership
- Automatic 24-hour SLA escalation, run hourly by n8n
- Daily summary email to each HOD (their department) and to Admins (whole university)
- Analytics dashboard, PDF and Excel reports, announcements, and an append-only audit log with CSV export
- Rate limiting on query submission and the AI assistant

## Technology

FastAPI · SQLAlchemy · PostgreSQL (Supabase) · LangChain with Google Gemini and Anthropic Claude ·
n8n with the Gmail API · React · Tailwind CSS · Chart.js

## Project structure

    backend/
        app/
            core/         settings, constants, security, rate limiting
            models/       database models
            routers/      API endpoints: auth, queries, users, notifications, admin, automation
            schemas/      request and response shapes
            services/     AI, routing, query workflow, notifications, analytics, reports
            main.py       creates the app, registers the routers and serves the frontend
        database/schema.sql
        scripts/          demo data and manual test helpers
    frontend/
        index.html        loads React, Tailwind CSS, Chart.js and the dashboard scripts
        js/               dashboard screens: core, student, staff, admin, app
    n8n/                  workflows: email delivery, hourly SLA check, email queries, daily summary

The backend serves the frontend by default. To host the frontend separately (for example on
Vercel), set `window.API_BASE_URL` in `frontend/index.html` to the backend's address and add
the frontend's address to `CORS_ORIGINS` in the backend's `.env`.

## Running locally

1. Create the database by running `backend/database/schema.sql` in the Supabase SQL editor.
2. In `backend/`, create a virtual environment and install the packages:
   `python -m venv venv`, then `.\venv\Scripts\activate`, then `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in every value.
4. Add the demo staff with `python -m scripts.seed_demo_users`, and optionally two weeks of
   sample queries with `python -m scripts.seed_demo_queries`.
5. Start the server: `python -m uvicorn app.main:app --reload --reload-dir app --port 8001`
6. Open `http://127.0.0.1:8001` for the dashboard, or `http://127.0.0.1:8001/docs` for the API.
7. In n8n, import the four workflows from `n8n/`, connect the Gmail and header-auth
   credentials, set each workflow's timezone to Asia/Karachi, and activate them.