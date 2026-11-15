"""
Campus Query Normalizer & Typo Tolerance Engine
Provides fuzzy matching, typo auto-correction, and acronym expansion
for SRMIST degrees, departments, faculty names, and query intents.
"""

import re
import difflib
from typing import Dict, Any, Tuple, Optional, List

# Standard Intent Vocabulary (Canonical forms)
INTENT_VOCABULARY = {
    # Admission / Eligibility
    "eligibility": ["eligibility", "eligibity", "eligiblity", "eligibile", "eligible", "eligable", "eligibl", "elgible", "criteria", "criterias", "critiria"],
    "admission": ["admission", "admissions", "admision", "admissionss", "admit", "entry", "enrollment", "enrolment"],
    "cutoff": ["cutoff", "cut-off", "cuttoff", "cut off", "minimum marks", "min percentage", "percent", "percentage", "marks"],
    "entrance exam": ["entrance exam", "entrance", "srmjeee", "srmjee", "srmjeem", "neet", "jee main", "jee"],
    "fees": ["fee", "fees", "tuition", "tuition fee", "cost", "annual fee", "how much is fee", "fee structure"],
    
    # Faculty
    "faculty": ["faculty", "faculties", "prof", "professor", "professors", "profesor", "proffesor", "teacher", "instructor", "lecturer", "dean", "hod", "head"],
    "cabin": ["cabin", "office", "staff room", "chamber", "room number"],
    
    # Prerequisites
    "prerequisite": ["prerequisite", "prerequisites", "prereq", "prereqs", "pre-requisite", "dependency", "dependencies", "chains"],
    
    # Infrastructure / Rooms
    "room": ["room", "classroom", "classrooms", "lab", "hall", "auditorium"],
    "schedule": ["schedule", "timetable", "time-table", "timing", "slots", "slot", "occupancy", "booked"],
    "vacant": ["available", "vacant", "free", "empty", "unoccupied"],

    # Offerings & Programs
    "courses": ["courses", "course", "couses", "couse", "coruses", "coruse", "subjects", "subject"],
    "programs": ["programs", "program", "programmes", "programme", "porgrams", "porgram", "degrees", "degree"]
}

# Slang & Acronym Mappings to Full Academic Degree Titles
DEGREE_ACRONYM_MAP = {
    "btech": "B.Tech",
    "b.tech": "B.Tech",
    "b tech": "B.Tech",
    "b.e": "B.Tech",
    "mtech": "M.Tech",
    "m.tech": "M.Tech",
    "m tech": "M.Tech",
    "m.e": "M.Tech",
    "mba": "MBA",
    "m.b.a": "MBA",
    "mca": "MCA",
    "m.c.a": "MCA",
    "bba": "BBA",
    "b.b.a": "BBA",
    "bcom": "B.Com",
    "b.com": "B.Com",
    "bsc": "B.Sc",
    "b.sc": "B.Sc",
    "msc": "M.Sc",
    "m.sc": "M.Sc",
    "mbbs": "MBBS",
    "m.b.b.s": "MBBS",
    "bds": "BDS",
    "b.d.s": "BDS",
    "barch": "B.Arch",
    "b.arch": "B.Arch",
    "phd": "Ph.D",
    "ph.d": "Ph.D",
    "law": "Law",
    "llb": "LL.B",
    "ll.b": "LL.B",
    "b.a.,ll.b": "B.A.,LL.B",
    "b.b.a.,ll.b": "B.B.A.,LL.B"
}

# Discipline & Department Slang Mappings
DISCIPLINE_ACRONYM_MAP = {
    "cse": "Computer Science and Engineering",
    "cs": "Computer Science",
    "comp sci": "Computer Science and Engineering",
    "computing": "Computing Technologies",
    "ctech": "Computing Technologies",
    "cims": "Computational Intelligence",
    "ds": "Data Science",
    "data science": "Data Science",
    "ai ml": "Artificial Intelligence and Machine Learning",
    "aiml": "Artificial Intelligence and Machine Learning",
    "ai": "Artificial Intelligence",
    "ml": "Machine Learning",
    "cyber": "Cyber Security",
    "cyber security": "Cyber Security",
    "devsecops": "DevSecOps",
    "cloud": "Cloud Computing",
    "big data": "Big Data Analytics",
    "iot": "Internet of Things",
    "info tech": "Information Technology",
    "information technology": "Information Technology",
    "ece": "Electronics and Communication Engineering",
    "eee": "Electrical and Electronics Engineering",
    "mech": "Mechanical Engineering",
    "mechanical": "Mechanical Engineering",
    "civil": "Civil Engineering",
    "aero": "Aerospace Engineering",
    "aerospace": "Aerospace Engineering",
    "biotech": "Biotechnology",
    "biotechnology": "Biotechnology",
    "bme": "Biomedical Engineering",
    "agri": "Agriculture",
    "agriculture": "Agriculture",
    "horticulture": "Horticulture",
    "med": "Medicine",
    "medical": "Medicine",
    "nursing": "Nursing",
    "pharmacy": "Pharmacy",
    "physio": "Physiotherapy",
    "mgmt": "Management",
    "management": "Management",
    "finance": "Finance",
    "fintech": "Fintech"
}

