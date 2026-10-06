import logging
import os
import time
from flask import Flask

from config import Config
from extensions import db, bcrypt, cors


# How hard to try when another gunicorn worker is mid-ALTER. Three short waits
# comfortably covers adding a nullable column, which MySQL does without
# rewriting the table.
_DDL_RETRIES = 3
_DDL_RETRY_DELAY_SECONDS = 0.5


def _add_column(table: str, column: str, ddl_type: str):
    """ALTER TABLE ... ADD COLUMN, tolerating the column already being there.

    The inspect()-then-ALTER pattern below is a race under gunicorn: all three
    workers boot at once, each inspects the table before any of them has
    altered it, so all three decide the column is missing and two then fail
    with "Duplicate column name" — which kills those workers and takes the
    service down with them. Checking first still avoids the pointless ALTER in
    the common case; swallowing a duplicate-column error makes the outcome the
    same whichever order the workers happen to run in.

    Only the duplicate-column error is swallowed. Any other failure is a real
    schema problem and is re-raised.
    """
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import DatabaseError

    inspector = inspect(db.engine)
    if table not in inspector.get_table_names():
        return
    if column in {col["name"] for col in inspector.get_columns(table)}:
        return

    # Two distinct symptoms of the same race, both benign, and both observed in
    # production on this app:
    #
    #   "duplicate column" (MySQL 1060 / SQLite) - another worker already added
    #   it, so there is nothing left to do.
    #
    #   MySQL 1684, "was skipped since its definition is being modified by
    #   concurrent DDL statement" - another worker is mid-ALTER right now and
    #   this one cannot even read the table definition. Unlike a duplicate that
    #   is final, this one is transient: wait and look again, because the column
    #   is about to exist.
    for attempt in range(_DDL_RETRIES):
        try:
            with db.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
            return
        except DatabaseError as exc:
            message = str(exc).lower()
            if "duplicate column" in message:
                return
            if "concurrent ddl" not in message:
                raise
            # Give the worker holding the DDL a moment, then re-check: if it
            # finished the job, this worker has nothing to do either.
            time.sleep(_DDL_RETRY_DELAY_SECONDS)
            if column in {col["name"] for col in inspect(db.engine).get_columns(table)}:
                return
    # Every attempt hit concurrent DDL and the column still is not there. That
    # is not a race any more, so it must surface rather than boot a worker
    # against a schema it expects columns from.
    raise RuntimeError(
        f"Could not add {table}.{column}: still blocked by concurrent DDL after "
        f"{_DDL_RETRIES} attempts."
    )


def _migrate_lesson_plan_columns():
    """db.create_all() only creates brand-new tables, it never alters existing
    ones. Older sqlite databases created before the section/submission
    feature won't have these columns yet, so add them if they're missing."""
    new_columns = {
        "section_id": "INTEGER",
        "status": "TEXT NOT NULL DEFAULT 'draft'",
        "teacher_feedback": "TEXT",
        "score": "INTEGER",
        "submitted_at": "DATETIME",
        "reviewed_at": "DATETIME",
        # A field's plain text lives in field_values; this holds the same
        # field's sanitized rich-text HTML (bold/italic/underline/lists) for
        # any field the teacher styled directly in the live document editor,
        # so export can reproduce that formatting instead of flattening it.
        "rich_field_values": "TEXT",
        # Lets any author share their own plan publicly, independent of the
        # submission workflow above.
        "is_public": "BOOLEAN NOT NULL DEFAULT 0",
        # The inactive generation mode's values; see LessonPlan.mode_values.
        "mode_values": "TEXT",
        # The "Before we start" answers; see LessonPlan.setup_context.
        "setup_context": "TEXT",
        # The teacher's edits to the document body; see LessonPlan.doc_edits.
        "doc_edits": "TEXT",
    }

    for col_name, col_type in new_columns.items():
        _add_column("lesson_plans", col_name, col_type)


