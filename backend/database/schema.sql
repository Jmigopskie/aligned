
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'student', -- admin | teacher | student
    is_active     BOOLEAN NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lesson_plan_formats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id            INTEGER NOT NULL,
    name                TEXT    NOT NULL,
    is_public           INTEGER NOT NULL DEFAULT 0,
    source_file_path    TEXT,
    template_docx_path  TEXT, -- auto-converted, cached .docx used as the export template when source_file_path is a PDF
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_formats_owner   ON lesson_plan_formats (owner_id);
CREATE INDEX IF NOT EXISTS idx_formats_public  ON lesson_plan_formats (is_public);

CREATE TABLE IF NOT EXISTS format_fields (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    format_id      INTEGER NOT NULL,
    field_key      TEXT    NOT NULL,
    label          TEXT    NOT NULL,
    field_type     TEXT    NOT NULL DEFAULT 'textarea',
    section_group  TEXT,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    is_required    INTEGER NOT NULL DEFAULT 1,
    ai_hint        TEXT,
    anchor_index   INTEGER,

    FOREIGN KEY (format_id) REFERENCES lesson_plan_formats (id) ON DELETE CASCADE,
    UNIQUE (format_id, field_key)
);

CREATE INDEX IF NOT EXISTS idx_fields_format ON format_fields (format_id);
CREATE INDEX IF NOT EXISTS idx_fields_order  ON format_fields (format_id, sort_order);

CREATE TABLE IF NOT EXISTS sections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id    INTEGER NOT NULL,
    name          TEXT    NOT NULL,
    subject       TEXT,
    grade_level   TEXT,
    join_code     TEXT    NOT NULL UNIQUE,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (teacher_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sections_teacher ON sections (teacher_id);

CREATE TABLE IF NOT EXISTS section_memberships (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id  INTEGER NOT NULL,
    student_id  INTEGER NOT NULL,
    joined_at   TEXT    NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (section_id) REFERENCES sections (id) ON DELETE CASCADE,
    FOREIGN KEY (student_id) REFERENCES users (id)    ON DELETE CASCADE,
    UNIQUE (section_id, student_id)
);

CREATE INDEX IF NOT EXISTS idx_memberships_student ON section_memberships (student_id);

CREATE TABLE IF NOT EXISTS lesson_plans (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,
    format_id        INTEGER NOT NULL,
    title            TEXT    NOT NULL,
    subject          TEXT,
    grade_level      TEXT,
    quarter          TEXT,
    date             TEXT,
    field_values     TEXT    NOT NULL DEFAULT '{}',
    generation_mode  TEXT    NOT NULL DEFAULT 'full',
    docx_path        TEXT,

    -- Student -> teacher submission workflow
    section_id       INTEGER,
    status           TEXT    NOT NULL DEFAULT 'draft', -- draft | submitted | reviewed
    teacher_feedback TEXT,
    score            INTEGER, -- 0-100, set by the teacher on review
    submitted_at     TEXT,
    reviewed_at      TEXT,

    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (user_id)    REFERENCES users (id)                  ON DELETE CASCADE,
    FOREIGN KEY (format_id)  REFERENCES lesson_plan_formats (id)    ON DELETE RESTRICT,
    FOREIGN KEY (section_id) REFERENCES sections (id)               ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_plans_user    ON lesson_plans (user_id);
CREATE INDEX IF NOT EXISTS idx_plans_format  ON lesson_plans (format_id);
CREATE INDEX IF NOT EXISTS idx_plans_section ON lesson_plans (section_id);

CREATE TABLE IF NOT EXISTS course_guides (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uploader_id     INTEGER NOT NULL,
    subject         TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    file_path       TEXT    NOT NULL,
    file_hash       VARCHAR(64), -- sha256 of the file bytes, used to dedupe uploads
    extracted_text  TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (uploader_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_course_guides_subject ON course_guides (subject);
CREATE INDEX IF NOT EXISTS idx_course_guides_file_hash ON course_guides (file_hash);

CREATE TABLE IF NOT EXISTS announcements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id   INTEGER NOT NULL,
    title       TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    type        TEXT    NOT NULL DEFAULT 'info', -- info | maintenance | urgent
    is_active   BOOLEAN NOT NULL DEFAULT 1,
    starts_at   TEXT,
    ends_at     TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (author_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_announcements_active ON announcements (is_active);

CREATE TRIGGER IF NOT EXISTS trg_lesson_plans_updated_at
AFTER UPDATE ON lesson_plans
FOR EACH ROW
BEGIN
    UPDATE lesson_plans SET updated_at = datetime('now') WHERE id = OLD.id;
END;