# Campus Building Aliases
BUILDING_ALIAS_MAP = {
    "tech park": "TP",
    "techpark": "TP",
    "tp": "TP",
    "tp1": "TP",
    "tp2": "TP",
    "tp-1": "TP",
    "tp-2": "TP",
    "university building": "UB",
    "univ building": "UB",
    "ub": "UB",
    "main building": "UB",
    "bio engineering": "BEL",
    "bio-engineering": "BEL",
    "bio engg": "BEL",
    "bel": "BEL",
    "mechanical building": "MEB",
    "meb": "MEB",
    "electrical building": "ESB",
    "esb": "ESB",
    "civil building": "FMB",
    "fmb": "FMB",
    "law building": "SLB",
    "slb": "SLB",
    "management building": "MCB",
    "mcb": "MCB"
}

def correct_intent_tokens(query: str) -> str:
    """Corrects spelling mistakes in intent keywords (e.g. eligibity -> eligibility)."""
    words = query.split()
    corrected_words = []
    
    for w in words:
        w_lower = re.sub(r"[^\w]", "", w.lower())
        matched_canonical = None
        
        # 1. Exact match against known misspellings dictionary
        for canonical, variants in INTENT_VOCABULARY.items():
            if w_lower in variants:
                matched_canonical = canonical
                break
        
        # 2. Fuzzy match against canonical intents if word is at least 4 letters
        if not matched_canonical and len(w_lower) >= 4:
            for canonical, variants in INTENT_VOCABULARY.items():
                close = difflib.get_close_matches(w_lower, variants, n=1, cutoff=0.80)
                if close:
                    matched_canonical = canonical
                    break
        
        corrected_words.append(matched_canonical if matched_canonical else w)
        
    return " ".join(corrected_words)

def expand_acronyms(query: str) -> Tuple[str, Dict[str, Any]]:
    """Expands slang and abbreviations (e.g. btech cse -> B.Tech Computer Science and Engineering)."""
    detected_degree = None
    detected_discipline = None
    detected_building = None
    
    q_out = query
    
    # Building check
    for alias, code in BUILDING_ALIAS_MAP.items():
        pattern = r"\b" + re.escape(alias) + r"\b"
        if re.search(pattern, q_out, re.IGNORECASE):
            detected_building = code
            q_out = re.sub(pattern, code, q_out, flags=re.IGNORECASE)
            break
            
    # Degree check (case-insensitive word boundary)
    for slang, full_degree in DEGREE_ACRONYM_MAP.items():
        pattern = r"\b" + re.escape(slang) + r"\b"
        if re.search(pattern, q_out, re.IGNORECASE):
            detected_degree = full_degree
            q_out = re.sub(pattern, full_degree, q_out, flags=re.IGNORECASE)
            break
            
    # Discipline check
    for slang, full_discipline in DISCIPLINE_ACRONYM_MAP.items():
        pattern = r"\b" + re.escape(slang) + r"\b"
        if re.search(pattern, q_out, re.IGNORECASE):
            detected_discipline = full_discipline
            q_out = re.sub(pattern, full_discipline, q_out, flags=re.IGNORECASE)
            break

    metadata = {
        "detected_degree": detected_degree,
        "detected_discipline": detected_discipline,
        "detected_building": detected_building
    }
    
    return q_out, metadata

def normalize_user_query(raw_query: str) -> Tuple[str, Dict[str, Any]]:
    """
    Main entrypoint:
    1. Lowercase-aware typo correction of intent tokens
    2. Acronym and slang expansion
    3. Intent tag classification
    """
    cleaned = raw_query.strip()
    
    # 1. Spelling correction on intent tokens
    corrected = correct_intent_tokens(cleaned)
    
    # 2. Acronym expansion
    expanded, meta = expand_acronyms(corrected)
    
    q_lower = expanded.lower()
    
    # 3. Intent Classification Flags
    meta["is_admission_intent"] = any(w in q_lower for w in ["eligibility", "admission", "cutoff", "entrance exam", "srmjeee", "neet", "criteria", "qualify"])
    meta["is_fee_intent"] = any(w in q_lower for w in ["fee", "fees", "tuition", "cost", "how much is fee", "annual fee"])
    meta["is_faculty_intent"] = any(w in q_lower for w in ["professor", "faculty", "who is dr", "dr.", "dean", "hod", "cabin", "instructor", "teacher"])
    meta["is_room_intent"] = any(w in q_lower for w in ["available room", "vacant room", "free room", "classroom in", "room schedule", "classes scheduled"])
    meta["is_prereq_intent"] = any(w in q_lower for w in ["prerequisite", "dependency", "prereq", "eligible to take", "can i take", "passed"])
    
    # Synthesize clean canonical target query
    target_prog = []
    if meta.get("detected_degree"):
        target_prog.append(meta["detected_degree"])
    if meta.get("detected_discipline"):
        target_prog.append(meta["detected_discipline"])
    meta["canonical_program"] = " ".join(target_prog) if target_prog else None
    
    return expanded, meta

if __name__ == "__main__":
    test_queries = [
        "eligibity for btech",
        "cuttoff for cse",
        "how much fee for btech cse",
        "who is prof godfry",
        "who teaches in agri dept",
        "vacant classroom in tech park",
        "prereqs for cse301",
        "can i take cse201 after cse101"
    ]
    for t in test_queries:
        norm, m = normalize_user_query(t)
        print(f"Original: {t:<35} -> Normalized: {norm:<50} | Canonical Prog: {m.get('canonical_program')}")

