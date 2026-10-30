-- =============================================================================
-- Smart Query Routing & Email Automation System
-- PostgreSQL schema — run in Supabase → SQL Editor
--
-- This script recreates every table from scratch and DELETES existing data.
-- Run it only on a development database.
-- =============================================================================

DROP TABLE IF EXISTS
    audit_log, escalations, notifications, replies, routes,
    query_status_history, queries, routing_rules, courses, users, departments
CASCADE;
DROP FUNCTION IF EXISTS prevent_audit_log_changes CASCADE;


-- -----------------------------------------------------------------------------
-- Departments
-- Academic departments own courses, instructors and an HOD.
-- Exam, Registrar, Finance and IT are service desks (exactly one of each).
-- -----------------------------------------------------------------------------
CREATE TABLE departments (
    department_id  SERIAL       PRIMARY KEY,
    name           VARCHAR(100) NOT NULL UNIQUE,
    type           VARCHAR(30)  NOT NULL,
    description    TEXT,

    CONSTRAINT chk_departments_type
        CHECK (type IN ('Academic', 'Exam', 'Registrar', 'Finance', 'IT'))
);

CREATE UNIQUE INDEX uq_departments_service_type
    ON departments (type) WHERE type <> 'Academic';


-- -----------------------------------------------------------------------------
-- Users — all five roles. No passwords: identity comes from Google OAuth2.
-- Users are deactivated, never deleted, so their history stays intact.
-- -----------------------------------------------------------------------------
CREATE TABLE users (
    user_id             SERIAL       PRIMARY KEY,
    name                VARCHAR(100) NOT NULL,
    email               VARCHAR(150) NOT NULL UNIQUE,
    role                VARCHAR(20)  NOT NULL DEFAULT 'Student',
    department_id       INTEGER      REFERENCES departments (department_id),
    oauth_provider      VARCHAR(30)  NOT NULL DEFAULT 'google',
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
    leave_from          TIMESTAMPTZ,
    leave_until         TIMESTAMPTZ,
    auto_reply_message  TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT chk_users_role
        CHECK (role IN ('Student', 'Instructor', 'HOD', 'DepartmentStaff', 'Admin')),
    -- Staff must belong to a department; students and admins do not need one.
    CONSTRAINT chk_users_staff_department
        CHECK (role IN ('Student', 'Admin') OR department_id IS NOT NULL),
    -- A leave period is either fully set or not set at all.
    CONSTRAINT chk_users_leave_period
        CHECK ((leave_from IS NULL) = (leave_until IS NULL)
               AND (leave_until IS NULL OR leave_until > leave_from))
);


-- -----------------------------------------------------------------------------
-- Courses — lets Course/Attendance queries reach the right instructor.
-- -----------------------------------------------------------------------------
CREATE TABLE courses (
    course_id      SERIAL       PRIMARY KEY,
    code           VARCHAR(12)  NOT NULL UNIQUE,      -- e.g. CS619
    title          VARCHAR(150) NOT NULL,
    department_id  INTEGER      NOT NULL REFERENCES departments (department_id),
    instructor_id  INTEGER      REFERENCES users (user_id)
);


-- -----------------------------------------------------------------------------
-- Routing rules — which department and role handle each AI category.
-- Editable by the Admin at runtime.
-- -----------------------------------------------------------------------------
CREATE TABLE routing_rules (
    category       VARCHAR(30)  PRIMARY KEY,
    department_id  INTEGER      NOT NULL REFERENCES departments (department_id),
    target_role    VARCHAR(20)  NOT NULL,
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT chk_routing_rules_category
        CHECK (category IN ('Fee', 'Result', 'Course', 'Attendance', 'Degree', 'IT', 'General')),
    CONSTRAINT chk_routing_rules_role
        CHECK (target_role IN ('Instructor', 'DepartmentStaff'))
);


