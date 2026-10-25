"""Self-check for the teacher's field setup in the format builder: review the
fields AlignED detected (rename, Guided, Locked, remove) and place missing
ones by hand at a line of the document. Locked fields are never generated;
Guided follows the teacher's picks; editing the document afterwards keeps the
teacher's fields, shifting their positions instead of re-detecting them.

Run it directly: `python test_field_setup.py`.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

import docx

from app import create_app
from extensions import db
from models.format import LessonPlanFormat, FormatField
from models.user import User
from routes.generate_routes import _generatable_keys
from services import docx_service


def make_doc(path):
    d = docx.Document()
    d.add_paragraph("SCHOOL LESSON PLAN")          # 0
    d.add_paragraph("Name:")                       # 1
    t = d.add_table(rows=3, cols=2)
    t.cell(0, 0).text = "Topic"                    # 2, blank cell 3
    t.cell(1, 0).text = "Objectives"               # 4, blank cell 5
    t.cell(2, 0).text = "Notes"                    # 6
    t.cell(2, 1).text = "Bring a notebook."        # 7
    d.add_paragraph("Remarks:")                    # 8
    d.save(path)


def main():
    upload = tempfile.mkdtemp()
    app = create_app()
    app.config.update(TESTING=True, UPLOAD_FOLDER=upload)
    from config import Config
    Config.UPLOAD_FOLDER = upload

    with app.app_context():
        teacher = User(full_name="Tina Teacher", email="tina@example.test", role="teacher")
        other = User(full_name="Oscar Other", email="oscar@example.test", role="teacher")
        student = User(full_name="Sam Student", email="sam@example.test", role="student")
        for u in (teacher, other, student):
            u.set_password("password123")
        db.session.add_all([teacher, other, student])
        db.session.commit()

        path = os.path.join(upload, "format_test.docx")
        make_doc(path)
        fmt = LessonPlanFormat(name="Test DLP", owner_id=teacher.id, source_file_path=path)
        db.session.add(fmt)
        db.session.flush()
        # What detection found: a "Name" line, Topic and Objectives cells.
        db.session.add_all([
            FormatField(format_id=fmt.id, field_key="name", label="Name", field_type="text", anchor_index=1, sort_order=0),
            FormatField(format_id=fmt.id, field_key="topic", label="Topic", field_type="textarea", anchor_index=2, sort_order=1),
            FormatField(format_id=fmt.id, field_key="objectives", label="Objectives", field_type="textarea", anchor_index=4, sort_order=2),
        ])
        db.session.commit()
        fid = fmt.id
        client = app.test_client()

        def login(user):
            with client.session_transaction() as sess:
                sess["user_id"] = user.id

        def setup(fields):
            return client.put(f"/api/formats/{fid}/field-setup", json={"fields": fields})

        wanted = [
            {"field_key": "name", "label": "Teacher's name", "anchor_index": 1, "guided": False, "locked": False},
            {"field_key": "topic", "label": "Topic", "anchor_index": 2, "guided": True, "locked": False},
            {"label": "Remarks", "anchor_index": 8, "guided": True, "locked": True},  # placed by hand
        ]

        # --- Only the format's own teacher ---
        login(student)
        assert setup(wanted).status_code == 403
        login(other)
        assert setup(wanted).status_code == 403
        print("  only the owner OK")

        # --- Bad lists are refused, nothing changes ---
        login(teacher)
        assert setup([{"label": "X", "anchor_index": 99, "guided": False, "locked": False}]).status_code == 400
        assert setup([{"label": "A", "anchor_index": 1}, {"label": "B", "anchor_index": 1}]).status_code == 400
        assert setup([{"label": "  ", "anchor_index": 1}]).status_code == 400
        assert setup([]).status_code == 400
        assert len(db.session.get(LessonPlanFormat, fid).fields) == 3
        print("  bad lists refused OK")

        # --- Review: rename, Guided, Locked, remove one, place one by hand ---
        res = setup(wanted)
        assert res.status_code == 200, res.get_json()
        got = res.get_json()["format"]
        assert got["fields_reviewed"] is True
        fields = got["fields"]
        assert [f["field_key"] for f in fields] == ["name", "topic", "remarks"], fields
        by = {f["field_key"]: f for f in fields}
        assert by["name"]["label"] == "Teacher's name" and by["name"]["role"] == "easy" and not by["name"]["locked"]
        assert by["topic"]["role"] == "heavy" and not by["topic"]["manual"]
        assert by["remarks"]["manual"] and by["remarks"]["locked"] and by["remarks"]["role"] == "heavy"
        assert by["remarks"]["anchor_index"] == 8
        print("  review saved OK")

        # The hand-placed field gets an input in the document.
        fmt = db.session.get(LessonPlanFormat, fid)
        rendered = docx_service.render_template_html(fmt)
        assert "remarks" in rendered["matched_fields"], rendered["unmatched_fields"]
        print("  hand-placed field has an input OK")

        # --- Locked fields are never generated ---
        assert _generatable_keys(None, fmt) == ["name", "topic"]
        assert _generatable_keys(["topic", "remarks"], fmt) == ["topic"]
        print("  locked never generated OK")

        # --- Alan still helps with a locked field, but only coaches ---
        from services import ai_service
        seen = []

        def fake_call(system, parts, label):
            seen.append(parts[-1])
            return {"reply": "Think about what you saw.", "choices": [
                {"type": "use", "label": "Ready text", "text": "Finished remarks."},
                {"type": "ask", "label": "What should I include?", "text": "What should I include?"}]}
        real_call, ai_service._call = ai_service._call, fake_call
        try:
            res = client.post("/api/generate/chat", json={"format_id": fid, "field_key": "remarks", "message": "Help me"})
            assert res.status_code == 200, res.get_json()
            assert [c["type"] for c in res.get_json()["choices"]] == ["ask"], res.get_json()
            assert "locked" in seen[-1].lower()
            res = client.post("/api/generate/chat", json={"format_id": fid, "field_key": "topic", "message": "Help me"})
            assert "use" in [c["type"] for c in res.get_json()["choices"]]
        finally:
            ai_service._call = real_call
        print("  Alan coaches on a locked field OK")

        # --- Editing the document keeps the teacher's fields ---
        res = client.patch(f"/api/formats/{fid}/content", json={"edits": [{"anchor_index": 0, "action": "delete"}]})
        assert res.status_code == 200, res.get_json()
        by = {f["field_key"]: f for f in res.get_json()["format"]["fields"]}
        assert sorted(by) == ["name", "remarks", "topic"], by
        assert (by["name"]["anchor_index"], by["topic"]["anchor_index"], by["remarks"]["anchor_index"]) == (0, 1, 7)
        assert by["name"]["label"] == "Teacher's name" and by["remarks"]["locked"]
        res = client.patch(f"/api/formats/{fid}/content", json={"edits": [{"anchor_index": 0, "action": "delete"}]})
        keys = [f["field_key"] for f in res.get_json()["format"]["fields"]]
        assert keys == ["topic", "remarks"], keys  # its line was deleted, so the field goes with it
        print("  document edits keep the teacher's fields OK")

    print("field setup OK")


if __name__ == "__main__":
    main()
