"""
Loader for matching_config.yaml (single source of tunable values for faculty matching,
cabin labeling, timetable slots, course category normalization, and department normalization).
"""
import os
import re
from typing import Dict, Any, List
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "matching_config.yaml")

_DEFAULT_CONFIG: Dict[str, Any] = {
    "faculty_matching": {
        "honorifics": ["dr", "prof", "professor", "mr", "mrs", "ms"],
        "min_similarity": 0.72,
        "max_displayed_matches": 5,
        "fuzzy_min_token_length": 3,
        "name_trailing_stop_words": [
            "and", "his", "her", "qualifications", "about", "tell", "me", "who", "is",
            "what", "department", "college", "cabin", "teach", "teaches", "teaching",
            "email", "mail", "contact", "office", "located", "sit", "stay", "work", "in", "at",
        ],
    },
    "rate_limiting": {
        "max_requests": 20,
        "window_seconds": 60,
    },
    "cabin_labeling": {
        "separators": ["-", "/", ":", " "],
    },
    "timetable_slots": {
        1: "08:45-09:35",
        2: "09:45-10:35",
        3: "10:45-11:35",
        4: "11:45-12:35",
        5: "13:30-14:20",
        6: "14:30-15:20",
        7: "15:30-16:20",
    },
    "course_category_normalization": {},
    "department_normalization": {
        "strip_patterns": [],
        "aliases": {},
    },
}


_CONFIG_CACHE: Dict[str, Any] = {"mtime": None, "data": None}


def load_matching_config() -> Dict[str, Any]:
    """Loads matching_config.yaml from disk (mtime-cached) with safe defaults."""
    if os.path.exists(CONFIG_PATH):
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
            if _CONFIG_CACHE["mtime"] == mtime and _CONFIG_CACHE["data"] is not None:
                return _CONFIG_CACHE["data"]
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            raw_slots = data.get("timetable_slots") or _DEFAULT_CONFIG["timetable_slots"]
            slots_int = {int(k): str(v) for k, v in raw_slots.items()}
            dept_norm = data.get("department_normalization") or {}
            parsed = {
                "faculty_matching": {
                    **_DEFAULT_CONFIG["faculty_matching"],
                    **(data.get("faculty_matching") or {}),
                },
                "cabin_labeling": {
                    **_DEFAULT_CONFIG["cabin_labeling"],
                    **(data.get("cabin_labeling") or {}),
                },
                "rate_limiting": {
                    **_DEFAULT_CONFIG["rate_limiting"],
                    **(data.get("rate_limiting") or {}),
                },
                "llm": data.get("llm") or {},
                "small_talk": data.get("small_talk") or {},
                "write_requests": data.get("write_requests") or {},
                "semantic_search": data.get("semantic_search") or {},
                "conversational": data.get("conversational") or {},
                "timetable_slots": slots_int,
                "course_category_normalization": {
                    str(k).strip().lower(): str(v).strip()
                    for k, v in (data.get("course_category_normalization") or {}).items()
                },
                "department_normalization": {
                    "strip_patterns": list(dept_norm.get("strip_patterns") or []),
                    "aliases": {
                        str(k).strip().lower(): str(v).strip()
                        for k, v in (dept_norm.get("aliases") or {}).items()
                    },
                },
            }
            _CONFIG_CACHE["mtime"] = mtime
            _CONFIG_CACHE["data"] = parsed
            return parsed
        except Exception:
            pass
    return {
        "faculty_matching": dict(_DEFAULT_CONFIG["faculty_matching"]),
        "cabin_labeling": dict(_DEFAULT_CONFIG["cabin_labeling"]),
        "rate_limiting": dict(_DEFAULT_CONFIG["rate_limiting"]),
        "timetable_slots": dict(_DEFAULT_CONFIG["timetable_slots"]),
        "course_category_normalization": {},
        "department_normalization": {"strip_patterns": [], "aliases": {}},
    }


def strip_honorifics_and_tokenize(text: str, honorifics: List[str] | None = None) -> List[str]:
    """Normalizes a name or query by stripping punctuation and configured honorifics (with or without '.')."""
    if not text:
        return []
    if honorifics is None:
        honorifics = load_matching_config()["faculty_matching"]["honorifics"]
    hon_set = {h.strip().lower().rstrip(".") for h in honorifics if h}
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return [tok for tok in cleaned.split() if tok and tok not in hon_set]


def get_slot_number_map() -> Dict[int, str]:
    """Returns integer-slot -> time-range mapping from matching_config.yaml."""
    return load_matching_config()["timetable_slots"]


def normalize_course_category(raw_category: str) -> str:
    """Normalizes a raw course category string via matching_config.yaml."""
    cleaned = re.sub(r"\s+", " ", (raw_category or "").strip())
    if not cleaned:
        return ""
    cat_map = load_matching_config()["course_category_normalization"]
    return cat_map.get(cleaned.lower(), cleaned)


def normalize_department_name(raw_dept: str) -> str:
    """Normalizes a department string via configured strip_patterns and aliases."""
    s = re.sub(r"\s+", " ", (raw_dept or "").replace("\xa0", " ").strip())
    if not s:
        return ""
    cfg = load_matching_config()["department_normalization"]
    for pat in cfg.get("strip_patterns", []):
        s = re.sub(pat, "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\s+", " ", s).strip()
    # Normalize common title-casing noise ("Department Of", " And ")
    s_key = re.sub(r"\s+", " ", s).strip().lower()
    aliases = cfg.get("aliases", {})
    if s_key in aliases:
        return aliases[s_key]
    # Also try stripping leading "department of " / "dept of "
    s_stripped = re.sub(r"^(?:department|dept\.?)\s+of\s+", "", s_key).strip()
    if s_stripped in aliases:
        return aliases[s_stripped]
    # Standardize "Department Of " -> "Department of " and " And " -> " and "
    s = re.sub(r"\bDepartment\s+Of\b", "Department of", s)
    s = re.sub(r"\s+And\s+", " and ", s)
    return s