-- -----------------------------------------------------------------------------
-- Queries — the central entity.
-- updated_at moves forward on every change; the SLA check measures from it.
-- -----------------------------------------------------------------------------
CREATE TABLE queries (
    query_id        SERIAL       PRIMARY KEY,
    reference_code  VARCHAR(20)  NOT NULL UNIQUE,
    student_id      INTEGER      NOT NULL REFERENCES users (user_id),
    department_id   INTEGER      REFERENCES departments (department_id),
    course_id       INTEGER      REFERENCES courses (course_id),
    assigned_to     INTEGER      REFERENCES users (user_id),
    category        VARCHAR(30),
    intent          VARCHAR(100),                       -- the AI's short summary, shown to staff
    channel         VARCHAR(20)  NOT NULL,
    query_text      TEXT         NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'Pending',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT chk_queries_category
        CHECK (category IN ('Fee', 'Result', 'Course', 'Attendance', 'Degree', 'IT', 'General')),
    CONSTRAINT chk_queries_channel
        CHECK (channel IN ('web', 'email')),
    CONSTRAINT chk_queries_status
        CHECK (status IN ('Pending', 'In Progress', 'Needs More Info', 'Escalated', 'Resolved'))
);


-- -----------------------------------------------------------------------------
-- Status history — one row per status change, shown to the student (FR-06).
-- -----------------------------------------------------------------------------
CREATE TABLE query_status_history (
    history_id  SERIAL       PRIMARY KEY,
    query_id    INTEGER      NOT NULL REFERENCES queries (query_id) ON DELETE CASCADE,
    old_status  VARCHAR(20),
    new_status  VARCHAR(20)  NOT NULL,
    changed_by  INTEGER      REFERENCES users (user_id),   -- NULL = system
    note        VARCHAR(255),
    changed_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);


-- -----------------------------------------------------------------------------
-- Routes — every routing decision, including manual overrides.
-- -----------------------------------------------------------------------------
CREATE TABLE routes (
    route_id        SERIAL        PRIMARY KEY,
    query_id        INTEGER       NOT NULL REFERENCES queries (query_id) ON DELETE CASCADE,
    routed_to_role  VARCHAR(20)   NOT NULL,
    department_id   INTEGER       REFERENCES departments (department_id),
    assigned_to     INTEGER       REFERENCES users (user_id),
    ai_confidence   NUMERIC(3, 2),
    method          VARCHAR(20)   NOT NULL,
    routed_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT chk_routes_role
        CHECK (routed_to_role IN ('Instructor', 'HOD', 'DepartmentStaff', 'Admin')),
    CONSTRAINT chk_routes_confidence
        CHECK (ai_confidence IS NULL OR ai_confidence BETWEEN 0 AND 1),
    CONSTRAINT chk_routes_method
        CHECK (method IN ('gemini', 'claude', 'keyword', 'manual'))
);


-- -----------------------------------------------------------------------------
-- Replies — the AI draft and the human-approved final text.
-- A reply can only be 'Sent' once a staff member has written/approved it.
-- -----------------------------------------------------------------------------
CREATE TABLE replies (
    reply_id       SERIAL       PRIMARY KEY,
    query_id       INTEGER      NOT NULL REFERENCES queries (query_id) ON DELETE CASCADE,
    responder_id   INTEGER      REFERENCES users (user_id),   -- NULL while still a draft
    ai_draft_text  TEXT,
    final_text     TEXT,
    status         VARCHAR(20)  NOT NULL DEFAULT 'Draft',
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    sent_at        TIMESTAMPTZ,

    CONSTRAINT chk_replies_status
        CHECK (status IN ('Draft', 'Sent')),
    CONSTRAINT chk_replies_human_approval
        CHECK (status <> 'Sent'
               OR (final_text IS NOT NULL AND responder_id IS NOT NULL AND sent_at IS NOT NULL))
);


-- -----------------------------------------------------------------------------
-- Notifications — dashboard and email alerts. query_id is NULL for announcements.
-- -----------------------------------------------------------------------------
CREATE TABLE notifications (
    notification_id  SERIAL        PRIMARY KEY,
    user_id          INTEGER       NOT NULL REFERENCES users (user_id),
    query_id         INTEGER       REFERENCES queries (query_id) ON DELETE CASCADE,
    kind             VARCHAR(20)   NOT NULL DEFAULT 'update',
    channel          VARCHAR(20)   NOT NULL,
    title            VARCHAR(150),
    message          TEXT          NOT NULL,
    is_read          BOOLEAN       NOT NULL DEFAULT FALSE,
    sent_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT chk_notifications_kind
        CHECK (kind IN ('update', 'announcement')),
    CONSTRAINT chk_notifications_channel
        CHECK (channel IN ('dashboard', 'email'))
);