def _migrate_user_columns():
    """Add columns needed for admin-managed accounts (is_active), a
    user-uploaded profile picture (avatar_path), and a teacher's dashboard
    banner (banner_path) to databases created before those features existed."""
    _add_column("users", "is_active", "BOOLEAN NOT NULL DEFAULT 1")
    _add_column("users", "avatar_path", "VARCHAR(255)")
    _add_column("users", "banner_path", "VARCHAR(255)")

    # The owl's onboarding tour is for accounts made from now on. Only when the
    # column is first added are the accounts already there marked as done: on
    # every later boot it already exists, so new accounts keep their blank.
    from sqlalchemy import inspect, text
    had_column = "onboarded_at" in {c["name"] for c in inspect(db.engine).get_columns("users")} \
        if "users" in inspect(db.engine).get_table_names() else True
    _add_column("users", "onboarded_at", "DATETIME")
    if not had_column:
        db.session.execute(text("UPDATE users SET onboarded_at = CURRENT_TIMESTAMP WHERE onboarded_at IS NULL"))
        db.session.commit()


def _migrate_course_guide_columns():
    """Add the file_hash column (used to dedupe uploads) to databases
    created before this feature existed, and backfill it for any guides
    whose file is still on disk."""
    import hashlib

    from sqlalchemy import inspect

    if "course_guides" not in inspect(db.engine).get_table_names():
        return

    _add_column("course_guides", "file_hash", "VARCHAR(64)")

    from models.course_guide import CourseGuide

    for guide in CourseGuide.query.filter(
        (CourseGuide.file_hash.is_(None)) | (CourseGuide.file_hash == "")
    ).all():
        if guide.file_path and os.path.exists(guide.file_path):
            with open(guide.file_path, "rb") as f:
                guide.file_hash = hashlib.sha256(f.read()).hexdigest()
    db.session.commit()


def _migrate_format_columns():
    """Add the template_docx_path column (the auto-converted, fillable copy
    of a PDF-sourced reference format) to databases created before this
    feature existed, and the columns that mark a seeded built-in format."""
    _add_column("lesson_plan_formats", "template_docx_path", "VARCHAR(255)")
    _add_column("lesson_plan_formats", "is_builtin", "BOOLEAN NOT NULL DEFAULT 0")
    _add_column("lesson_plan_formats", "builtin_key", "VARCHAR(64)")
    _add_column("lesson_plan_formats", "description", "VARCHAR(255)")
    _add_unique_index("lesson_plan_formats", "uq_lesson_plan_formats_builtin_key", "builtin_key")


def _migrate_course_guide_builtin_columns():
    """Columns describing an official DepEd guide seeded from backend/builtin."""
    for column, ddl_type in (
        ("is_builtin", "BOOLEAN NOT NULL DEFAULT 0"),
        ("builtin_key", "VARCHAR(64)"),
        ("doc_type", "VARCHAR(20)"),
        ("grade_band", "VARCHAR(20)"),
        ("grades", "VARCHAR(20)"),
        ("curriculum", "VARCHAR(20)"),
        ("source_url", "VARCHAR(500)"),
        ("retrieved_at", "DATE"),
    ):
        _add_column("course_guides", column, ddl_type)
    _add_unique_index("course_guides", "uq_course_guides_builtin_key", "builtin_key")


def _add_unique_index(table: str, name: str, column: str):
    """CREATE UNIQUE INDEX, tolerating it already being there.

    Same race as _add_column: every gunicorn worker boots at once, so two can
    both find the index missing. The loser's "already exists" (SQLite) or
    "duplicate key name" (MySQL 1061) means the index is in place, which is all
    this wants. The seeder relies on the index to stop two workers inserting the
    same built-in twice. NULLs never collide, so teachers' rows are unaffected.
    """
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import DatabaseError

    inspector = inspect(db.engine)
    if table not in inspector.get_table_names():
        return
    if name in {ix["name"] for ix in inspector.get_indexes(table)}:
        return
    try:
        with db.engine.begin() as conn:
            conn.execute(text(f"CREATE UNIQUE INDEX {name} ON {table} ({column})"))
    except DatabaseError as exc:
        message = str(exc).lower()
        if "already exists" not in message and "duplicate key name" not in message:
            raise


