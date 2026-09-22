"""Self-check that the schema migrations survive several workers booting at once.

This is the bug that took the live site down: gunicorn runs three workers, all
three call create_app() simultaneously, and the migrations used to inspect the
table and then ALTER it. All three would see a column missing, all three would
issue the ALTER, and the two that lost the race died with "Duplicate column
name" — which killed the workers and the service with them.

_add_column() now swallows exactly that error and nothing else, so the outcome
is the same whichever order the workers run in. This runs the migration
concurrently against one shared database to hold that property in place.

Run it directly: `venv/Scripts/python test_migration_race.py`.
"""
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# A real file rather than ":memory:", so every thread genuinely shares one
# database the way the workers share MySQL.
_db_path = os.path.join(tempfile.mkdtemp(), "race.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

from app import _add_column, create_app
from extensions import db
from sqlalchemy import inspect, text


def check_concurrent_add_column():
    """Several threads adding the same column at once: one wins, the rest must
    return quietly instead of raising."""
    app = create_app()
    errors = []
    barrier = threading.Barrier(6)

    def worker():
        try:
            # Every thread waits here, so they all attempt the ALTER together
            # rather than politely one after another.
            barrier.wait()
            with app.app_context():
                _add_column("sections", "race_col", "VARCHAR(16)")
        except Exception as exc:  # noqa: BLE001 - the whole point is to catch any
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent _add_column raised: {errors[:3]}"

    with app.app_context():
        cols = {c["name"] for c in inspect(db.engine).get_columns("sections")}
        assert "race_col" in cols, cols
    print("  concurrent add_column OK")


def check_idempotent():
    """Running a migration twice must be a no-op the second time, which is what
    every restart after the first one does."""
    app = create_app()
    with app.app_context():
        _add_column("sections", "twice_col", "VARCHAR(8)")
        _add_column("sections", "twice_col", "VARCHAR(8)")
        cols = [c["name"] for c in inspect(db.engine).get_columns("sections")]
        assert cols.count("twice_col") == 1, cols
    print("  idempotent OK")


def check_real_error_still_raises():
    """Only the duplicate-column case is swallowed. A genuine schema error must
    still surface, or a broken migration would fail silently."""
    app = create_app()
    with app.app_context():
        raised = False
        try:
            # Deliberately invalid DDL for the column type.
            _add_column("sections", "bad_col", "NOT A REAL TYPE (((")
        except Exception:
            raised = True
        assert raised, "an invalid column definition must still raise"
    print("  real errors still raise OK")


def check_missing_table_is_skipped():
    """A table that doesn't exist yet is skipped rather than erroring, which is
    what happens on a brand-new database before create_all() has run."""
    app = create_app()
    with app.app_context():
        _add_column("no_such_table", "whatever", "INTEGER")
    print("  missing table skipped OK")


def check_boot_is_concurrent_safe():
    """The whole of create_app(), migrations and all, run from several threads
    at once — the closest thing to what gunicorn actually does."""
    errors = []
    barrier = threading.Barrier(3)

    def boot():
        try:
            barrier.wait()
            create_app()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=boot) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent create_app() raised: {errors[:3]}"
    print("  concurrent create_app OK")


check_concurrent_add_column()
check_idempotent()
check_real_error_still_raises()
check_missing_table_is_skipped()
check_boot_is_concurrent_safe()
print("migration race OK")
