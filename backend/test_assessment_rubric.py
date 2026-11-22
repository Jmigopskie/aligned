"""Self-check for the assessment step and the rubric table:
- the setup's four assessment choices each tell the assessing field what to
  write (objectives decide; quiz; task; both), the rubric always as a table;
- rubric rows ("a | b | c") become a bordered Word table on export, in the
  body or inside a table cell, header bold, markdown |---| rules dropped,
  lone lines and two-cell lines left alone.

No provider or network. Run it directly: `python test_assessment_rubric.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from docx import Document  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402

from services import ai_service, docx_service  # noqa: E402

HEAD = "Criteria | Excellent (4) | Good (3) | Fair (2) | Needs Improvement (1)"
ROW = "Accuracy | All steps correct | One minor error | Several errors | Mostly incorrect"


def directive(kind):
    return ai_service._assessment_directive("evaluation", {"assessment_type": kind})


def main():
    by_objectives = directive("based on the objectives, up to a 10-item multiple-choice quiz")
    assert "objectives already written" in by_objectives and "both" in by_objectives
    assert "up to 10 items" in by_objectives and "' | '" in by_objectives, by_objectives
    assert "affective" in by_objectives and "Observed:" in by_objectives, by_objectives
    quiz = directive("a 15-item multiple-choice quiz")
    assert "exactly 15 items" in quiz and "Rubric" not in quiz, quiz
    task = directive("a performance task with a rubric")
    assert "' | '" in task and "Criteria | Excellent (4)" in task and "quiz" not in task, task
    both = directive("a 5-item multiple-choice quiz and a performance task with a rubric")
    assert "exactly 5 items" in both and "'Performance task:'" in both and "' | '" in both, both
    assert directive("") == "" and ai_service._assessment_directive("mastery", {"assessment_type": "x quiz"}) == ""
    print("  assessment choices OK")

    # A long rubric row survives the length trim whole.
    field = type("F", (), {"field_key": "evaluation", "label": "Evaluation", "field_type": "textarea",
                           "ai_hint": None, "locked": False})()
    long_row = "Accuracy | " + " | ".join(["the learner names every part and explains its use"] * 4)
    out = ai_service._trim({"evaluation": f"Rubric:\n{HEAD}\n{long_row}"}, [field],
                           context={"assessment_type": "a performance task with a rubric"})
    assert out["evaluation"].split("\n")[2] == long_row, out
    print("  rubric rows kept whole OK")

    assert docx_service.pipe_cells(HEAD)[0] == "Criteria" and len(docx_service.pipe_cells(HEAD)) == 5
    assert docx_service.pipe_cells("| a | b | c |") == ["a", "b", "c"]
    assert docx_service.pipe_cells("a | b") == [] and docx_service.pipe_cells("|---|---|---|") == []

    doc = Document()
    doc.add_paragraph("Performance task: build a circuit.")
    doc.add_paragraph("Rubric:")
    doc.add_paragraph(HEAD)
    doc.add_paragraph("|---|---|---|---|---|")
    doc.add_paragraph(ROW)
    doc.add_paragraph("Total: 8 points")
    doc.add_paragraph("Name | Section")          # two cells: not a table
    doc.add_paragraph("Only | one | row")        # a single row: not a table
    outer = doc.add_table(rows=1, cols=2)
    cell = outer.cell(0, 1)
    cell.paragraphs[0].text = HEAD
    cell.add_paragraph(ROW)                       # the rows end the cell
    docx_service.pipe_rows_to_tables(doc)

    body = doc.element.body
    tables = [t for t in body.iter(qn("w:tbl"))]
    assert len(tables) == 3, len(tables)          # outer + body rubric + nested rubric
    rubric = doc.tables[0]
    assert [c.text for c in rubric.rows[0].cells][0] == "Criteria" and len(rubric.rows) == 2
    assert rubric.rows[1].cells[1].text == "All steps correct"
    assert rubric.rows[0].cells[0].paragraphs[0].runs[0].bold
    texts = [p.text for p in doc.paragraphs]
    assert texts == ["Performance task: build a circuit.", "Rubric:", "Total: 8 points", "Name | Section",
                     "Only | one | row"], texts
    nested = doc.tables[1].cell(0, 1)
    assert nested.tables and nested.tables[0].rows[1].cells[0].text == "Accuracy"
    assert nested._tc[-1].tag == qn("w:p"), "a cell must end with a paragraph"
    print("  rubric rows become Word tables OK")
    print("assessment and rubric OK")


if __name__ == "__main__":
    main()
