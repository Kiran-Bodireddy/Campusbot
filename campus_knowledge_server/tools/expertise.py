"""
Expertise matching: "who could teach this course?" answered only with real data.

The dataset has no official teacher-to-course allocation (the TEACHES links made by
data/build_campus_dataset.py are random and are NOT used). Instead we rank faculty from the
department that offers the course by how well their published specialization matches the
course topic. Every name, designation, specialization and cabin shown is real.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

COMPUTING_FAMILY = [
    "Department of Computing Technologies", "Department of Computational Intelligence",
    "Department of Networking And Communications", "Department of Data Science And Business Systems",
    "Department of CTech",
]
CODE_PREFIX_DEPTS = {
    "21CS": COMPUTING_FAMILY, "21IT": COMPUTING_FAMILY, "21AI": COMPUTING_FAMILY, "21DS": COMPUTING_FAMILY,
    "21MA": ["mathematics"], "21EC": ["electronics and communication"], "21EE": ["electrical and electronics"],
    "21ME": ["mechanical"], "21CE": ["civil"], "21BT": ["biotechnology"], "21PY": ["physics"],
    "21CY": ["chemistry"], "21LE": ["english", "language"], "21AS": ["aerospace"], "21AU": ["automobile"],
    "21BM": ["biomedical"], "21EI": ["electronics and instrumentation"], "21MH": ["mechatronics"],
    "21CH": ["chemical"], "21GN": ["genetic"], "21NT": ["nanotechnology", "physics"],
    "21MG": ["management"], "21MB": ["management"], "21BA": ["management"], "21CM": ["commerce"],
    "21BI": ["bioinformatics", "biotechnology"], "21FT": ["food"], "21AG": ["agricultur"],
}

STOP = {"and", "of", "the", "for", "in", "to", "a", "an", "with", "on", "introduction", "principles", "fundamentals",
        "basics", "basic", "computer", "computers", "computing", "smart", "engineering", "systems", "system", "design", "analysis", "theory", "advanced", "applied",
        "applications", "application", "lab", "laboratory", "practice", "technology", "technologies", "concepts",
        "elements", "studies", "study", "methods", "techniques", "management", "i", "ii", "iii", "iv"}

# topic word -> extra phrases that mean the same expertise in faculty profiles
SYNONYMS = {
    "probability": ["probability", "statistics", "stochastic"],
    "queueing": ["queueing", "queuing", "queue", "stochastic", "operations research"],
    "statistics": ["statistics", "statistical", "probability"],
    "algorithms": ["algorithm", "data structures", "theory of computation", "optimization", "graph theory"],
    "database": ["database", "dbms", "data management", "big data", "data mining", "data analytics"],
    "artificial": ["artificial intelligence", "machine learning", "deep learning", "neural network"],
    "intelligence": ["artificial intelligence", "machine learning", "intelligent"],
    "compiler": ["compiler", "automata", "formal language", "theory of computation"],
    "automata": ["automata", "theory of computation", "formal language", "compiler"],
    "formal": ["formal language", "formal method", "theory of computation", "automata"],
    "language": [], "languages": [],
    "networks": ["network", "networking", "wireless", "sensor network", "communication"],
    "network": ["network", "networking", "wireless"],
    "operating": ["operating system", "distributed system", "parallel computing"],
    "security": ["security", "cryptography", "cyber"],
    "cryptography": ["cryptography", "security"],
    "software": ["software engineering", "software testing", "software"],
    "cloud": ["cloud"], "iot": ["iot", "internet of things", "embedded"],
    "learning": ["machine learning", "deep learning"],
    "machine": ["machine learning"], "deep": ["deep learning", "neural network"],
    "image": ["image processing", "computer vision"], "vision": ["computer vision", "image processing"],
    "data": ["data science", "data mining", "data analytics", "big data"],
    "web": ["web", "internet"], "mobile": ["mobile", "android"],
    "calculus": ["calculus", "differential equations", "analysis"], "linear": ["linear algebra", "matrix"],
    "transforms": ["transforms", "fourier", "differential equations"], "discrete": ["discrete mathematics", "graph theory", "combinatorics"],
    "numerical": ["numerical"], "optimization": ["optimization", "operations research"],
    "communication": ["communication", "signal processing", "wireless"],
    "signal": ["signal processing", "dsp"], "vlsi": ["vlsi", "embedded"], "embedded": ["embedded", "vlsi", "iot"],
    "power": ["power systems", "power electronics"], "thermodynamics": ["thermal", "thermodynamics", "heat transfer"],
    "structural": ["structural", "structures"], "environmental": ["environmental"],
}

DESIG_RANK = [("professor and head", 0), ("professor & head", 0), ("head", 0), ("professor", 1),
              ("associate professor", 2), ("assistant professor", 3)]


def _norm(s: str) -> str:
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"\b(department|school|faculty|college) of\b", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def _desig_rank(desig: str) -> int:
    d = (desig or "").lower()
    if "head" in d:
        return 0
    if "associate" in d:
        return 2
    if "assistant" in d:
        return 3
    if "professor" in d:
        return 1
    return 4


def candidate_departments(course: Dict[str, Any], faculty_departments: Iterable[str]) -> List[str]:
    """Faculty departments that plausibly offer this course (by the course's department, then its code)."""
    # ignore malformed department strings from other campuses / scraping artefacts
    depts = sorted(set(d for d in faculty_departments if d and "](" not in d and "Nagar" not in d))
    cdept = _norm(course.get("department", ""))
    out: List[str] = []
    if cdept and cdept not in ("computing", "engineering and technology"):
        for d in depts:
            nd = _norm(d)
            if nd and (cdept in nd or nd in cdept):
                out.append(d)
    if not out:
        prefix = (course.get("code") or "")[:4].upper()
        for hint in CODE_PREFIX_DEPTS.get(prefix, []):
            for d in depts:
                if d == hint or (hint.islower() and hint in _norm(d)):
                    out.append(d)
    return list(dict.fromkeys(out))


def topic_phrases(course: Dict[str, Any]) -> List[str]:
    words = [w for w in re.findall(r"[a-z]+", (course.get("name") or "").lower()) if w not in STOP and len(w) > 2]
    phrases: List[str] = []
    for w in words:
        phrases.extend(SYNONYMS.get(w, [w]))
    name = (course.get("name") or "").lower()
    for multi in ("artificial intelligence", "machine learning", "computer networks", "operating systems",
                  "data structures", "image processing", "computer vision", "software engineering",
                  "internet of things", "cloud computing", "big data", "data science"):
        if multi in name:
            phrases.append(multi.rstrip("s"))
    return list(dict.fromkeys(phrases))


def _matches(phrase: str, spec: str) -> bool:
    if " " in phrase:
        return phrase in spec
    # plural / -e endings only (algorithms ~ algorithm, network ~ networking) - never automata ~ automation
    stem = phrase[:-1] if len(phrase) >= 5 and phrase.endswith(("s", "e")) else phrase
    return re.search(r"\b" + re.escape(stem) + r"(?:s|es|e|ing|ed|al)?\b", spec) is not None


def rank_faculty(course: Dict[str, Any], pool: List[Dict[str, Any]], all_faculty: List[Dict[str, Any]],
                 limit: int = 5) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Returns (ranked faculty with match info, topic phrases used)."""
    phrases = topic_phrases(course)
    specs_all = [(f.get("specialization") or "").lower() for f in all_faculty]
    n = max(len(specs_all), 1)
    idf = {p: math.log(n / (1 + sum(1 for s in specs_all if _matches(p, s)))) + 1.0 for p in phrases}
    scored = []
    for f in pool:
        spec = (f.get("specialization") or "").lower()
        hit = [p for p in phrases if spec and _matches(p, spec)]
        score = sum(idf[p] for p in hit)
        title = re.sub(r"\s+", " ", (course.get("name") or "").lower()).strip()
        if title and len(title) > 5 and title in spec:
            score += 8.0                                         # the course itself is listed as a specialization
        scored.append((score, -_desig_rank(f.get("designation")), f, hit))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2].get("name", "")))
    out = []
    for score, _, f, hit in scored[:limit]:
        out.append({
            "id": f.get("id"), "name": re.sub(r"\s+", " ", f.get("name", "")).strip(),
            "designation": re.sub(r"\s+", " ", f.get("designation", "")).strip(),
            "department": f.get("department", ""), "specialization": f.get("specialization", ""),
            "cabin": f.get("cabin", ""), "email": f.get("email", ""),
            "matched_topics": hit, "match_score": round(score, 2),
        })
    return out, phrases


def experts_for_course(course: Dict[str, Any], faculty: List[Dict[str, Any]], exclude: Optional[set] = None,
                       limit: int = 5) -> Dict[str, Any]:
    exclude = exclude or set()
    depts = candidate_departments(course, (f.get("department") for f in faculty))
    pool = [f for f in faculty if f.get("department") in depts and f.get("name") not in exclude]
    if not pool:
        # offering department unknown: search everyone's published specialization
        pool = [f for f in faculty if f.get("name") not in exclude]
        depts = ["(all departments - offering department not identified)"]
    ranked, phrases = rank_faculty(course, pool, faculty, limit=limit)
    matched = [r for r in ranked if r["matched_topics"]]
    basis = "specialization"
    if not matched and depts and depts[0].startswith("(all departments"):
        basis, ranked = "none", []
    elif not matched:
        # no specialization overlap in the offering department: show its senior faculty, clearly labelled
        basis = "department"
        ranked.sort(key=lambda r: (_desig_rank(r["designation"]), r["name"]))
    else:
        ranked = matched
    return {"departments": depts, "topics": phrases, "specialists": ranked, "match_basis": basis}
