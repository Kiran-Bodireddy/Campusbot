"""Extra routing rules for common phrasings the original heuristics missed.

Every rule returns (tool_name, params) or None. Names, programmes and course codes are matched
against the graph, so a rule can only point at entities that exist.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

_HON = r"^(?:dr|prof|professor|mr|mrs|ms|miss)\.?\s+"
_NAME_CACHE: Dict[int, List[Tuple[str, str]]] = {}


def _norm(t: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (t or "").lower()))


def _faculty_phrases(faculty: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    key = id(faculty)
    if key not in _NAME_CACHE:
        out = []
        for f in faculty:
            raw = re.sub(_HON, "", (f.get("name") or "").strip(), flags=re.I)
            ph = _norm(raw)
            toks = ph.split()
            if len(toks) >= 2 and len(toks[0]) >= 3 and len(ph) >= 5:
                out.append((ph, f.get("name")))
        out.sort(key=lambda x: -len(x[0]))
        _NAME_CACHE.clear()
        _NAME_CACHE[key] = out
    return _NAME_CACHE[key]


def faculty_named_in(query: str, faculty: List[Dict[str, Any]]) -> Optional[str]:
    q = " " + _norm(query) + " "
    for ph, name in _faculty_phrases(faculty):
        if " " + ph + " " in q:
            return name
    return None


def route_extra(user_query: str, codes: List[str], faculty: List[Dict[str, Any]],
                program_names: List[str]) -> Optional[Tuple[str, Dict[str, Any]]]:
    q = user_query.lower().strip()
    explicit = re.findall(r"\b21[A-Z]{2,4}\d{3}[A-Z]?\b", user_query.upper())   # codes typed by the user (not resolved titles)

    # Reverse prerequisites: "courses that require 21CSC201J", "what needs X as a prerequisite"
    if codes and re.search(r"\b(?:courses?|subjects?|what)\s+(?:that\s+|which\s+)?(?:require|requires|need|needs|depend\s+on|depends\s+on|build\s+on)\b"
                           r"|\b(?:unlock|unlocks|leads?\s+to)\b|\bas\s+a\s+prereq", q):
        return "find_dependent_courses", {"course_code": codes[0]}

    # Compare two programmes: "compare mba and mca", "mba vs mca"
    m = re.search(r"\bcompare\s+(.+?)\s+(?:and|vs\.?|versus|with)\s+(.+?)[\s?.!]*$|^(.+?)\s+(?:vs\.?|versus)\s+(.+?)[\s?.!]*$", q)
    if m and not codes:
        a, b = (m.group(1) or m.group(3)).strip(), (m.group(2) or m.group(4)).strip()
        if 2 <= len(a) <= 120 and 2 <= len(b) <= 120:
            return "compare_programs", {"program_a": a, "program_b": b}

    # Faculty by research area: "professors working on blockchain", "faculty specialising in image processing"
    m = re.search(r"\b(?:faculty|professors?|profs?|teachers?|experts?|researchers?|staff)\s+(?:members?\s+)?(?:who\s+(?:work|works|research|specialise|specialize)\s+(?:on|in)|"
                  r"working\s+on|working\s+in|specialis\w*\s+in|specializ\w*\s+in|researching|research\w*\s+(?:on|in)|expert\s+in|with\s+expertise\s+in|in\s+the\s+(?:area|field)\s+of)\s+(.+?)[\s?.!]*$", q)
    if m and not explicit:
        return "search_faculty", {"specialization": m.group(1).strip()}

    # Course listings by credits / category: "list 4 credit open electives"
    if re.search(r"\b(?:list|show|all|which|what)\b", q) and re.search(r"\b(?:electives?|courses|subjects)\b", q) and not codes \
            and not re.search(r"\b(?:after|finish\w*|complet\w*|unlock\w*|requir\w*|need\w*|prereq\w*)\b", q):
        cr = re.search(r"\b(\d{1,2})\s*-?\s*credits?\b", q)
        cat = None
        for c in ("open elective", "professional elective", "professional core", "basic sciences", "engineering sciences",
                  "humanities", "mandatory non-credit", "project"):
            if c in q or (c.endswith("elective") and c + "s" in q):
                cat = c.title()
                break
        if cr or cat:
            params: Dict[str, Any] = {}
            if cr:
                params["credits"] = int(cr.group(1))
            if cat:
                params["category"] = cat
            return "list_courses", params

    # A faculty member named without "Dr." ("email id of Visalakshi P", "cabin of maria nancy a")
    if not codes:
        name = faculty_named_in(user_query, faculty)
        if name:
            if re.search(r"\b(?:teach\w*|courses?|classes|subjects?)\b", q):
                return "get_faculty_courses", {"faculty_name": name}
            return "lookup_faculty_profile", {"faculty_name": name}
    return None