def _migrate_format_field_columns():
    """Add the anchor_index column (a field's exact position in its
    reference file, set by clicking it in the format builder's document
    editor) to databases created before this feature existed."""
    _add_column("format_fields", "anchor_index", "INTEGER")
    _add_column("format_fields", "role", "VARCHAR(10)")
    # The day names of a weekly field; see FormatField.parts.
    _add_column("format_fields", "parts", "TEXT")


def _migrate_section_columns():
    """Add the is_active column (a section the admin has archived) to databases
    created before bulk archiving existed. Existing sections default to active
    so archiving is opt-in and nothing disappears on upgrade."""
    _add_column("sections", "is_active", "BOOLEAN NOT NULL DEFAULT 1")


def _migrate_announcement_columns():
    """Add the section_id column (lets a teacher scope an announcement to
    one of their own sections instead of everyone) to databases created
    before this feature existed."""
    _add_column("announcements", "section_id", "INTEGER")
    # An attached tutorial video.
    _add_column("announcements", "video_path", "VARCHAR(500)")
    _add_column("announcements", "video_name", "VARCHAR(255)")
    _add_column("announcements", "video_size", "BIGINT")


def _ensure_default_admin(app):
    """Create a bootstrap admin account if no admin exists yet, so there's
    always a way in to start creating teacher and student accounts."""
    from models.user import User

    if User.query.filter_by(role="admin").first():
        return

    admin = User(
        full_name=app.config["DEFAULT_ADMIN_NAME"],
        email=app.config["DEFAULT_ADMIN_EMAIL"].lower(),
        role="admin",
    )
    admin.set_password(app.config["DEFAULT_ADMIN_PASSWORD"])
    db.session.add(admin)
    db.session.commit()
    app.logger.warning(
        "No admin account existed — created default admin '%s'. "
        "Log in and change this password right away.",
        app.config["DEFAULT_ADMIN_EMAIL"],
    )


def create_app():
    # Without this, INFO records (AI token usage and timing) are dropped under
    # gunicorn, whose own logging setup leaves the root logger at WARNING.
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    else:
        logging.getLogger("services").setLevel(logging.INFO)

    app = Flask(__name__, static_folder="../frontend", static_url_path="")
    app.config.from_object(Config)

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["GENERATED_FOLDER"], exist_ok=True)

    db.init_app(app)
    bcrypt.init_app(app)
    cors.init_app(app, supports_credentials=True, origins=[app.config["FRONTEND_ORIGIN"]])

    from routes.auth_routes import auth_bp
    from routes.format_routes import format_bp
    from routes.generate_routes import generate_bp
    from routes.course_guide_routes import course_guide_bp
    from routes.section_routes import section_bp
    from routes.admin_routes import admin_bp
    from routes.announcement_routes import announcement_bp
    from routes.notification_routes import notification_bp
    from routes.image_routes import image_bp

    app.register_blueprint(auth_bp, url_prefix="/api")
    app.register_blueprint(format_bp, url_prefix="/api")
    app.register_blueprint(generate_bp, url_prefix="/api")
    app.register_blueprint(course_guide_bp, url_prefix="/api")
    app.register_blueprint(section_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/api")
    app.register_blueprint(announcement_bp, url_prefix="/api")
    app.register_blueprint(notification_bp, url_prefix="/api")
    app.register_blueprint(image_bp, url_prefix="/api")

    with app.app_context():
        # Import models so db.create_all() knows about every table,
        # including the newer sections / section_memberships / announcements /
        # notifications tables.
        from models import user, format, lesson_plan, course_guide, section, announcement, notification  # noqa: F401

        db.create_all()
        _migrate_lesson_plan_columns()
        _migrate_user_columns()
        # Before _migrate_course_guide_columns: its backfill queries the full
        # CourseGuide model, which fails on a database missing these columns.
        _migrate_course_guide_builtin_columns()
        _migrate_course_guide_columns()
        _migrate_format_columns()
        _migrate_format_field_columns()
        _migrate_announcement_columns()
        _migrate_section_columns()
        _ensure_default_admin(app)

        from services.builtins import seed_builtins
        seed_builtins()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    return app
