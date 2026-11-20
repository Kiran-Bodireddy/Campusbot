"""Course-title matching that tolerates small words, short forms and plurals.

"who teaches formal language automata" -> 21CSC301T (Formal Language And Automata)
"who teaches discrete maths"           -> 21MAB302T (Discrete Mathematics)
Only titles from the graph are matched, so the result is always a real course code.
"""
import difflib
import re
from typing import Dict, List, Optional

_SMALL = {"and", "of", "the", "for", "in", "to", "a", "an", "on", "with"}

# common student short forms -> words used in course titles
_ALIASES = {
    "maths": "mathematics", "math": "mathematics", "stats": "statistics", "algo": "algorithms",
    "algos": "algorithms", "prob": "probability", "dbms": "database management systems",
    "os": "operating systems", "cn": "computer networks", "ai": "artificial intelligence",
    "ml": "machine learning", "dl": "deep learning", "nlp": "natural language processing",
    "oops": "object oriented programming", "oop": "object oriented programming",
    "dsa": "data structures algorithms", "daa": "design analysis algorithms",
    "se": "software engineering", "iot": "internet things", "cv": "computer vision",
    "ds": "data structures algorithms", "intro": "introduction",
}


def _words(text: str, expand: bool = False) -> List[str]:
    text = (text or "").lower().replace("&", " and ")
    out: List[str] = []
    for w in re.findall(r"[a-z0-9]+", text):
        if w in _SMALL:
            continue
        if expand and w in _ALIASES:
            out.extend(_ALIASES[w].split())
        else:
            out.append(w)
    return out


def _word_ok(title_word: str, q_words: List[str]) -> bool:
    for q in q_words:
        if q == title_word:
            return True
        qs = q[:-1] if q.endswith("s") and len(q) > 4 else q          # maths -> math, networks -> network
        ts = title_word[:-1] if title_word.endswith("s") and len(title_word) > 4 else title_word
        if qs == ts:
            return True
        if len(qs) >= 4 and title_word.startswith(qs):              # math -> mathematics, algo -> algorithms
            return True
    return False


def resolve_course_title(query: str, course_by_code: Dict[str, Dict]) -> Optional[str]:
    """Longest course title whose words all appear in the query (exact phrase first, then word-wise)."""
    q_exact = " " + " ".join(_words(query)) + " "
    q_words = _words(query, expand=True)
    best, best_len, best_exact = None, 0, False
    for code, c in course_by_code.items():
        t_words = _words(c.get("name", ""))
        key = " ".join(t_words)
        if len(key) < 5 or (len(t_words) < 2 and len(key) < 8):
            continue
        exact = (" " + key + " ") in q_exact
        if not exact and (len(t_words) < 2 or not all(_word_ok(w, q_words) for w in t_words)):
            continue
        rank = (exact, len(key))
        if best is None or rank > (best_exact, best_len):
            best, best_len, best_exact = code, len(key), exact
    word_best, word_len = best, best_len
    best = None
    # Typo pass ("imcrocontrollers and its application in medicine", "instrumentatio nsystem design"):
    # compare each multi-word title with same-length windows of the query, letters only
    qw = _words(query)
    best_ratio = 0.0
    for code, c in course_by_code.items():
        t_words = _words(c.get("name", ""))
        if len(t_words) < 2:
            continue
        key = " ".join(t_words)
        if len(key) < 12:
            continue
        n = len(t_words)
        for size in (n - 1, n, n + 1):
            if size < 2 or size > len(qw):
                continue
            for i in range(len(qw) - size + 1):
                window = " ".join(qw[i:i + size])
                r = difflib.SequenceMatcher(None, window, key).ratio()
                if r > best_ratio:
                    best_ratio, best = r, code
    typo_best = best if best_ratio >= 0.88 else None
    if word_best and typo_best and typo_best != word_best:
        # "digital rinciples and system design": the longer, almost-exact title beats a shorter subset title
        if len(_words(course_by_code[typo_best].get("name", ""))) > len(_words(course_by_code[word_best].get("name", ""))) and best_ratio >= 0.9:
            return typo_best
    return word_best or typo_best
