"""Self-check for the built-in formats and official DepEd guides.

The five ready-made formats and the DepEd guides ship in backend/builtin/ and
are seeded on every startup. What matters here: seeding is idempotent and
updates rows in place, it never touches a teacher's own formats or uploads,
nobody (the admin who owns them included) can change or delete a built-in
format through any route, every user can see them, a lesson plan on one
exports into the real layout, and guide search ranks official guides first.

Run it directly: `venv/Scripts/python test_builtins.py`.
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from docx import Document

from app import create_app
from extensions import db
from models.course_guide import CourseGuide
from models.format import LessonPlanFormat
from models.lesson_plan import LessonPlan
from models.user import User
from services import builtins, docx_service

KEYS = {"4as-lesson-plan", "dlp", "ilaw-lesson-plan", "pal3-sdlp", "snhs-dlp"}


def client_for(app, user):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user.id
    return client


def make_user(name, email, role):
    u = User(full_name=name, email=email, role=role)
    u.set_password("Password123!")
    db.session.add(u)
    db.session.commit()
    return u


def builtin_formats():
    return LessonPlanFormat.query.filter_by(is_builtin=True).all()


def check_format_seeding(app):
    formats = builtin_formats()
    assert {f.builtin_key for f in formats} == KEYS, [f.builtin_key for f in formats]
    for f in formats:
        assert f.is_public and f.fields and f.description, f.builtin_key
        assert os.path.isfile(f.source_file_path) and os.path.isfile(f.template_docx_path)

    # Seeding again (a restart) changes nothing: same rows, same field rows.
    before = {f.builtin_key: (f.id, [x.id for x in f.fields]) for f in formats}
    builtins.seed_builtins()
    db.session.expire_all()
    after = {f.builtin_key: (f.id, [x.id for x in f.fields]) for f in builtin_formats()}
    assert before == after, "a second seed must not rewrite anything"
    print("  format seeding idempotent OK")


def check_manifest_change_updates_in_place(app):
    tmp = tempfile.mkdtemp()
    try:
        src = os.path.join(builtins.BUILTIN_DIR, "formats")
        dst = os.path.join(tmp, "formats")
        shutil.copytree(src, dst)
        manifest = json.load(open(os.path.join(dst, "formats.json"), encoding="utf-8"))
        entry = next(e for e in manifest if e["key"] == "dlp")
        entry["name"] = "DLP renamed"
        entry["fields"] = entry["fields"][:3]
        # A broken entry and a missing file must be skipped, not crash startup.
        manifest.append({"key": "broken"})
        manifest.append({"key": "ghost", "source": "nope.pdf", "template": "nope.docx", "fields": [{"label": "X"}]})
        json.dump(manifest, open(os.path.join(dst, "formats.json"), "w", encoding="utf-8"))

        old_id = LessonPlanFormat.query.filter_by(builtin_key="dlp").one().id
        builtins.seed_builtins(tmp)
        db.session.expire_all()
        dlp = LessonPlanFormat.query.filter_by(builtin_key="dlp").one()
        assert dlp.id == old_id and dlp.name == "DLP renamed" and len(dlp.fields) == 3
        assert not LessonPlanFormat.query.filter(LessonPlanFormat.builtin_key.in_(["broken", "ghost"])).count()
    finally:
        builtins.seed_builtins()  # back to the real manifest
        db.session.expire_all()
        shutil.rmtree(tmp, ignore_errors=True)
    assert LessonPlanFormat.query.filter_by(builtin_key="dlp").one().name == "Detailed Lesson Plan (DLP)"
    print("  manifest change updates in place OK")


def check_lock(app, admin, teacher, student):
    fmt = LessonPlanFormat.query.filter_by(builtin_key="4as-lesson-plan").one()
    field_key = fmt.fields[0].field_key
    for user in (admin, teacher):  # admin is the nominal owner
        c = client_for(app, user)
        calls = [
            c.patch(f"/api/formats/{fmt.id}", json={"name": "Hijacked"}),
            c.delete(f"/api/formats/{fmt.id}"),
            c.patch(f"/api/formats/{fmt.id}/content", json={"edits": [{"anchor_index": 1, "action": "delete"}]}),
            c.patch(f"/api/formats/{fmt.id}/field-roles", json={"roles": {field_key: "heavy"}}),
        ]
        assert [r.status_code for r in calls] == [403] * 4, [r.status_code for r in calls]
    db.session.expire_all()
    fmt = db.session.get(LessonPlanFormat, fmt.id)
    assert fmt.name == "4A's Lesson Plan" and fmt.fields[0].role is None

    # A teacher's own format is still theirs to change, and seeding leaves it alone.
    c = client_for(app, student)
    res = c.post("/api/formats", json={"name": "Mine", "fields": [{"label": "Objectives"}]})
    assert res.status_code == 201, res.get_json()
    mine = res.get_json()["format"]["id"]
    assert c.patch(f"/api/formats/{mine}", json={"name": "Mine, renamed"}).status_code == 200
    builtins.seed_builtins()
    db.session.expire_all()
    own = db.session.get(LessonPlanFormat, mine)
    assert own.name == "Mine, renamed" and not own.is_builtin and own.builtin_key is None
    print("  lock OK")


def check_visibility(app, student):
    res = client_for(app, student).get("/api/formats").get_json()
    shown = [f for f in res["formats"] if f["is_builtin"]]
    assert {f["name"] for f in shown} >= {"4A's Lesson Plan", "SNHS Detailed Lesson Plan"}
    assert len(shown) == 5
    for f in shown:
        assert f["thumbnail"].startswith("img/formats/") and f["field_count"] > 0 and f["description"]
    src = client_for(app, student).get(f"/api/formats/{shown[0]['id']}/source?inline=1")
    assert src.status_code == 200 and "inline" in src.headers.get("Content-Disposition", "inline")
    src.close()
    print("  visibility OK")


def check_export_fills_frozen_anchors(app, student):
    """The hand-added 4A's anchors (Abstraction's answer cell holds an "a."
    placeholder) must actually receive the teacher's text on export."""
    fmt = LessonPlanFormat.query.filter_by(builtin_key="4as-lesson-plan").one()
    by_label = {f.label: f.field_key for f in fmt.fields}
    plan = LessonPlan(user_id=student.id, format_id=fmt.id, title="Export check")
    plan.set_values({by_label["Abstraction"]: "ABSTRACTION-TEXT-XYZ", by_label["Activity"]: "ACTIVITY-TEXT-XYZ",
                     by_label["Review"]: "REVIEW-TEXT-XYZ",
                     by_label["Learning Competencies and Objectives"]: "LC-TEXT-XYZ"})
    db.session.add(plan)
    db.session.commit()
    path = docx_service.export_lesson_plan(plan, fmt)
    text = "\n".join(c.text for t in Document(path).tables for r in t.rows for c in r.cells)
    assert "ABSTRACTION-TEXT-XYZ" in text and "ACTIVITY-TEXT-XYZ" in text
    # And in the answer cell beside its label, not squeezed into the label
    # cell: the 4A's answer cells for these rows started out holding a
    # leftover bullet or "a." that made them look already filled.
    for label, value in (("ABSTRACTION", "ABSTRACTION-TEXT-XYZ"), ("ACTIVITY", "ACTIVITY-TEXT-XYZ"),
                         ("REVIEW", "REVIEW-TEXT-XYZ"), ("LEARNING COMPETENCIES", "LC-TEXT-XYZ")):
        row = next(r for t in Document(path).tables for r in t.rows
                   if r.cells[0].text.strip().upper().startswith(label))
        assert value not in row.cells[0].text, (label, row.cells[0].text)
        assert value in row.cells[-1].text, (label, [c.text for c in row.cells])
    os.remove(path)
    # The shared template itself is never written to.
    assert "XYZ" not in "\n".join(c.text for t in Document(fmt.template_docx_path).tables for r in t.rows for c in r.cells)
    print("  export into the real layout OK")


