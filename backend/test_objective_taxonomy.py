"""Self-check: objectives take their verbs from the taxonomy of their domain
(Revised Bloom's for cognitive, Krathwohl for affective, Dave for
psychomotor), still exactly 3, only the domains the lesson really has.

No provider or network. Run it directly: `python test_objective_taxonomy.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = "sqlite://"

from services import ai_service  # noqa: E402


class Field:
    def __init__(self, field_key, label, field_type="textarea"):
        self.field_key, self.label, self.field_type = field_key, label, field_type
        self.ai_hint, self.locked = None, False


LEVELS = ("Remember Understand Apply Analyze Evaluate Create Receiving Responding Valuing Organization "
          "Characterization Imitation Manipulation Precision Articulation Naturalization").split()


def main():
    t = ai_service.taxonomy_text()
    assert "Revised Bloom's" in t and "Krathwohl" in t and "Dave" in t, t
    for level in LEVELS:
        assert level in t, level
    assert set(ai_service.TAXONOMIES) == {"cognitive", "affective", "psychomotor"}
    # A verb names one domain, so the coherence check can tell them apart.
    verbs = [v for _, levels in ai_service.TAXONOMIES.values() for _, vs in levels for v in vs]
    assert len(verbs) == len(set(verbs)), sorted(v for v in verbs if verbs.count(v) > 1)
    print("  three taxonomies with their levels OK")

    d = ai_service._field_directive(Field("objectives", "Objectives", "list"))
    assert t in d, d
    assert "exactly 3" in d and "only the domains" in d.lower(), d
    assert "understand', 'know', 'learn'" in d and "lower to higher" in d, d
    print("  objectives directive uses them OK")
    print("objective taxonomy OK")


if __name__ == "__main__":
    main()
