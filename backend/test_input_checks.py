"""Self-check for the server side of input checks (Batch 2): a value the
database refuses (too long for its column on MySQL, the wrong kind) or a
duplicate comes back as a clear 400/409 message, never a crash page; any other
failure on an /api route is JSON too.

Run it directly: `python test_input_checks.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from sqlalchemy.exc import DataError, IntegrityError  # noqa: E402

from app import create_app  # noqa: E402


def main():
    app = create_app()
    app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)

    def too_long():
        raise DataError("INSERT ...", {}, Exception("(1406, \"Data too long for column 'name' at row 1\")"))

    def duplicate():
        raise IntegrityError("INSERT ...", {}, Exception("Duplicate entry"))

    def broken():
        raise RuntimeError("boom")

    app.add_url_rule("/api/_t/too-long", view_func=too_long)
    app.add_url_rule("/api/_t/duplicate", view_func=duplicate)
    app.add_url_rule("/api/_t/broken", view_func=broken)
    client = app.test_client()

    res = client.get("/api/_t/too-long")
    assert res.status_code == 400 and "too long" in res.get_json()["message"], (res.status_code, res.data[:200])
    res = client.get("/api/_t/duplicate")
    assert res.status_code == 409 and res.get_json()["status"] == "error", res.data[:200]
    res = client.get("/api/_t/broken")
    assert res.status_code == 500 and res.is_json and "try again" in res.get_json()["message"], res.data[:200]
    assert client.get("/api/_t/nothing-here").get_json()["status"] == "error"
    print("input checks OK")


if __name__ == "__main__":
    main()