-- -----------------------------------------------------------------------------
-- Escalations — manual escalations and automatic 24-hour SLA escalations.
-- -----------------------------------------------------------------------------
CREATE TABLE escalations (
    escalation_id  SERIAL        PRIMARY KEY,
    query_id       INTEGER       NOT NULL REFERENCES queries (query_id) ON DELETE CASCADE,
    escalated_by   INTEGER       REFERENCES users (user_id),   -- NULL = automatic SLA
    escalated_to   INTEGER       NOT NULL REFERENCES users (user_id),
    reason         VARCHAR(255),
    escalated_at   TIMESTAMPTZ   NOT NULL DEFAULT now()
);


-- -----------------------------------------------------------------------------
-- Audit log — append-only activity trail (FR-14).
-- user_id is NULL for actions performed by the system itself.
-- -----------------------------------------------------------------------------
CREATE TABLE audit_log (
    log_id     SERIAL        PRIMARY KEY,
    user_id    INTEGER       REFERENCES users (user_id),
    query_id   INTEGER       REFERENCES queries (query_id),
    action     VARCHAR(100)  NOT NULL,
    details    TEXT,
    timestamp  TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE FUNCTION prevent_audit_log_changes() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_log_append_only
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_changes();


-- -----------------------------------------------------------------------------
-- Indexes for the most frequent lookups (dashboards, inboxes, SLA check)
-- -----------------------------------------------------------------------------
CREATE INDEX idx_queries_status_department ON queries (status, department_id);
CREATE INDEX idx_queries_student           ON queries (student_id);
CREATE INDEX idx_queries_assigned_to       ON queries (assigned_to);
CREATE INDEX idx_queries_updated_at        ON queries (updated_at);
CREATE INDEX idx_history_query             ON query_status_history (query_id);
CREATE INDEX idx_routes_query              ON routes (query_id);
CREATE INDEX idx_replies_query             ON replies (query_id);
CREATE INDEX idx_notifications_user_unread ON notifications (user_id, is_read);
CREATE INDEX idx_audit_log_timestamp       ON audit_log ("timestamp" DESC);


-- -----------------------------------------------------------------------------
-- Supabase exposes the public schema through its REST API. The backend
-- connects directly as the table owner, so enabling RLS without any policy
-- closes that public door without affecting the application.
-- -----------------------------------------------------------------------------
ALTER TABLE departments          ENABLE ROW LEVEL SECURITY;
ALTER TABLE users                ENABLE ROW LEVEL SECURITY;
ALTER TABLE courses              ENABLE ROW LEVEL SECURITY;
ALTER TABLE routing_rules        ENABLE ROW LEVEL SECURITY;
ALTER TABLE queries              ENABLE ROW LEVEL SECURITY;
ALTER TABLE query_status_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE routes               ENABLE ROW LEVEL SECURITY;
ALTER TABLE replies              ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications        ENABLE ROW LEVEL SECURITY;
ALTER TABLE escalations          ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log            ENABLE ROW LEVEL SECURITY;


-- -----------------------------------------------------------------------------
-- Seed data
-- -----------------------------------------------------------------------------
INSERT INTO departments (name, type, description) VALUES
    ('Computer Science',       'Academic',  'Courses, attendance, instructors and HOD'),
    ('Examination Department', 'Exam',      'Results, rechecking and DMC corrections'),
    ('Registrar Office',       'Registrar', 'Degree verification, transcripts and enrolment'),
    ('Finance Department',     'Finance',   'Fee challans, scholarships and payments'),
    ('IT Helpdesk',            'IT',        'LMS, portal, email and lab issues');

INSERT INTO routing_rules (category, department_id, target_role)
SELECT r.category, d.department_id, r.target_role
FROM (VALUES
    ('Fee',        'Finance',   'DepartmentStaff'),
    ('Result',     'Exam',      'DepartmentStaff'),
    ('Course',     'Academic',  'Instructor'),
    ('Attendance', 'Academic',  'Instructor'),
    ('Degree',     'Registrar', 'DepartmentStaff'),
    ('IT',         'IT',        'DepartmentStaff'),
    ('General',    'Registrar', 'DepartmentStaff')
) AS r (category, dept_type, target_role)
JOIN departments d ON d.type = r.dept_type;

INSERT INTO courses (code, title, department_id)
SELECT c.code, c.title, d.department_id
FROM (VALUES
    ('CS101', 'Introduction to Computing'),
    ('CS201', 'Introduction to Programming'),
    ('CS619', 'Final Year Project')
) AS c (code, title)
JOIN departments d ON d.name = 'Computer Science';