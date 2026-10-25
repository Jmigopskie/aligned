"""Self-check: a format with no usable reference file still shows as a
document (a plain page built from its fields), never as a bare field form.

Run it directly: `python test_plain_document.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from app import create_app
from extensions import db
from models.format import FormatField, LessonPlanFormat
from models.user import User


def main():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        teacher = User(full_name="Tina Teacher", email="tina.plain@example.test", role="teacher")
        teacher.set_password("password123")
        db.session.add(teacher)
        db.session.commit()
        fmt = LessonPlanFormat(name="TUP <Format>", owner_id=teacher.id)
        db.session.add(fmt)
        db.session.flush()
        db.session.add_all([
            FormatField(format_id=fmt.id, field_key="objectives", label="Lesson Objectives", sort_order=0),
            FormatField(format_id=fmt.id, field_key="days", label="Activities", field_type="weekly",
                        parts='["Monday", "Tuesday"]', sort_order=1),
        ])
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = teacher.id

        res = client.get(f"/api/formats/{fmt.id}/template-html")
        data = res.get_json()
        assert res.status_code == 200 and data["plain"] is True, data
        html = data["html"]
        assert 'class="lp-doc lp-doc-plain"' in html and "TUP &lt;Format&gt;" in html, html
        assert html.index("Lesson Objectives") < html.index('data-field-key="objectives"') < html.index("Activities")
        assert 'data-field-key="days" data-part="0"' in html and 'data-field-key="days" data-part="1"' in html, html
        assert data["matched_fields"] == ["objectives", "days"] and data["unmatched_fields"] == [], data
    print("plain document OK")


if __name__ == "__main__":
    main()
