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
from sqlalchemy.exc import OperationalError


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


def check_concurrent_ddl_is_retried():
    """MySQL 1684 must be waited out, not raised.

    This is the second symptom of the same race, seen in production: worker A is
    mid-ALTER and worker B cannot even read the table definition, so it gets
    "was skipped since its definition is being modified by concurrent DDL
    statement" instead of a duplicate-column error. Unlike a duplicate, which is
    final, that one is transient, and killing the worker over it is wrong.

    sqlite has no such error, so it is simulated: the first ALTER attempt raises
    1684 and, in the same moment, the column appears from "another worker" -
    exactly the state a worker losing this race wakes up to. The re-check after
    the wait must then find it and return quietly.
    """
    app = create_app()
    calls = {"n": 0}

    with app.app_context():
        real_begin = db.engine.begin

        class _Boom:
            """Fails like MySQL 1684 on the first attempt, and has the other
            worker finish the job while this one is failing."""

            def __enter__(self):
                calls["n"] += 1
                if calls["n"] == 1:
                    with real_begin() as conn:
                        conn.execute(text("ALTER TABLE sections ADD COLUMN ddl_col VARCHAR(8)"))
                raise OperationalError(
                    "ALTER TABLE sections ADD COLUMN ddl_col VARCHAR(8)",
                    {},
                    Exception(
                        "(1684, \"Table 'aligned'.'sections' was skipped since its "
                        "definition is being modified by concurrent DDL statement\")"
                    ),
                )

            def __exit__(self, *a):
                return False

        db.engine.begin = lambda: _Boom()
        try:
            # Must return quietly: the column exists by the time it looks again.
            _add_column("sections", "ddl_col", "VARCHAR(8)")
        finally:
            db.engine.begin = real_begin

        assert calls["n"] == 1, f"should have stopped after the first retry, attempted {calls['n']}"
        cols = {c["name"] for c in inspect(db.engine).get_columns("sections")}
        assert "ddl_col" in cols, cols
    print("  concurrent DDL retried OK")


def check_concurrent_ddl_gives_up_eventually():
    """If the column never appears, concurrent DDL must not be swallowed forever.

    Retrying without end would boot a worker against a schema missing a column
    the code expects, which is worse than a loud failure.
    """
    app = create_app()

    with app.app_context():
        real_begin = db.engine.begin

        class _AlwaysBoom:
            def __enter__(self):
                raise OperationalError(
                    "ALTER TABLE sections ADD COLUMN never_col VARCHAR(8)",
                    {},
                    Exception("(1684, \"skipped since its definition is being modified by "
                              "concurrent DDL statement\")"),
                )

            def __exit__(self, *a):
                return False

        db.engine.begin = lambda: _AlwaysBoom()
        raised = False
        try:
            _add_column("sections", "never_col", "VARCHAR(8)")
        except Exception:
            raised = True
        finally:
            db.engine.begin = real_begin

        assert raised, "endless concurrent DDL must eventually surface"
    print("  concurrent DDL gives up OK")


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
check_concurrent_ddl_is_retried()
check_concurrent_ddl_gives_up_eventually()
check_real_error_still_raises()
check_missing_table_is_skipped()
check_boot_is_concurrent_safe()
print("migration race OK")