def _guide_docx(path, text):
    d = Document()
    d.add_paragraph(text)
    d.save(path)


def check_guides(app, admin, student):
    tmp = tempfile.mkdtemp()
    try:
        folder = os.path.join(tmp, "course_guides")
        os.makedirs(folder)
        _guide_docx(os.path.join(folder, "g7.docx"), "Grade 7 ICT budget of work")
        _guide_docx(os.path.join(folder, "cp.docx"), "Computer Programming budget of work")
        json.dump([
            {"key": "bow-g7-ict", "title": "[G7] TLE: ICT", "subject": "ICT", "doc_type": "budget_of_work",
             "grade_band": "7-8", "grades": "7", "curriculum": "MATATAG", "file": "g7.docx",
             "source_url": "https://example.test/g7", "retrieved_at": "2026-09-25"},
            {"key": "bow-g9-cp", "title": "[G9/G10] TLE: ICT - Computer Programming", "subject": "CP (ComProg)",
             "doc_type": "budget_of_work", "grade_band": "9-10", "grades": "9-10", "curriculum": "MATATAG",
             "file": "cp.docx", "source_url": "https://example.test/cp", "retrieved_at": "2026-09-25"},
            {"key": "missing", "file": "not-there.pdf"},
        ], open(os.path.join(folder, "guides.json"), "w", encoding="utf-8"))

        # A teacher's upload that predates the seeding.
        c = client_for(app, student)
        res = c.post("/api/course-guides", data={
            "subject": "ICT", "title": "My ICT notes",
            "file": (io.BytesIO(open(os.path.join(folder, "g7.docx"), "rb").read() + b""), "notes.docx"),
        }, content_type="multipart/form-data")
        assert res.status_code in (200, 201), res.get_json()
        own_id = res.get_json()["course_guide"]["id"]

        builtins.seed_builtins(tmp)
        builtins.seed_builtins(tmp)  # idempotent
        official = CourseGuide.query.filter(CourseGuide.builtin_key.in_(["bow-g7-ict", "bow-g9-cp"])).all()
        assert sorted(g.builtin_key for g in official) == ["bow-g7-ict", "bow-g9-cp"]
        assert all(g.extracted_text for g in official)
        own = db.session.get(CourseGuide, own_id)
        assert not own.is_builtin and own.title == "My ICT notes"

        rows = c.get("/api/course-guides?subject=ICT").get_json()["course_guides"]
        assert rows[0]["is_builtin"], "official guides come first"
        assert rows[-1]["id"] == own_id
        # Official guides come in catalogue (seed) order, not by upload date.
        titles = [g["title"] for g in c.get("/api/course-guides").get_json()["course_guides"] if g["is_builtin"]]
        assert titles.index("[G7] TLE: ICT") < titles.index("[G9/G10] TLE: ICT - Computer Programming"), titles

        cp = c.get("/api/course-guides?subject=CP%20(ComProg)").get_json()["course_guides"]
        assert "[G9/G10] TLE: ICT - Computer Programming" in [g["title"] for g in cp], cp
        assert all(g["is_builtin"] for g in cp)

        band = c.get("/api/course-guides?grade_band=7-8").get_json()["course_guides"]
        assert "[G7] TLE: ICT" in [g["title"] for g in band] and all("7-8" in g["grade_band"] for g in band)
        pref = c.get("/api/course-guides?prefer_grade_band=9-10").get_json()["course_guides"]
        assert "9-10" in pref[0]["grade_band"]
        # The MATATAG curriculum guide spans Grades 4 to 10, so every JHS band
        # filter must still find it.
        for b in ("4-6", "7-8", "9-10"):
            rows = c.get(f"/api/course-guides?grade_band={b}&doc_type=curriculum_guide").get_json()["course_guides"]
            assert any(g["title"].startswith("MATATAG EPP/TLE") for g in rows), (b, rows)
        assert all(g["doc_type"] == "curriculum_guide" for g in c.get("/api/course-guides?doc_type=curriculum_guide").get_json()["course_guides"])

        g7 = next(g for g in official if g.builtin_key == "bow-g7-ict")
        f = c.get(f"/api/course-guides/{g7.id}/file")
        assert f.status_code == 200 and f.data[:2] == b"PK"
        f.close()

        # Uploading the official file again hands back the official row.
        again = c.post("/api/course-guides", data={
            "subject": "ICT", "file": (io.BytesIO(open(os.path.join(folder, "cp.docx"), "rb").read()), "dup.docx"),
        }, content_type="multipart/form-data").get_json()
        assert again["duplicate"] and again["course_guide"]["is_builtin"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for g in CourseGuide.query.filter_by(is_builtin=False).all():
            if g.file_path and os.path.isfile(g.file_path):
                os.remove(g.file_path)
    print("  guides OK")


def check_upgrade_from_old_schema():
    """A database created before this feature (tables without the new
    columns, one guide missing its hash so the old backfill runs) must boot
    and get seeded. Every real server is upgraded this way."""
    import sqlite3
    from sqlalchemy.pool import NullPool

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, full_name VARCHAR(120) NOT NULL, email VARCHAR(120) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL, role VARCHAR(20) NOT NULL, created_at DATETIME);
        CREATE TABLE lesson_plan_formats (id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, name VARCHAR(120) NOT NULL,
            is_public BOOLEAN, source_file_path VARCHAR(255), created_at DATETIME);
        CREATE TABLE course_guides (id INTEGER PRIMARY KEY, uploader_id INTEGER NOT NULL, subject VARCHAR(150) NOT NULL,
            title VARCHAR(200) NOT NULL, file_path VARCHAR(255) NOT NULL, extracted_text TEXT, created_at DATETIME);
        INSERT INTO users (id, full_name, email, password_hash, role) VALUES (1, 'Old Teacher', 'old@example.test', 'x', 'teacher');
        INSERT INTO lesson_plan_formats (id, owner_id, name, is_public) VALUES (1, 1, 'Old format', 0);
        INSERT INTO course_guides (id, uploader_id, subject, title, file_path) VALUES (1, 1, 'ICT', 'Old guide', 'gone.pdf');
    """)
    con.close()

    os.environ["DATABASE_URL"] = f"sqlite:///{path}"
    try:
        from config import Config
        Config.SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]
        Config.SQLALCHEMY_ENGINE_OPTIONS = {"poolclass": NullPool}
        app = create_app()
        with app.app_context():
            assert LessonPlanFormat.query.filter_by(is_builtin=True).count() == 5
            old = db.session.get(LessonPlanFormat, 1)
            assert old.name == "Old format" and not old.is_builtin
            db.session.remove()
            db.engine.dispose()
    finally:
        os.environ["DATABASE_URL"] = "sqlite://"
        Config.SQLALCHEMY_DATABASE_URI = "sqlite://"
        Config.SQLALCHEMY_ENGINE_OPTIONS = {}
        os.remove(path)
    print("  upgrade from old schema OK")


def check_guide_text_is_precomputed(app):
    """Boot must not spend minutes in PDF text extraction: every gunicorn
    worker seeds while loading, so a guide ships its text beside it as
    <name>.txt and the seeder reads that. A guide without one is extracted
    once; an empty or failed extraction is not retried on every boot."""
    from services import text_extract

    tmp = tempfile.mkdtemp()
    real = text_extract.extract_text
    calls = []

    def fake(path):
        calls.append(os.path.basename(path))
        return ""

    try:
        folder = os.path.join(tmp, "course_guides")
        os.makedirs(folder)
        _guide_docx(os.path.join(folder, "cached.docx"), "ignored body")
        with open(os.path.join(folder, "cached.txt"), "w", encoding="utf-8") as fh:
            fh.write("PRECOMPUTED TEXT")
        _guide_docx(os.path.join(folder, "scanned.docx"), "")
        json.dump([
            {"key": "t-cached", "title": "Cached", "subject": "ICT", "file": "cached.docx"},
            {"key": "t-scanned", "title": "Scanned", "subject": "ICT", "file": "scanned.docx"},
        ], open(os.path.join(folder, "guides.json"), "w", encoding="utf-8"))

        text_extract.extract_text = fake
        builtins.seed_builtins(tmp)
        builtins.seed_builtins(tmp)
    finally:
        text_extract.extract_text = real
        shutil.rmtree(tmp, ignore_errors=True)

    cached = CourseGuide.query.filter_by(builtin_key="t-cached").one()
    assert cached.extracted_text == "PRECOMPUTED TEXT", cached.extracted_text
    assert "cached.docx" not in calls, calls
    assert calls.count("scanned.docx") == 1, calls
    # Every shipped official guide has its text beside it.
    folder = os.path.join(builtins.BUILTIN_DIR, "course_guides")
    for entry in json.load(open(os.path.join(folder, "guides.json"), encoding="utf-8")):
        txt = os.path.join(folder, os.path.splitext(entry["file"])[0] + ".txt")
        assert os.path.isfile(txt) and os.path.getsize(txt) > 1000, txt
    print("  guide text precomputed OK")


def check_admin_owning_builtins_can_be_deleted(app, first_admin):
    """The first admin owns the seeded built-ins. Another admin must still be
    able to delete that account; the built-ins move to the acting admin."""
    second = make_user("Second Admin", "second.admin@example.test", "admin")
    res = client_for(app, second).delete(f"/api/admin/users/{first_admin.id}")
    assert res.status_code == 200, (res.status_code, res.get_json())
    db.session.expire_all()
    assert all(f.owner_id == second.id for f in builtin_formats())
    assert all(g.uploader_id == second.id for g in CourseGuide.query.filter_by(is_builtin=True))
    print("  deleting the admin who owns built-ins OK")


def main():
    check_upgrade_from_old_schema()
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        admin = User.query.filter_by(role="admin").one()
        teacher = make_user("Tess Teacher", "tess@example.test", "teacher")
        student = make_user("Stu Student", "stu@example.test", "student")
        check_format_seeding(app)
        check_manifest_change_updates_in_place(app)
        check_lock(app, admin, teacher, student)
        check_visibility(app, student)
        check_export_fills_frozen_anchors(app, student)
        check_guides(app, admin, student)
        check_guide_text_is_precomputed(app)
        check_admin_owning_builtins_can_be_deleted(app, admin)
    print("builtins OK")


if __name__ == "__main__":
    main()
