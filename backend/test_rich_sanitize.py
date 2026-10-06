"""Self-check for server-side cleaning of a plan's styled field HTML.

The page cleans what it saves, but the API accepts whatever is sent, and the
saved HTML is painted back with innerHTML for anyone who opens the plan. So the
server rebuilds it from the same small allowlist: formatting marks, lists, the
size/colour/highlight classes, and pictures by id. Everything else goes.

Run it directly: `venv/Scripts/python test_rich_sanitize.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from services.rich_html import sanitize_rich_html, sanitize_rich_values
from models.lesson_plan import LessonPlan

IMG = "a" * 32


def check_scripts_and_handlers_removed():
    dirty = ('ok<script>alert(1)</script><img src=x onerror="alert(2)">'
             '<b onclick="x()">bold</b><a href="javascript:alert(3)">link</a>'
             '<style>body{display:none}</style><iframe src="//evil"></iframe>')
    clean = sanitize_rich_html(dirty)
    for bad in ("script", "onerror", "onclick", "javascript", "<a", "iframe", "style", "alert(1)", "display:none"):
        assert bad not in clean, (bad, clean)
    assert clean == "ok<b>bold</b>link", clean
    print("  scripts and handlers removed OK")


def check_formatting_kept():
    html = ('<b>B</b> <i>I</i> <u>U</u><br><ul><li>one</li><li><strong>two</strong></li></ul>'
            '<ol><li><em>x</em></li></ol><span class="fs-lg fc-red hl-yellow bogus">styled</span>'
            '<span class="nothing">plain</span><span style="color:red">inline</span>')
    clean = sanitize_rich_html(html)
    assert clean == ('<b>B</b> <i>I</i> <u>U</u><br><ul><li>one</li><li><strong>two</strong></li></ul>'
                     '<ol><li><em>x</em></li></ol><span class="fs-lg fc-red hl-yellow">styled</span>'
                     'plaininline'), clean
    assert sanitize_rich_html(clean) == clean, "cleaning is idempotent"
    assert sanitize_rich_html("a &lt;b&gt; &amp; c") == "a &lt;b&gt; &amp; c"
    assert sanitize_rich_html("<div>one</div><p>two</p>") == "one<br>two<br>"
    print("  formatting kept OK")


def check_pictures():
    pic = (f'<span class="lp-img img-align-center img-wrap-left img-border evil" data-img-id="{IMG}" '
           f'data-width-pct="250" onclick="x" contenteditable="false"><img src="https://evil/x.png" onerror="y">'
           f'<span class="lp-img-handle"></span><span class="lp-img-cap" contenteditable="true">Fig <b>1</b></span></span>')
    clean = sanitize_rich_html(pic)
    assert clean == (f'<span class="lp-img img-align-center img-wrap-left img-border" data-img-id="{IMG}" '
                     f'data-width-pct="100" contenteditable="false"><img src="/api/images/{IMG}" alt="">'
                     f'<span class="lp-img-cap">Fig <b>1</b></span></span>'), clean
    assert sanitize_rich_html(clean) == clean
    bad_id = '<span class="lp-img" data-img-id="../../etc"><img src="x"></span>after'
    assert sanitize_rich_html(bad_id) == "after", sanitize_rich_html(bad_id)
    print("  pictures OK")


def check_value_shapes():
    vals = {"flow": "<b>a</b><script>x</script>", "weekly": ["<i>mon</i><img onerror=1>", None, ""], "n": None, "x": 5}
    clean = sanitize_rich_values(vals)
    assert clean == {"flow": "<b>a</b>", "weekly": ["<i>mon</i>", "", ""], "n": "", "x": ""}, clean
    assert sanitize_rich_values("not a dict") == {}
    print("  value shapes OK")


def check_model_cleans_on_save_and_read():
    plan = LessonPlan()
    plan.set_rich_values({"flow": '<b>ok</b><img src=x onerror="alert(1)">'})
    assert plan.get_rich_values() == {"flow": "<b>ok</b>"}, plan.get_rich_values()
    plan.set_mode_values({"field_values": {"flow": "t"}, "rich_field_values": {"flow": "<script>x</script>y"}, "step_index": 2})
    mv = plan.get_mode_values()
    assert mv["rich_field_values"] == {"flow": "y"} and mv["step_index"] == 2 and mv["field_values"] == {"flow": "t"}, mv
    # A row saved before this fix is cleaned when it is read back.
    plan.rich_field_values = '{"flow": "<svg onload=alert(1)>hi</svg>"}'
    assert plan.get_rich_values() == {"flow": "hi"}, plan.get_rich_values()
    print("  model cleans on save and read OK")


if __name__ == "__main__":
    check_scripts_and_handlers_removed()
    check_formatting_kept()
    check_pictures()
    check_value_shapes()
    check_model_cleans_on_save_and_read()
    print("rich sanitize OK")
