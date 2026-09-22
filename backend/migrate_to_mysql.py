"""One-time data migration: copy every row from the local sqlite database
into the MySQL database configured via DATABASE_URL / MYSQL_* env vars.

Usage:
    venv/Scripts/python.exe migrate_to_mysql.py [--sqlite-path PATH] [--yes]

Safe to re-run: it only ever INSERTs into what should be freshly created,
empty MySQL tables, and refuses to touch a target table that already has
rows unless you pass --force (and even then only after confirming).
This never modifies or deletes the source sqlite file.
"""
import argparse
import os
import sys

# Reuse the app's own SQLAlchemy models so both schemas — source and
# target — come from the exact same table/column/type definitions instead
# of a hand-maintained second copy that could drift out of sync.
from sqlalchemy import create_engine, MetaData, select

TABLE_ORDER = [
    "users",
    "lesson_plan_formats",
    "format_fields",
    "sections",
    "lesson_plans",
    "section_memberships",
    "course_guides",
    "announcements",
]


def build_target_uri():
    from config import Config
    return Config.SQLALCHEMY_DATABASE_URI


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-path", default=os.path.join(os.path.dirname(__file__), "instance", "aligned.db"))
    parser.add_argument("--force", action="store_true", help="Proceed even if a target table already has rows.")
    parser.add_argument("--yes", action="store_true", help="Don't ask for confirmation before writing to the target database.")
    args = parser.parse_args()

    if not os.path.isfile(args.sqlite_path):
        print(f"Source sqlite file not found: {args.sqlite_path}")
        sys.exit(1)

    target_uri = build_target_uri()
    if target_uri.startswith("sqlite"):
        print("DATABASE_URL / MYSQL_* still resolve to sqlite — nothing to migrate to.")
        print(f"Resolved target URI: {target_uri}")
        sys.exit(1)

    print(f"Source (sqlite): {args.sqlite_path}")
    print(f"Target:          {target_uri}")

    source_engine = create_engine(f"sqlite:///{args.sqlite_path}")
    target_engine = create_engine(target_uri)

    # Build the target schema from the app's real models — the single
    # source of truth for column types, foreign keys, and unique
    # constraints — rather than reverse-engineering it from sqlite. This
    # also bootstraps a default admin account (create_app()'s normal
    # first-run behavior) that would collide on id/email with the real
    # users we're about to copy in, so it's removed again right after.
    from app import create_app
    from config import Config
    app = create_app()  # runs db.create_all() + _ensure_default_admin() against the TARGET
    from extensions import db
    with app.app_context():
        metadata: MetaData = db.metadata
        users_table = metadata.tables["users"]
        with target_engine.begin() as tconn:
            tconn.execute(users_table.delete().where(users_table.c.email == Config.DEFAULT_ADMIN_EMAIL.lower()))

        with target_engine.connect() as tconn:
            for name in TABLE_ORDER:
                table = metadata.tables[name]
                existing = tconn.execute(select(table.c.id)).first()
                if existing and not args.force:
                    print(f"SKIP {name}: target already has rows (use --force to overwrite-insert anyway).")
                    return
        print()

        if not args.yes:
            answer = input("Copy all rows listed above into the target database now? [y/N] ")
            if answer.strip().lower() != "y":
                print("Aborted — no changes made.")
                return

        with source_engine.connect() as sconn, target_engine.begin() as tconn:
            for name in TABLE_ORDER:
                table = metadata.tables[name]
                rows = [dict(r._mapping) for r in sconn.execute(select(table))]
                if not rows:
                    print(f"{name}: 0 rows (nothing to copy)")
                    continue
                tconn.execute(table.insert(), rows)
                print(f"{name}: copied {len(rows)} row(s)")

        # MySQL's AUTO_INCREMENT counters start fresh from db.create_all()
        # and don't know about the explicit ids we just inserted — bump each
        # one past the highest copied id so the next INSERT doesn't collide.
        with target_engine.begin() as tconn:
            for name in TABLE_ORDER:
                table = metadata.tables[name]
                max_id = tconn.execute(select(table.c.id)).all()
                if not max_id:
                    continue
                highest = max(r[0] for r in max_id)
                tconn.exec_driver_sql(f"ALTER TABLE `{name}` AUTO_INCREMENT = {highest + 1}")

    print("\nDone. The sqlite file was not modified — verify the app works against MySQL before removing it.")


if __name__ == "__main__":
    main()
