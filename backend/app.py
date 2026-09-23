import logging
import os
from flask import Flask

from config import Config
from extensions import db, bcrypt, cors


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

    try:
        with db.engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
    except DatabaseError as exc:
        message = str(exc).lower()
        # MySQL: (1060, "Duplicate column name 'x'"). SQLite: "duplicate column
        # name: x". Either means another worker won the race, which is fine.
        if "duplicate column" in message:
            return
        raise


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
    feature existed."""
    _add_column("lesson_plan_formats", "template_docx_path", "VARCHAR(255)")


def _migrate_format_field_columns():
    """Add the anchor_index column (a field's exact position in its
    reference file, set by clicking it in the format builder's document
    editor) to databases created before this feature existed."""
    _add_column("format_fields", "anchor_index", "INTEGER")
    _add_column("format_fields", "role", "VARCHAR(10)")


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

    app.register_blueprint(auth_bp, url_prefix="/api")
    app.register_blueprint(format_bp, url_prefix="/api")
    app.register_blueprint(generate_bp, url_prefix="/api")
    app.register_blueprint(course_guide_bp, url_prefix="/api")
    app.register_blueprint(section_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/api")
    app.register_blueprint(announcement_bp, url_prefix="/api")
    app.register_blueprint(notification_bp, url_prefix="/api")

    with app.app_context():
        # Import models so db.create_all() knows about every table,
        # including the newer sections / section_memberships / announcements /
        # notifications tables.
        from models import user, format, lesson_plan, course_guide, section, announcement, notification  # noqa: F401

        db.create_all()
        _migrate_lesson_plan_columns()
        _migrate_user_columns()
        _migrate_course_guide_columns()
        _migrate_format_columns()
        _migrate_format_field_columns()
        _migrate_announcement_columns()
        _migrate_section_columns()
        _ensure_default_admin(app)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    return app
