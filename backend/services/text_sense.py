"""Whether typed text reads as real words, not a number, a keyboard mash or a
placeholder (user, 2026-11-28). Kept in step with sensible() in
frontend/js/setup-flow-steps.js, which tells the user first; this stops a
request that skipped the page from having a plan written about "12345".
"""
import re

_PLACEHOLDERS = {"test", "testing", "sample", "topic", "none", "na", "n/a", "nothing", "idk", "blah", "abc", "xyz",
                 "asdf", "qwerty", "lorem ipsum", "lorem", "aaa", "xxx", "etc", "something", "anything", "wala"}
_MASHES = ("qwer", "wert", "asdf", "sdfg", "dfgh", "fghj", "ghjk", "hjkl", "zxcv", "xcvb", "cvbn", "vbnm")
_SHORT_MASHES = {"asd", "qwe", "zxc", "sdf", "jkl", "hjk", "dfg"}
_WORD = re.compile(r"[^\W\d_]+")


def _word_ok(word: str) -> bool:
    if re.fullmatch(r"[A-Z]{2,6}s?", word):
        return True  # an acronym: HTML, CSS, LANs
    w = word.lower()
    if re.search(r"(.)\1\1", w) or any(m in w for m in _MASHES):
        return False
    if len(w) < 4:
        return w not in _SHORT_MASHES
    if not re.search(r"[aeiouy]", w):
        return False
    return not re.search(r"[bcdfghjklmnpqrstvwxz]{6,}", w)


def sensible(value) -> bool:
    text = str(value or "").strip()
    letters = len(re.findall(r"[^\W\d_]", text))
    if letters < 3 or letters * 2 < len(re.findall(r"\d", text)):
        return False
    if re.sub(r"[.!?]+$", "", text.lower()) in _PLACEHOLDERS:
        return False
    return all(_word_ok(w) for w in _WORD.findall(text))


if __name__ == "__main__":
    for ok in ("Cell formulas", "IPv4 addressing", "HTML and CSS basics", "Excel 2019 charts", "LANs",
               "Pagsasaka at pag-aalaga ng hayop", "Strengths of materials", "Mary Schmidt", "Ohm's law"):
        assert sensible(ok), ok
    for bad in ("123", "a1", "asdf", "asdfgh", "qwerty", "zzzz", "Test", "n/a", "lorem ipsum", "hgfdkjl", "12 ab", "!!!"):
        assert not sensible(bad), bad
    print("text sense OK")
