"""
Loader for matching_config.yaml (single source of tunable values for faculty matching and cabin labeling).
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
    },
    "cabin_labeling": {
        "separators": ["-", "/", ":", " "],
    },
}


def load_matching_config() -> Dict[str, Any]:
    """Loads matching_config.yaml from disk with safe defaults."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            merged = {
                "faculty_matching": {
                    **_DEFAULT_CONFIG["faculty_matching"],
                    **(data.get("faculty_matching") or {}),
                },
                "cabin_labeling": {
                    **_DEFAULT_CONFIG["cabin_labeling"],
                    **(data.get("cabin_labeling") or {}),
                },
            }
            return merged
        except Exception:
            pass
    return {
        "faculty_matching": dict(_DEFAULT_CONFIG["faculty_matching"]),
        "cabin_labeling": dict(_DEFAULT_CONFIG["cabin_labeling"]),
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
