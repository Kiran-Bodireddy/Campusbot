"""
Local Qwen 2.5 Agent Harness
Executes tool-calling ReAct loop over governed campus tools with
Ollama local integration, provenance attribution, and fallback execution.
"""

import os
import json
import re
import requests
from typing import Dict, List, Any, Optional

from campus_knowledge_server.agent.prompts import SYSTEM_GROUNDING_PROMPT, TOOL_DEFINITIONS, INTENT_ROUTING_PROMPT
from campus_knowledge_server.agent.normalizer import normalize_user_query
from campus_knowledge_server.database.neo4j_client import get_graph_client
from campus_knowledge_server.tools.campus_tools import (
    CampusKnowledgeTools,
    CourseLookupRequest,
    PrerequisiteTreeRequest,
    PrerequisiteVerifyRequest,
    FacultyCourseRequest,
    FacultyProfileRequest,
    RoomScheduleRequest,
    AvailableRoomsRequest,
    SemanticSearchRequest,
    AdmissionEligibilityRequest,
    CampusStatisticsRequest,
    SemesterCurriculumRequest
)

def describe_cabin_location(cabin: str) -> str:
    """Decodes SRMIST cabin codes into human-readable building and floor descriptions."""
    if not cabin or cabin.strip().lower() in ("n/a", "none", "unknown"):
        return "Main Campus Faculty Staff Room"
    cabin_u = cabin.upper()
    bldg = ""
    floor = ""
    if "TP2" in cabin_u or "TP-2" in cabin_u:
        bldg = "Tech Park 2 (TP-2)"
    elif "TP" in cabin_u or "TP1" in cabin_u:
        bldg = "Tech Park (TP-1)"
    elif "UB" in cabin_u:
        bldg = "University Building (UB)"
    elif "BEL" in cabin_u or "BIO" in cabin_u:
        bldg = "Bioengineering Block (BEL)"
    elif "MEB" in cabin_u or "MECH" in cabin_u:
        bldg = "Mechanical Block (MEB)"
    elif "ESB" in cabin_u or "ELEC" in cabin_u:
        bldg = "Electrical Sciences Block (ESB)"
    elif "FMB" in cabin_u or "MGMT" in cabin_u:
        bldg = "Faculty of Management Building (FMB)"
    elif "SLB" in cabin_u or "LAW" in cabin_u:
        bldg = "School of Law Block (SLB)"
    elif "MCB" in cabin_u or "MED" in cabin_u:
        bldg = "Medical College Block (MCB)"

    m_fl = re.search(r"(\d+)(?:st|nd|rd|th)?\s*Floor", cabin, re.IGNORECASE)
    if m_fl:
        floor = f"Floor {m_fl.group(1)}"
    else:
        m_num = re.search(r"(?:FR|TP|UB)?[\s-]*(\d{3,4})", cabin_u)
        if m_num:
            digits = m_num.group(1)
            if len(digits) == 3:
                floor = f"Floor {digits[0]}"
            elif len(digits) == 4:
                floor = f"Floor {digits[:2]}"

    parts = [p for p in [bldg, floor] if p]
    if parts:
        return f"{cabin} ({', '.join(parts)})"
    return cabin

class ConversationMemory:
    """Lightweight session-scoped multi-turn conversation memory.
    Stores recent (query, tool_name, compact_answer) tuples per session_id
    so the agent can resolve pronouns and follow-up questions."""

    _sessions: Dict[str, List[Dict[str, str]]] = {}
    MAX_TURNS = 6  # Keep last 6 exchanges per session

    @classmethod
    def add_turn(cls, session_id: str, query: str, tool_name: str, answer_summary: str, entities: Optional[Dict[str, Any]] = None):
        if session_id not in cls._sessions:
            cls._sessions[session_id] = []
        cls._sessions[session_id].append({
            "query": query,
            "tool": tool_name,
            "answer": answer_summary[:200],
            "entities": entities or {}
        })
        # Trim to last MAX_TURNS
        if len(cls._sessions[session_id]) > cls.MAX_TURNS:
            cls._sessions[session_id] = cls._sessions[session_id][-cls.MAX_TURNS:]

    @classmethod
    def get_history(cls, session_id: str) -> List[Dict[str, str]]:
        return cls._sessions.get(session_id, [])

    @classmethod
    def get_last_entities(cls, session_id: str) -> Dict[str, Any]:
        """Returns entity context from the last turn (faculty name, course code, etc.)."""
        history = cls._sessions.get(session_id, [])
        if history:
            return history[-1].get("entities", {})
        return {}

    @classmethod
    def resolve_followup(cls, session_id: str, user_query: str) -> Optional[str]:
        """Resolves pronoun-based follow-up queries using conversation history.
        E.g. 'what is his email?' -> resolves 'his' to last faculty entity."""
        q_lower = user_query.lower().strip()
        pronouns = {"his", "her", "their", "them", "that", "this", "it", "its", "he", "she"}
        has_pronoun = any(p in q_lower.split() for p in pronouns)

        if not has_pronoun:
            return None

        last_ent = cls.get_last_entities(session_id)
        if not last_ent:
            return None

        # Faculty follow-up: resolve 'his/her email' -> 'email of Dr. X'
        if last_ent.get("faculty_name"):
            fname = last_ent["faculty_name"]
            if any(w in q_lower for w in ["email", "contact", "mail"]):
                return f"email of {fname}"
            if any(w in q_lower for w in ["cabin", "office", "room", "where", "located", "building", "block", "sit"]):
                return f"where is {fname} cabin"
            if any(w in q_lower for w in ["teach", "course", "subject"]):
                return f"what does {fname} teach"
            if any(w in q_lower for w in ["department", "dept"]):
                return f"department of {fname}"
            # Generic: just re-query the faculty name
            return f"tell me about {fname}"

        # Course follow-up: resolve 'its prerequisites' -> 'prerequisites for CODE'
        if last_ent.get("course_code"):
            ccode = last_ent["course_code"]
            if any(w in q_lower for w in ["prereq", "prerequisite", "dependency", "require"]):
                return f"prerequisites for {ccode}"
            if any(w in q_lower for w in ["teach", "instructor", "professor", "who"]):
                return f"who teaches {ccode}"
            if any(w in q_lower for w in ["credit", "detail", "about", "syllabus"]):
                return f"course details for {ccode}"
            return f"tell me about {ccode}"

        # Program follow-up
        if last_ent.get("program_name"):
            pname = last_ent["program_name"]
            if any(w in q_lower for w in ["fee", "cost", "tuition"]):
                return f"fees for {pname}"
            if any(w in q_lower for w in ["cutoff", "eligibility", "admission"]):
                return f"eligibility for {pname}"
            return f"tell me about {pname}"

        return None

    @classmethod
    def build_context_prompt(cls, session_id: str) -> str:
        """Builds a compact conversation context string for Qwen synthesis."""
        history = cls.get_history(session_id)
        if not history:
            return ""
        lines = ["Previous conversation context:"]
        for turn in history[-3:]:  # Last 3 turns only
            lines.append(f"- User asked: \"{turn['query']}\" -> Tool: {turn['tool']} -> Key info: {turn['answer'][:100]}")
        return "\n".join(lines)


class GovernedCampusAgent:
    def __init__(self, ollama_url: str = "http://localhost:11434", model_name: str = "qwen2.5:1.5b"):
        self.ollama_url = ollama_url
        self.model_name = model_name
        self.ollama_active = False
        try:
            r = requests.get(f"{self.ollama_url}/api/tags", timeout=1.0)
            if r.status_code == 200:
                self.ollama_active = True
        except Exception:
            self.ollama_active = False

        # Load Governance Policy (RBAC, row limits, hidden fields)
        policy_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "policy.yaml")
        self.policy = {}
        if os.path.exists(policy_path):
            try:
                import yaml
                with open(policy_path, "r", encoding="utf-8") as f:
                    self.policy = yaml.safe_load(f) or {}
            except Exception:
                self.policy = {}
        self.tool_map = {
            "lookup_course": lambda args: CampusKnowledgeTools.lookup_course(CourseLookupRequest(**args), caller="qwen_agent"),
            "get_prerequisite_tree": lambda args: CampusKnowledgeTools.get_prerequisite_tree(PrerequisiteTreeRequest(**args), caller="qwen_agent"),
            "verify_prerequisites": lambda args: CampusKnowledgeTools.verify_prerequisites(PrerequisiteVerifyRequest(**args), caller="qwen_agent"),
            "find_faculty_for_course": lambda args: CampusKnowledgeTools.find_faculty_for_course(FacultyCourseRequest(**args), caller="qwen_agent"),
            "lookup_faculty_profile": lambda args: CampusKnowledgeTools.lookup_faculty_profile(FacultyProfileRequest(**args), caller="qwen_agent"),
            "find_room_schedule": lambda args: CampusKnowledgeTools.find_room_schedule(RoomScheduleRequest(**args), caller="qwen_agent"),
            "find_available_rooms": lambda args: CampusKnowledgeTools.find_available_rooms(AvailableRoomsRequest(**args), caller="qwen_agent"),
            "search_courses_semantic": lambda args: CampusKnowledgeTools.search_courses_semantic(SemanticSearchRequest(**args), caller="qwen_agent"),
            "check_admission_eligibility": lambda args: CampusKnowledgeTools.check_admission_eligibility(AdmissionEligibilityRequest(**args), caller="qwen_agent"),
            "get_campus_statistics": lambda args: CampusKnowledgeTools.get_campus_statistics(CampusStatisticsRequest(**args), caller="qwen_agent"),
            "get_semester_curriculum": lambda args: CampusKnowledgeTools.get_semester_curriculum(SemesterCurriculumRequest(**args), caller="qwen_agent"),
        }

    def _select_tool_heuristically(self, user_query: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """High-precision fuzzy & normalized router tolerant of typos, slang, and misspellings."""
        norm_query, meta = normalize_user_query(user_query)
        q_lower = norm_query.lower()
        codes = re.findall(r"\b(?:21[A-Z]{2,4}\d{3}[A-Z]?|[A-Za-z]{3,4}\d{3})\b", user_query.upper())

        raw_lower = user_query.lower()

        # 0. Official Semester Curriculum & Implementation Plan
        # Matches queries like: '3rd sem subjects for cse', 'what courses in semester 4 AI', 'curriculum for mechanical', 'subjects in sem 1'
        sem_match = re.search(r"\b(?:sem(?:ester)?|term)\s*([1-8]|i|ii|iii|iv|v|vi|vii|viii)\b|\b([1-8]|1st|2nd|3rd|4th|5th|6th|7th|8th)\s*(?:sem(?:ester)?)\b", raw_lower, re.IGNORECASE)
        is_curriculum_intent = (
            sem_match is not None
            or any(w in raw_lower for w in ["curriculum", "implementation plan", "syllabus for sem", "subjects in sem", "courses in sem", "course plan", "semester plan", "sem wise", "sem-wise", "semester-wise", "semester wise"])
            or (any(w in raw_lower for w in ["subject", "course", "syllabus"]) and any(w in raw_lower for w in ["sem", "semester", "year 1", "year 2", "year 3", "year 4", "1st sem", "2nd sem", "3rd sem", "4th sem", "5th sem", "6th sem", "7th sem", "8th sem"]))
        )
        if is_curriculum_intent and not (len(codes) >= 2 and any(w in raw_lower for w in ["eligible", "passed", "take"])):
            sem_num = None
            if sem_match:
                s_tok = (sem_match.group(1) or sem_match.group(2) or "").lower()
                roman_or_ord = {
                    "1": 1, "1st": 1, "i": 1,
                    "2": 2, "2nd": 2, "ii": 2,
                    "3": 3, "3rd": 3, "iii": 3,
                    "4": 4, "4th": 4, "iv": 4,
                    "5": 5, "5th": 5, "v": 5,
                    "6": 6, "6th": 6, "vi": 6,
                    "7": 7, "7th": 7, "vii": 7,
                    "8": 8, "8th": 8, "viii": 8
                }
                sem_num = roman_or_ord.get(s_tok)

            # Identify target branch
            prog_cand = "Computer Science and Engineering"
            for p_code, full_p in [
                ("aiml", "Artificial Intelligence and Machine Learning"),
                ("ai", "Artificial Intelligence"),
                ("cse", "Computer Science and Engineering"),
                ("cs", "Computer Science and Engineering"),
                ("ece", "Electronics and Communication Engineering"),
                ("eee", "Electrical and Electronics Engineering"),
                ("mech", "Mechanical Engineering"),
                ("mechanical", "Mechanical Engineering"),
                ("aero", "Aerospace Engineering"),
                ("aerospace", "Aerospace Engineering"),
                ("auto", "Automobile Engineering"),
                ("automobile", "Automobile Engineering"),
                ("automotive", "Automotive Engineering"),
                ("biotech", "Biotechnology"),
                ("biotechnology", "Biotechnology"),
                ("bme", "Biomedical Engineering"),
                ("biomedical", "Biomedical Engineering"),
                ("civil", "Civil Engineering"),
                ("chemical", "Chemical Engineering"),
                ("csbs", "Computer Science and Business Systems"),
                ("it", "Information Technology"),
                ("iot", "Internet of Things"),
                ("data science", "Data Science"),
                ("cybersecurity", "Cybersecurity"),
                ("cyber", "Cybersecurity"),
                ("cloud", "Cloud Computing"),
                ("blockchain", "Blockchain Technology"),
                ("mechatronics", "Mechatronics Engineering"),
                ("nano", "Nanotechnology"),
                ("nanotechnology", "Nanotechnology")
            ]:
                if re.search(rf"\b{p_code}\b", raw_lower):
                    prog_cand = full_p
                    break
            else:
                cleaned = re.sub(r"(?i)\b(what|are|the|subjects?|courses?|syllabus|in|for|of|semester|sem|\d+(?:st|nd|rd|th)?|implementation|plan|curriculum|give|me|list|show|details?)\b", " ", user_query).strip()
                if len(cleaned) >= 3:
                    prog_cand = cleaned

            return "get_semester_curriculum", {
                "program_query": prog_cand,
                "semester": sem_num
            }

        # 0. Campus Overview & Aggregation Statistics (e.g. 'number of courses offered at srmist', 'how many programs', 'total faculty')
        is_stat_intent = (
            any(w in raw_lower or w in q_lower for w in [
                "number of", "how many", "total number", "count of", "total count", "statistics",
                "overview of", "summary of", "about srm", "about srmist", "tell me about srm",
                "tell me about srmist", "what is srmist", "what does srmist offer", "programs offered",
                "courses offered", "couses offered", "degrees offered", "courses at srm", "couses at srm",
                "programs at srm", "degrees at srm"
            ])
            or (
                any(w in raw_lower or w in q_lower for w in ["how many", "number of", "total", "count of"])
                and any(w in raw_lower or w in q_lower for w in ["course", "couse", "program", "faculty", "prof", "room", "student", "degree", "subject", "branch", "department"])
            )
        )
        if is_stat_intent:
            stat_cat = "all"
            if any(w in raw_lower or w in q_lower for w in ["faculty", "prof", "teacher", "staff", "lecturer"]):
                stat_cat = "faculty"
            elif any(w in raw_lower or w in q_lower for w in ["room", "classroom", "lab", "venue", "hall"]):
                stat_cat = "rooms"
            elif any(w in raw_lower or w in q_lower for w in ["course", "couse", "program", "degree", "subject", "curriculum", "branch"]):
                stat_cat = "programs"
            return "get_campus_statistics", {"category": stat_cat}

        # 1. Admission eligibility & Program Details (fees, intake, cutoffs, duration)
        # Matches queries like: 'eligibity for btech', 'how much fee for cse', 'admission for mbbs', 'cutoff for mba'
        is_admission_or_fee = meta.get("is_admission_intent") or meta.get("is_fee_intent") or any(
            w in q_lower for w in ["admission", "admissions", "cutoff", "entrance exam", "srmjeee", "neet", "fee", "fees", "tuition", "cost", "criteria", "qualify", "eligible", "eligibility"]
        )
        has_degree = (
            meta.get("detected_degree") is not None
            or meta.get("detected_discipline") is not None
            or any(deg in q_lower for deg in ["b.tech", "m.tech", "mbbs", "bds", "mba", "mca", "b.sc", "bba", "b.com", "b.arch", "law", "ph.d", "diploma", "computer science"])
        )

        if (is_admission_or_fee and (has_degree or not codes)) and not (len(codes) >= 2):
            pct_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent)", user_query, re.IGNORECASE)
            cand_pct = float(pct_match.group(1)) if pct_match else None
            is_reserved = any(cat in q_lower for cat in ["reserved", "sc", "st", "obc", "pwd"])
            cand_stream = None
            if "pcm" in q_lower: cand_stream = "PCM"
            elif "pcb" in q_lower: cand_stream = "PCB"
            elif "commerce" in q_lower: cand_stream = "Commerce"
            elif "arts" in q_lower or "humanities" in q_lower: cand_stream = "Arts"

            # Identify target degree / discipline using canonical program from normalizer
            if meta.get("canonical_program"):
                prog_clean = meta["canonical_program"]
            elif "computer science" in q_lower or "cse" in q_lower:
                prog_clean = "B.Tech Computer Science and Engineering"
            elif "biotech" in q_lower:
                prog_clean = "B.Tech Biotechnology"
            elif "mbbs" in q_lower:
                prog_clean = "MBBS"
            elif "bds" in q_lower:
                prog_clean = "BDS"
            elif "mba" in q_lower:
                prog_clean = "MBA"
            elif "mca" in q_lower:
                prog_clean = "MCA"
            elif "law" in q_lower or "llb" in q_lower:
                prog_clean = "Law"
            elif "b.arch" in q_lower:
                prog_clean = "B.Arch"
            elif "b.tech" in q_lower:
                prog_clean = "B.Tech"
            elif "m.tech" in q_lower:
                prog_clean = "M.Tech"
            else:
                prog_clean = re.sub(r"(?i)\b(what|is|the|are|admission|eligibility|requirements|criteria|for|in|can|i|get|with|\d+(?:\.\d+)?\s*%|percent|aggregate|marks|sc|st|obc|reserved|candidate|category|student|degree|program|entrance|exams?|minimum|percentage|required|12th|qualifying|exam|fee|fees|cost|tuition|annual)\b", " ", norm_query)
                prog_clean = re.sub(r"[^\w\s\.]", " ", prog_clean)
                prog_clean = re.sub(r"\s+", " ", prog_clean).strip()
                if not prog_clean:
                    prog_clean = "B.Tech"

            return "check_admission_eligibility", {
                "program_query": prog_clean,
                "candidate_percentage": cand_pct,
                "is_reserved_category": is_reserved,
                "candidate_stream": cand_stream
            }

        # 1. Course Prerequisite eligibility check (e.g., 'passed PHY101 take CSE301', 'eligible for CSE201')
        if any(w in q_lower for w in ["eligible", "can i take", "can a student", "passed", "take"]) and len(codes) >= 2:
            target = codes[-1]
            completed = codes[:-1]
            return "verify_prerequisites", {"target_course": target, "completed_courses": completed}

        # 2. Prerequisite dependency tree
        if (meta.get("is_prereq_intent") or any(w in q_lower for w in ["prereq", "dependency", "leads to", "prerequisites for"])) and codes:
            return "get_prerequisite_tree", {"course_code": codes[0], "max_depth": 3}

        # 3. Faculty teaching a specific course
        q_raw_lower = user_query.lower()
        if codes and (
            any(w in q_raw_lower for w in ["who teaches", "instructor", "instruct", "professor for", "professors for", "professors are assigned", "teach", "faculty for", "faculty teaching", "assigned to"])
            or any(w in q_lower for w in ["who teaches", "instructor", "instruct", "professor for", "professors are assigned", "teach"])
            or (meta.get("is_faculty_intent") and not any(w in q_raw_lower for w in ["dr.", "dr ", "profile of", "cabin", "qualifications"]))
        ):
            return "find_faculty_for_course", {"course_code": codes[0]}

        # 3b. Building info intent — MUST come before room schedule to prevent misroutes
        # Matches: "tp1 building", "tech park", "tp2 building", "tell me about ub", "university building", etc.
        BUILDING_ALIASES = {
            "tp":  "TP",  "tp1": "TP",  "tp-1": "TP", "tech park": "TP",  "tech park 1": "TP",  "techpark": "TP",
            "tp2": "TP2", "tp-2": "TP2", "tech park 2": "TP2", "techpark 2": "TP2",
            "ub":  "UB",  "university building": "UB",  "university block": "UB",
            "bel": "BEL", "bioengineering": "BEL", "bio engg": "BEL", "bio engineering": "BEL",
            "meb": "MEB", "mechanical block": "MEB", "mechanical engineering block": "MEB",
            "esb": "ESB", "electrical block": "ESB", "electrical sciences": "ESB",
            "fmb": "FMB", "management block": "FMB", "management building": "FMB",
            "slb": "SLB", "law block": "SLB", "school of law": "SLB", "law building": "SLB",
            "mcb": "MCB", "medical block": "MCB", "medical college": "MCB",
        }
        BUILDING_KEYWORDS = [
            "tech park", "university building", "university block", "bioengineering block",
            "mechanical block", "electrical block", "management block", "law block", "medical block",
            "tp1 building", "tp2 building", "tp-1 building", "tp-2 building", "about tp", "about ub", "about bel",
            "tp building", "ub building", "bel building"
        ]
        is_faculty_clue = any(w in raw_lower for w in ["dr.", "dr ", "professor", "prof.", "prof ", "faculty", "who is", "who's", "where is", "where's", "which building is", "what building is", "where does", "cabin", "staff room"])
        is_building_intent = any(w in raw_lower for w in BUILDING_KEYWORDS) and not is_faculty_clue
        # Also detect bare building code like "tp1", "tp 1", "TP-1", "ub" with/without qualifiers
        bare_bldg = re.match(
            r"^\s*(tp-?[12]?|tp2|tech\s*park\s*[12]?|ub|university\s*build|bel|meb|esb|fmb|slb|mcb)"
            r"[\s\-]*(building|block|info|details|about|rooms?)?\s*$",
            raw_lower
        )
        # Also handle uppercase patterns: "TP-1 rooms", "TP-2", "UB info"
        if not bare_bldg:
            bare_bldg = re.match(
                r"^\s*(TP-?[12]?|TP2?|UB|BEL|MEB|ESB|FMB|SLB|MCB)"
                r"[\s\-]*(building|block|info|details|about|rooms?)?\s*$",
                user_query.strip()
            )
        if is_building_intent or bare_bldg:
            detected_code = "TP"
            combined = raw_lower
            for alias, code in BUILDING_ALIASES.items():
                if alias in combined:
                    detected_code = code
                    break
            else:
                b_match2 = re.search(r"\b(TP2|TP|UB|BEL|MEB|ESB|FMB|SLB|MCB)\b", user_query.upper())
                if b_match2:
                    detected_code = b_match2.group(1)
            # Route to find_available_rooms which lists all rooms for this building
            day_match = re.search(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", user_query, re.IGNORECASE)
            day_val = day_match.group(1).capitalize() if day_match else "Monday"
            slot_match = re.search(r"\b(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})\b", user_query)
            slot_val = slot_match.group(1).replace(" ", "") if slot_match else "08:45-09:35"
            cap_match = re.search(r"\b(?:capacity|cap|seats?|students?)\s*(?:of\s*)?(\d{1,3})\b|\b(?:for\s*)?(\d{1,3})\s*(?:seats?|students?|capacity)\b", user_query, re.IGNORECASE)
            cap_val = int(cap_match.group(1) or cap_match.group(2)) if cap_match else 10
            return "find_available_rooms", {"building_code": detected_code, "day": day_val, "slot": slot_val, "min_capacity": cap_val}

        # 4. Room schedule / occupancy (e.g. TP-501, TP501, UB102, TP 201)
        r_match = re.search(r"\b(TP2|TP|UB|BEL|MEB|ESB|FMB|SLB|MCB)[\s-]*(\d{3})\b", user_query.upper())
        if r_match:
            room_id = f"{r_match.group(1)}-{r_match.group(2)}"
            day_match = re.search(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", user_query, re.IGNORECASE)
            day_val = day_match.group(1).capitalize() if day_match else None
            return "find_room_schedule", {"room_id": room_id, "day_of_week": day_val}

        # 5. Vacant / available rooms in building
        if meta.get("is_room_intent") or any(w in q_lower for w in ["available room", "available classroom", "free room", "vacant", "classroom in", "rooms in", "room in"]):
            b_code = meta.get("detected_building") or "TP"
            b_match = re.search(r"\b(TP2|TP|UB|BEL|MEB|ESB|FMB|SLB|MCB)\b", norm_query, re.IGNORECASE)
            if b_match:
                b_code = b_match.group(1).upper()
            day_match = re.search(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", user_query, re.IGNORECASE)
            day_val = day_match.group(1).capitalize() if day_match else "Monday"
            slot_match = re.search(r"\b(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})\b", user_query)
            slot_val = slot_match.group(1).replace(" ", "") if slot_match else "08:45-09:35"
            cap_match = re.search(r"\b(?:capacity|cap|seats?|students?)\s*(?:of\s*)?(\d{1,3})\b|\b(?:for\s*)?(\d{1,3})\s*(?:seats?|students?|capacity)\b", user_query, re.IGNORECASE)
            cap_val = int(cap_match.group(1) or cap_match.group(2)) if cap_match else 30
            return "find_available_rooms", {"building_code": b_code, "day": day_val, "slot": slot_val, "min_capacity": cap_val}

        # 6. Faculty profile & research lookup
        COMMON_GREETINGS_AND_NON_NAMES = {
            "hey", "hello", "hi", "howdy", "greetings", "good morning", "good afternoon", "good evening",
            "sup", "yo", "namaste", "help", "who are you", "what are you", "what can you do", "test", "ok",
            "okay", "yes", "no", "thanks", "thank you", "bye", "good", "bad", "fine", "cool", "why", "what",
            "how", "who", "where", "when", "srm", "srmist", "campus", "college", "department",
            "sports", "facilities", "hostel", "mess", "canteen", "library", "wifi", "portal", "attendance",
            "placement", "placements", "jobs", "fees", "fee", "cost", "apply", "admission", "cut off",
            "ai", "ml", "dl", "ds", "cse", "ece", "eee", "it", "mech", "civil", "iot", "cyber", "cloud", "data", "math", "physics", "chemistry"
        }
        CAMPUS_LOCATION_TERMS = {
            "tech park", "tp1", "tp2", "tp-1", "tp-2", "university building",
            "bioengineering", "mechanical block", "electrical block", "management block",
            "law block", "medical college", "campus", "building", "block", "hostel",
            "canteen", "library", "lab", "auditorium", "ground", "playground"
        }
        is_greeting_or_non_name = (
            q_lower.strip() in COMMON_GREETINGS_AND_NON_NAMES
            or q_lower.strip() in CAMPUS_LOCATION_TERMS
            or any(q_lower.strip().startswith(g) for g in ["hey ", "hello ", "hi ", "how are you"])
        )

        words = user_query.strip().split()
        raw_query_lower = user_query.lower()
        is_faculty_title_or_intent = (
            meta.get("is_faculty_intent")
            or any(w in raw_query_lower for w in [
                "dr.", "dr ", "professor", "prof.", "prof ", "faculty", "research", "hod", "dean",
                "who is", "who's", "where is", "where's", "where does", "which building is", "what building is", "which block is", "tell me about", "tell us about", "can you tell me about", "can u tell me about",
                "know about", "details of", "profile of", "cabin of", "email of", "contact of", "cabin", "staff room"
            ])
            or any(w in q_lower for w in ["dr.", "dr ", "professor", "prof.", "faculty", "cabin", "staff room"])
        )
        is_solitary_name = (
            len(words) <= 3
            and all(len(w) >= 3 for w in words)
            and not codes 
            and not is_admission_or_fee 
            and not any(w in q_lower for w in ["room", "course", "prereq", "syllabus", "building", "class", "schedule"])
            and not any(w.lower() in COMMON_GREETINGS_AND_NON_NAMES for w in words)
        )
        is_faculty_query = (
            not is_greeting_or_non_name
            and not (codes and not any(w in raw_query_lower for w in ["dr.", "dr ", "professor", "prof.", "prof ", "hod", "dean", "cabin"]))
            and (is_faculty_title_or_intent or is_solitary_name)
        )
        if is_faculty_query:
            m = re.search(r"(?:dr\.?|professor|prof\.?|dean|faculty)\s*([A-Za-z\.\s]+)", user_query, re.IGNORECASE)
            if m:
                raw_name = m.group(1).strip()
                clean_name = re.sub(r"(?i)\b(?:and|his|her|qualifications|about|tell|me|who|is|what|department|college|cabin)\b.*", "", raw_name).strip()
            else:
                cleaned = re.sub(r"(?i)\b(?:can\s+(?:you|u)\s+)?(?:please\s+)?(?:tell\s+(?:me|us)\s+about|know\s+about|information\s+about|who\s+is|who\'s|where\s+is|where\s+does|which\s+building\s+is|what\s+building\s+is|which\s+block\s+is|cabin\s+of|profile\s+of|details\s+of|contact\s+of|email\s+of|about)\b", "", user_query)
                clean_name = re.sub(r"(?i)\b(?:and|his|her|qualifications|about|department|college|cabin|sit|stay|work|located|in|at)\b.*", "", cleaned).strip()
            clean_name = re.sub(r"^[^\w]+|[^\w]+$", "", clean_name).strip()
            if clean_name:
                return "lookup_faculty_profile", {"faculty_name": clean_name}

        # 7. Direct course lookup by code
        if codes:
            return "lookup_course", {"query": codes[0]}

        # 8. Semantic course discovery (only if query contains course or subject-related keywords)
        COURSE_TOPIC_HINTS = {
            "course", "courses", "syllabus", "subject", "curriculum", "learn", "study", "topic",
            "ai", "ml", "data science", "cloud", "security", "database", "python", "java", "network",
            "physics", "chemistry", "math", "algorithms", "software", "circuits", "robotics", "web",
            "operating system", "compiler", "electronics", "mechanics"
        }
        if any(h in q_lower or h in raw_lower for h in COURSE_TOPIC_HINTS):
            return "search_courses_semantic", {"query": user_query, "top_k": 5}

        # Otherwise, do NOT blindly search courses; return None to let Qwen LLM parse or clarify
        return None

    def _fast_path_match(self, user_query: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """Sub-millisecond fast-path router for direct course codes and room identifiers (~1ms)."""
        q_strip = user_query.strip().upper()
        # Direct course code lookup: e.g. "21CSC206T", "21CSO451T", "CSE101" or "LOOKUP 21CSC206T"
        m_code = re.match(r"^(?:LOOKUP\s+)?((?:21[A-Z]{2,4}\d{3}[A-Z]?)|(?:[A-Z]{3,4}\d{3}))$", q_strip)
        if m_code:
            return "lookup_course", {"query": m_code.group(1)}
        # Direct room schedule lookup: e.g. "TP-101" or "SCHEDULE TP-101"
        m_room = re.match(r"^(?:SCHEDULE\s+)?([A-Z]{2,3}-\d{3})$", q_strip)
        if m_room:
            return "find_room_schedule", {"room_id": m_room.group(1)}
        return None

    def _select_tool_with_llm(self, user_query: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """
        Two-Stage Semantic Intent Parser using Qwen 2.5 (JSON Mode).
        Stage 1: Qwen understands intent category and what the user really wants.
        Stage 2: Qwen maps intent to the correct governed tool with parameters.
        Handles typos, slang, abbreviations, and casual phrasing naturally.
        """
        try:
            prompt = f"{INTENT_ROUTING_PROMPT}\n\nUser Question: {user_query}\n\nJSON Output:"
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                    "options": {
                        "temperature": 0.0,
                        "top_p": 0.9
                    }
                },
                timeout=20.0
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_text = data.get("response", "{}")
                parsed = json.loads(raw_text)
                tool = parsed.get("tool")
                params = parsed.get("parameters", {})

                # Log intent understanding for traceability
                intent_cat = parsed.get("intent_category", "?")
                intent_desc = parsed.get("intent_description", "")
                if intent_cat and intent_desc:
                    import logging
                    logging.getLogger("qwen_agent").info(
                        f"[Qwen Intent] Category={intent_cat} | {intent_desc} | tool={tool}"
                    )

                if tool and tool in self.tool_map:
                    # Parameter normalization & tolerance across variations
                    if tool == "check_admission_eligibility":
                        if "program_query" not in params and "program_name" in params:
                            params["program_query"] = params.pop("program_name")
                        if not params.get("program_query"):
                            params["program_query"] = "B.Tech"
                    elif tool == "lookup_faculty_profile":
                        if "faculty_name" not in params and "name_query" in params:
                            params["faculty_name"] = params.pop("name_query")
                        # Strip honorifics that Qwen might include
                        name = params.get("faculty_name", "")
                        name = re.sub(r"(?i)^(dr\.?\s*|prof\.?\s*|professor\s*|mr\.?\s*|ms\.?\s*|mrs\.?\s*)", "", name).strip()
                        if name:
                            params["faculty_name"] = name
                    elif tool == "find_available_rooms":
                        if "building_code" not in params:
                            params["building_code"] = "TP"
                        # Normalize building code aliases Qwen might use
                        bc = params["building_code"].upper().strip()
                        BLDG_NORMALIZE = {"TP1": "TP", "TECHPARK": "TP", "TECH PARK": "TP",
                                          "TP-1": "TP", "TP-2": "TP2", "TECH PARK 2": "TP2",
                                          "UNIVERSITY": "UB", "UNIVERSITY BUILDING": "UB"}
                        params["building_code"] = BLDG_NORMALIZE.get(bc, bc)
                    elif tool == "find_room_schedule":
                        if "room_id" not in params and "room" in params:
                            params["room_id"] = params.pop("room")
                        # Normalize room_id: TP101 -> TP-101
                        if "room_id" in params:
                            rid = params["room_id"].upper().strip()
                            rid = re.sub(r"([A-Z]{2,3})\s*-?\s*(\d{3})", r"\1-\2", rid)
                            params["room_id"] = rid
                    elif tool == "lookup_course":
                        if "query" not in params and "course_code" in params:
                            params["query"] = params.pop("course_code")
                        elif "query" not in params and "course" in params:
                            params["query"] = params.pop("course")
                    elif tool == "verify_prerequisites":
                        if isinstance(params.get("completed_courses"), str):
                            params["completed_courses"] = [params["completed_courses"]]
                    elif tool == "get_campus_statistics":
                        if "category" not in params:
                            params["category"] = "all"
                    elif tool == "get_semester_curriculum":
                        if "program_query" not in params:
                            params["program_query"] = "Computer Science and Engineering"
                    return tool, params
        except Exception:
            pass
        return None

    def _federated_cross_entity_search(
        self,
        user_query: str,
        role: str = "student",
        engine_mode: str = "neo4j",
        attempted_tool: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Federated cross-entity graph scanner.
        Executes an instant, multi-domain search across all 4 catalogs
        (Faculty, Courses, Classrooms/Buildings, Programs) to eliminate single-database tunnel vision.
        """
        client = get_graph_client()
        matched = client.find_entities(user_query, max_per_type=5)

        fac_list = matched.get("faculty", [])
        course_list = matched.get("courses", [])
        room_list = matched.get("rooms", [])
        prog_list = matched.get("programs", [])
        bldg_list = matched.get("buildings", [])

        # If an attempted tool failed to find data, exclude that empty category
        if attempted_tool == "lookup_faculty_profile":
            fac_list = []
        elif attempted_tool in ("lookup_course", "search_courses_semantic"):
            course_list = []
        elif attempted_tool == "find_room_schedule":
            room_list = []
        elif attempted_tool == "check_admission_eligibility":
            prog_list = []

        total_hits = len(fac_list) + len(course_list) + len(room_list) + len(prog_list) + len(bldg_list)
        if total_hits == 0:
            return None

        # Determine non-empty categories
        active_cats = []
        if fac_list:
            active_cats.append("faculty")
        if course_list:
            active_cats.append("courses")
        if prog_list:
            active_cats.append("programs")
        if room_list or bldg_list:
            active_cats.append("rooms")

        # Single category match: synthesize grounded answer using specialized formatter
        if len(active_cats) == 1:
            cat = active_cats[0]
            if cat == "faculty":
                tool_name = "lookup_faculty_profile"
                tool_res = {"faculty": fac_list, "query": user_query, "status": "SUCCESS"}
                answer = self._synthesize_grounded_answer(user_query, tool_name, tool_res)
                return {
                    "user_query": user_query,
                    "tool_selected": tool_name,
                    "parameters": {"faculty_name": fac_list[0]["name"]},
                    "status": "SUCCESS",
                    "suggestions": [
                        f"Who teaches in {fac_list[0].get('short_department', 'Computing Technologies')}?",
                        "Find available rooms in Tech Park",
                        "Eligibility for B.Tech"
                    ],
                    "tool_result": tool_res,
                    "answer": answer,
                    "grounded": True,
                    "intent_source": "Federated Cross-Entity Search (Graph Fallback)",
                    "engine_mode": engine_mode,
                    "source": "SRMIST Faculty Directory",
                    "synthesizer": "Governed Campus Engine"
                }
            elif cat == "courses":
                tool_name = "lookup_course"
                tool_res = {"courses": course_list, "query": user_query, "status": "SUCCESS"}
                answer = self._synthesize_grounded_answer(user_query, tool_name, tool_res)
                c_code = course_list[0].get("code", "")
                return {
                    "user_query": user_query,
                    "tool_selected": tool_name,
                    "parameters": {"query": c_code},
                    "status": "SUCCESS",
                    "suggestions": [
                        f"Prerequisites for {c_code}",
                        f"Who teaches {c_code}?",
                        "Find available rooms in Tech Park"
                    ],
                    "tool_result": tool_res,
                    "answer": answer,
                    "grounded": True,
                    "intent_source": "Federated Cross-Entity Search (Graph Fallback)",
                    "engine_mode": engine_mode,
                    "source": "SRMIST Academic Regulations 2021",
                    "synthesizer": "Governed Campus Engine"
                }
            elif cat == "programs":
                tool_name = "check_admission_eligibility"
                tool_res = {"eligible": True, "evaluated_programs": prog_list, "query": user_query, "status": "SUCCESS"}
                answer = self._synthesize_grounded_answer(user_query, tool_name, tool_res)
                return {
                    "user_query": user_query,
                    "tool_selected": tool_name,
                    "parameters": {"program_query": prog_list[0]["program_name"]},
                    "status": "SUCCESS",
                    "suggestions": [
                        f"B.Tech CSE Semester 3",
                        "Eligibility for B.Tech",
                        "Course details for 21CSC206T"
                    ],
                    "tool_result": tool_res,
                    "answer": answer,
                    "grounded": True,
                    "intent_source": "Federated Cross-Entity Search (Graph Fallback)",
                    "engine_mode": engine_mode,
                    "source": "SRMIST Admissions Directorate",
                    "synthesizer": "Governed Campus Engine"
                }
            elif cat == "rooms":
                if room_list:
                    r = room_list[0]
                    tool_name = "find_room_schedule"
                    tool_res = {
                        "room_id": r["id"],
                        "room_type": r.get("type", "Classroom"),
                        "capacity": r.get("capacity", 60),
                        "building_code": r.get("building_code", "TP"),
                        "schedules": client._schedules_by_room.get(r["id"], [])[:10],
                        "source": "SRMIST Room Allocation Master"
                    }
                    answer = self._synthesize_grounded_answer(user_query, tool_name, tool_res)
                    return {
                        "user_query": user_query,
                        "tool_selected": tool_name,
                        "parameters": {"room_id": r["id"]},
                        "status": "SUCCESS",
                        "suggestions": [
                            f"Find available rooms in {r.get('building_code', 'TP')}",
                            "Who teaches 21CSC206T?",
                            "Eligibility for B.Tech"
                        ],
                        "tool_result": tool_res,
                        "answer": answer,
                        "grounded": True,
                        "intent_source": "Federated Cross-Entity Search (Graph Fallback)",
                        "engine_mode": engine_mode,
                        "source": "SRMIST Room Allocation Master",
                        "synthesizer": "Governed Campus Engine"
                    }
                else:
                    b = bldg_list[0]
                    b_code = b.get("code", "TP")
                    tool_name = "find_available_rooms"
                    tool_res = {
                        "building_code": b_code,
                        "day": "Monday",
                        "slot": "08:45-09:35",
                        "min_capacity": 10,
                        "available_count": 20,
                        "available_rooms": [r for r in client.in_memory_data.get("rooms", []) if r.get("building_code") == b_code][:20],
                        "source": "SRMIST Space Allocation Matrix"
                    }
                    answer = self._synthesize_grounded_answer(user_query, tool_name, tool_res)
                    return {
                        "user_query": user_query,
                        "tool_selected": tool_name,
                        "parameters": {"building_code": b_code},
                        "status": "SUCCESS",
                        "suggestions": [
                            f"Schedule for {b_code}-101",
                            "Who teaches 21CSC206T?",
                            "Eligibility for B.Tech"
                        ],
                        "tool_result": tool_res,
                        "answer": answer,
                        "grounded": True,
                        "intent_source": "Federated Cross-Entity Search (Graph Fallback)",
                        "engine_mode": engine_mode,
                        "source": "SRMIST Space Allocation Matrix",
                        "synthesizer": "Governed Campus Engine"
                    }

        # Multi-category match: Query spans multiple domains (e.g. "AI", "Cloud", "Computing")
        md_lines = [
            f"### SRMIST Campus Knowledge Graph: Cross-Entity Results for '{user_query}'\n",
            "I checked across all campus catalogs (Programs, Courses, Faculty, and Classrooms) and found matching records:\n"
        ]

        if prog_list:
            md_lines.append("#### Academic Programs & Degrees")
            for p in prog_list[:3]:
                fee_val = p.get('annual_fee_inr')
                fee_str = f"INR {fee_val:,}/yr" if fee_val else "Official Norms"
                dur = p.get('duration', '4 Years')
                min_pct = p.get('min_percentage_general', p.get('min_percentage', 60.0))
                md_lines.append(f"- **[Program: {p['program_name']}]** ({p.get('degree', 'Degree')})")
                md_lines.append(f"  - Minimum Criteria: {min_pct}% in qualifying exam | Duration: {dur} | Fee: {fee_str}")
            md_lines.append("")

        if course_list:
            md_lines.append("#### Curriculum & Courses")
            for c in course_list[:3]:
                c_code = c.get('code', '')
                c_name = c.get('name', '')
                c_cr = c.get('credits', 3)
                c_dept = c.get('department', 'Engineering')
                md_lines.append(f"- **[{c_code} - {c_name}]** ({c_cr} Credits, {c_dept})")
            md_lines.append("")

        if fac_list:
            md_lines.append("#### Faculty & Researchers")
            for f in fac_list[:3]:
                f_name = f.get('name', '')
                f_desig = f.get('designation', 'Faculty')
                f_dept = f.get('department', '')
                f_cabin = describe_cabin_location(f.get('cabin', 'Staff Room'))
                f_email = f.get('email', '')
                md_lines.append(f"- **[Faculty: {f_name}]**: {f_desig}, {f_dept}")
                md_lines.append(f"  - Cabin: **{f_cabin}** | Email: `{f_email}`")
            md_lines.append("")

        if room_list:
            md_lines.append("#### Campus Classrooms & Spaces")
            for r in room_list[:3]:
                md_lines.append(f"- **[Room: {r.get('id')}]**: {r.get('type', 'Classroom')}, Capacity: {r.get('capacity', 'N/A')}, Building: {r.get('building_code', '')}")
            md_lines.append("")

        md_lines.append("Would you like more details on any specific program, course, faculty member, or classroom above?")

        answer = "\n".join(md_lines)
        return {
            "user_query": user_query,
            "tool_selected": "federated_cross_entity_search",
            "parameters": {"query": user_query},
            "status": "SUCCESS",
            "suggestions": [
                f"Course details for {course_list[0]['code']}" if course_list else "Course details for 21CSC206T",
                f"Cabin of {fac_list[0]['name']}" if fac_list else "Find available rooms in Tech Park",
                "Eligibility for B.Tech"
            ],
            "tool_result": {
                "type": "federated_cross_entity_discovery",
                "query": user_query,
                "programs": prog_list,
                "courses": course_list,
                "faculty": fac_list,
                "rooms": room_list,
                "buildings": bldg_list
            },
            "answer": answer,
            "grounded": True,
            "intent_source": "Federated Cross-Entity Search (Graph Fallback)",
            "engine_mode": engine_mode,
            "source": "SRMIST Unified Knowledge Graph",
            "synthesizer": "Governed Multi-Entity Engine"
        }

    def execute_query(self, user_query: str, use_llm_synthesis: bool = True, role: str = "student", engine_mode: str = "neo4j", session_id: str = "") -> Dict[str, Any]:
        """
        Executes a user question through the governed Model-First pipeline:
        0. Multi-Turn Follow-Up Resolution (pronoun & context)
        1. Interactive Conversational & Greeting Handler
        2. Fast-Path Bypass for direct identifiers (~1ms)
        3. High-Speed Fuzzy Normalized Router (~8ms)
        4. Model-First Semantic Intent Parsing via Qwen 2.5
        5. Role-Based Access Control (RBAC) & AST Security Check (via policy.yaml)
        6. Governed Tool Execution with Schema Validation
        7. Field Masking & Row Limits by Role (Student/Faculty/Admin)
        8. Grounded Answer Synthesis with Entity Citations
        """
        # -1. Multi-Turn Follow-Up Resolution
        original_query = user_query
        if session_id:
            resolved = ConversationMemory.resolve_followup(session_id, user_query)
            if resolved:
                user_query = resolved
        # 0. Zero-Trust AST Security Guardrail: Intercept destructive operations and injections (~1ms)
        from campus_knowledge_server.security.ast_validator import ASTSecurityValidator
        from campus_knowledge_server.security.audit import get_audit_logger

        is_adversarial, violation_reason = ASTSecurityValidator.is_adversarial_or_destructive(user_query)
        if is_adversarial:
            audit_logger = get_audit_logger()
            audit_logger.log_event(
                caller="web_user",
                tool_name="ast_security_interception",
                parameters={"query": user_query},
                status="POLICY_VIOLATION",
                latency_ms=1.1,
                result_count=0,
                violation_reason=f"Access Policy Violation: {violation_reason}",
                role=role
            )
            return {
                "user_query": user_query,
                "tool_selected": "ast_security_interception",
                "parameters": {"query": user_query},
                "status": "POLICY_VIOLATION",
                "answer": (
                    f"Access Policy Violation: Destructive operations or unauthorized mutations "
                    f"('{user_query.strip()}') are strictly prohibited by the AST Security Guardrail and RBAC policy. "
                    f"This security interception has been logged to the cryptographic audit ledger."
                ),
                "grounded": False,
                "engine_mode": engine_mode,
                "intent_source": "AST Security Guardrail (~1ms)",
                "source": "Zero-Trust Security Boundary",
                "synthesizer": "AST Security Policy Enforcer"
            }

        clean_input = re.sub(r"[^\w\s]", " ", user_query.strip().lower())
        input_words = clean_input.split()

        GREETINGS = {"hey", "hello", "hi", "howdy", "greetings", "good morning", "good afternoon", "good evening", "sup", "yo", "namaste"}
        CONVERSATIONAL_PHRASES = [
            "help", "can you help", "who are you", "what are you", "what can you do", "what do you do",
            "how to use", "how do i use", "how does this work", "i want to ask", "i have a question",
            "tell me something", "features", "menu", "options", "commands", "start", "guide", "assist", "instructions"
        ]

        is_greeting = clean_input in GREETINGS or (input_words and input_words[0] in GREETINGS and len(input_words) <= 3)
        is_help = any(p in clean_input for p in CONVERSATIONAL_PHRASES) or (clean_input in {"help", "start", "hi", "hey"})

        if is_greeting or is_help:
            return {
                "user_query": user_query,
                "tool_selected": "interactive_assistant",
                "parameters": {},
                "status": "INTERACTIVE_GREETING",
                "tool_result": {
                    "type": "interactive_guidance",
                    "suggestions": [
                        "B.Tech CSE Semester 3",
                        "Eligibility for B.Tech",
                        "Course details for 21CSC206T",
                        "Find available rooms in Tech Park"
                    ]
                },
                "answer": (
                    "Hello! I am the SRMIST Campus Knowledge Assistant.\n\n"
                    "I provide verified facts across the campus graph. What would you like to look up?\n\n"
                    "- Admissions: Check cutoffs and requirements (e.g., 'eligibility for btech' or 'fees for cse')\n"
                    "- Curriculum: View semester courses (e.g., 'B.Tech CSE Semester 3' or 'AI Semester 4')\n"
                    "- Courses: Check course details and prerequisites (e.g., 'Course details for 21CSC206T' or 'Prerequisites for 21CSO451T')\n"
                    "- Classrooms: Find vacant rooms or view timetables (e.g., 'Find available rooms in Tech Park')"
                ),
                "grounded": True,
                "intent_source": "Interactive Conversational Engine",
                "source": "SRMIST Campus Knowledge Assistant",
                "synthesizer": "Interactive Campus Assistant"
            }

        # 1. Fast-path for exact course codes / room codes (~1ms)
        tool_call = self._fast_path_match(user_query)
        intent_source = "Fast-Path Matcher (~1ms)" if tool_call else None

        # 2. High-Speed Fuzzy Normalized Router (~8ms)
        if not tool_call:
            tool_call = self._select_tool_heuristically(user_query)
            if tool_call:
                intent_source = "High-Speed Normalized Router (~8ms)"

        # 3. Model-First Semantic Intent Understanding via Qwen 2.5 (for complex unmapped queries)
        if not tool_call and self.ollama_active:
            tool_call = self._select_tool_with_llm(user_query)
            if tool_call:
                intent_source = "Qwen 2.5 Semantic Intent Parser (JSON Mode)"

        if not tool_call:
            # Fallback to federated cross-entity search across all 4 catalogs
            fed_res = self._federated_cross_entity_search(user_query, role=role, engine_mode=engine_mode)
            if fed_res:
                return fed_res

            return {
                "user_query": user_query,
                "status": "CLARIFICATION_NEEDED",
                "tool_selected": "interactive_clarification",
                "parameters": {"query": user_query},
                "tool_result": {
                    "type": "clarification",
                    "suggestions": [
                        "B.Tech CSE Semester 3",
                        "Eligibility for B.Tech",
                        "Course details for 21CSC206T",
                        "Find available rooms in Tech Park"
                    ]
                },
                "answer": (
                    f"I did not find a specific campus entity matching '{user_query}'.\n\n"
                    "Could you specify what you are looking for?\n\n"
                    "- Curriculum: Mention the branch and semester (e.g., 'B.Tech CSE Semester 3')\n"
                    "- Admissions: Mention the program (e.g., 'Eligibility for B.Tech' or 'MBA cutoffs')\n"
                    "- Courses: Provide the course code (e.g., '21CSC206T' or 'Prerequisites for 21CSO451T')\n"
                    "- Rooms: Mention the building (e.g., 'Available rooms in Tech Park')"
                ),
                "grounded": True,
                "intent_source": "Interactive Clarification Engine",
                "source": "SRMIST Campus Knowledge Assistant",
                "synthesizer": "Interactive Campus Assistant"
            }

        tool_name, tool_params = tool_call
        if tool_name not in self.tool_map:
            return {
                "user_query": user_query,
                "status": "UNAUTHORIZED_TOOL",
                "answer": f"Tool '{tool_name}' is not authorized.",
                "grounded": False
            }

        # 4. Check Role-Based Access Control (RBAC) via policy.yaml
        policy = getattr(self, "policy", None)
        if policy and "roles" in policy and role in policy["roles"]:
            role_cfg = policy["roles"][role]
            forbidden = role_cfg.get("forbidden_tools", [])
            allowed = role_cfg.get("allowed_tools", [])
            if tool_name in forbidden or (allowed and tool_name not in allowed):
                return {
                    "user_query": user_query,
                    "tool_selected": tool_name,
                    "status": "FORBIDDEN_TOOL_FOR_ROLE",
                    "answer": f"Access Policy Violation: Role '{role}' is not permitted to execute tool '{tool_name}'.",
                    "grounded": False
                }

        # 5. Execute governed tool
        try:
            tool_result = self.tool_map[tool_name](tool_params)
        except Exception as e:
            return {
                "user_query": user_query,
                "tool_selected": tool_name,
                "parameters": tool_params,
                "status": "EXECUTION_ERROR",
                "error": str(e),
                "grounded": False
            }

        # 6. Apply Field Masking & Row Limits by Role
        if policy and "roles" in policy and role in policy["roles"]:
            role_cfg = policy["roles"][role]
            hidden_fields = set(role_cfg.get("hidden_fields", []))
            row_limit = role_cfg.get("row_limit", 50)
            if hidden_fields:
                for k, v in tool_result.items():
                    if isinstance(v, list):
                        for item in v:
                            if isinstance(item, dict):
                                for hf in hidden_fields:
                                    if hf in item:
                                        item[hf] = "[Hidden by Policy]"
                    elif isinstance(v, dict):
                        for hf in hidden_fields:
                            if hf in v:
                                v[hf] = "[Hidden by Policy]"
            for k in ["faculty", "courses", "programs", "rooms", "classes"]:
                if k in tool_result and isinstance(tool_result[k], list):
                    tool_result[k] = tool_result[k][:row_limit]

        # Synthesize Grounded Answer with Citations
        # Check whether records were found in the graph
        has_data = self._check_result_has_data(tool_result, tool_name)

        status_code = "SUCCESS"
        suggestions = []

        if not has_data:
            # Check across all other catalogs before declaring nothing found
            fed_res = self._federated_cross_entity_search(user_query, role=role, engine_mode=engine_mode, attempted_tool=tool_name)
            if fed_res:
                return fed_res

            status_code = "CLARIFICATION_NEEDED"
            if tool_name == "lookup_faculty_profile":
                suggestions = ["Who teaches 21CSC206T?", "B.Tech CSE Semester 3", "Eligibility for B.Tech", "Find available rooms in Tech Park"]
                grounded_answer = f"I could not find a faculty profile matching '{user_query}' in the SRMIST directory.\n\nTry searching with a department or course code, or select an option below:"
            elif tool_name in ["lookup_course", "search_courses_semantic"]:
                suggestions = ["21CSC206T", "21CSO451T", "Who teaches 21CSC206T?", "Prerequisites for 21CSO451T"]
                grounded_answer = f"I could not find any course matching '{user_query}' in the official catalog.\n\nTry searching with a standard course code or select a suggestion below:"
            elif tool_name == "find_room_schedule":
                suggestions = ["Schedule for TP-101", "Find available rooms in Tech Park", "Find available rooms in University Building"]
                grounded_answer = f"No classes or schedules found for '{user_query}'.\n\nTry checking room availability or a known room code:"
            elif tool_name == "check_admission_eligibility":
                suggestions = ["Eligibility for B.Tech", "MBA admission requirements", "MBBS cutoff", "M.Tech eligibility"]
                grounded_answer = f"No specific admission rules found for '{user_query}'.\n\nSelect a program below to view official admission criteria:"
            else:
                suggestions = ["B.Tech CSE Semester 3", "Eligibility for B.Tech", "Course details for 21CSC206T", "Find available rooms in Tech Park"]
                grounded_answer = f"I did not find any campus records matching '{user_query}'.\n\nHere are some common things you can ask me:"

            tool_result["suggestions"] = suggestions
        else:
            if use_llm_synthesis and self.ollama_active:
                grounded_answer = self._synthesize_with_qwen(user_query, tool_name, tool_result, session_id=session_id)
            else:
                grounded_answer = self._synthesize_grounded_answer(user_query, tool_name, tool_result)

            if tool_result.get("status") == "CLARIFICATION_NEEDED":
                status_code = "CLARIFICATION_NEEDED"
            if tool_result.get("suggestions"):
                suggestions = tool_result.get("suggestions")

        # Extract entities for conversation memory
        entities = self._extract_entities_from_result(tool_name, tool_result, has_data)

        # Record turn in conversation memory
        if session_id:
            ConversationMemory.add_turn(
                session_id, original_query, tool_name,
                grounded_answer[:200] if grounded_answer else "",
                entities
            )

        result_payload = {
            "user_query": user_query,
            "original_query": original_query if original_query != user_query else None,
            "tool_selected": tool_name,
            "parameters": tool_params,
            "status": status_code,
            "suggestions": suggestions if not has_data else tool_result.get("suggestions", []),
            "tool_result": tool_result,
            "answer": grounded_answer,
            "grounded": True,
            "engine_mode": engine_mode,
            "intent_source": intent_source,
            "source": "Neo4j Community Graph & Vector Index" if engine_mode == "neo4j" else "Governed Campus Knowledge Mirror",
            "synthesizer": "Qwen 2.5 (Ollama)" if (use_llm_synthesis and self.ollama_active and has_data) else "Deterministic Governed Synthesizer"
        }
        # Remove None fields
        return {k: v for k, v in result_payload.items() if v is not None}

    def ask_qwen(self, user_query: str) -> Dict[str, Any]:
        """Direct query method using Qwen 2.5 for grounded natural language synthesis."""
        return self.execute_query(user_query, use_llm_synthesis=True)

    def _check_result_has_data(self, result: Dict[str, Any], tool_name: str = "") -> bool:
        """Determines whether a tool execution produced verified records from the graph."""
        if not result or not isinstance(result, dict):
            return False
        if "programs" in result and result["programs"]:
            return True
        if "faculty" in result and result["faculty"]:
            return True
        if "courses" in result and result["courses"]:
            return True
        if "available_rooms" in result:
            return bool(result.get("available_rooms"))
        if tool_name == "find_room_schedule" and "room_id" in result and not result.get("error"):
            return True
        if "schedules" in result and result["schedules"]:
            return True
        if "instructors" in result and result["instructors"]:
            return True
        if tool_name in ("get_prerequisite_tree", "verify_prerequisites") and ("target_course" in result or "prerequisites" in result or "eligible" in result):
            return True
        if "prerequisites" in result:
            return True
        if "eligible" in result:
            return True
        if "statistics" in result and result["statistics"]:
            return True
        if "semesters" in result or ("courses" in result and tool_name == "get_semester_curriculum"):
            return True
        return False

    def _extract_entities_from_result(self, tool_name: str, tool_result: Dict[str, Any], has_data: bool) -> Dict[str, Any]:
        """Extracts primary entity keys from tool result for conversation memory tracking."""
        entities = {}
        if not has_data or not isinstance(tool_result, dict):
            return entities
        if tool_name == "lookup_faculty_profile":
            fac_list = tool_result.get("faculty", [])
            if fac_list:
                entities["faculty_name"] = fac_list[0].get("name", "")
        elif tool_name in ("lookup_course", "get_prerequisite_tree", "verify_prerequisites"):
            courses = tool_result.get("courses", [])
            if courses:
                entities["course_code"] = courses[0].get("code", "")
            elif tool_result.get("target_course"):
                entities["course_code"] = tool_result["target_course"]
        elif tool_name == "find_faculty_for_course":
            instructors = tool_result.get("instructors", [])
            if instructors:
                entities["faculty_name"] = instructors[0].get("name", "")
            if tool_result.get("course_code"):
                entities["course_code"] = tool_result["course_code"]
        elif tool_name == "check_admission_eligibility":
            progs = tool_result.get("programs", [])
            if progs:
                entities["program_name"] = progs[0].get("program_name", "")
        elif tool_name == "find_room_schedule":
            entities["room_id"] = tool_result.get("room_id", "")
        return entities

    def _compact_tool_payload(self, result: Dict[str, Any], tool_name: str = "") -> Dict[str, Any]:
        """Compacts the payload to eliminate CPU prompt-evaluation latency while preserving rich context."""
        compact_res = {}
        if "programs" in result and result["programs"]:
            compact_res["programs"] = [
                {
                    "program": p.get("program_name"),
                    "cutoff_gen": p.get("min_percentage_general", p.get("min_percentage")),
                    "exam": p.get("required_entrance_exam"),
                    "fee": p.get("annual_fee_inr"),
                    "duration": p.get("duration"),
                    "campuses": p.get("campuses")
                }
                for p in result["programs"][:3]
            ]
        elif "faculty" in result and result["faculty"]:
            compact_res["faculty"] = [
                {
                    "name": f.get("name"),
                    "designation": f.get("designation"),
                    "dept": f.get("department"),
                    "cabin": describe_cabin_location(f.get("cabin", "Staff Room")),
                    "email": f.get("email")
                }
                for f in result["faculty"][:3]
            ]
        elif "courses" in result and result["courses"]:
            compact_res["courses"] = [
                {
                    "code": c.get("code") or c.get("course_code"),
                    "name": c.get("name") or c.get("course_name"),
                    "credits": c.get("credits"),
                    "dept": c.get("department"),
                    "semester": c.get("semester_range") or c.get("semester"),
                    "summary": c.get("description", "")[:120] if c.get("description") else ""
                }
                for c in result["courses"][:3]
            ]
        elif "prerequisites" in result and result["prerequisites"]:
            compact_res["target_course"] = result.get("target_course")
            compact_res["prerequisites"] = [
                {"code": p.get("prerequisite_code"), "name": p.get("prerequisite_name"), "depth": p.get("depth")}
                for p in result["prerequisites"][:4]
            ]
        elif "instructors" in result and result["instructors"]:
            compact_res["course_code"] = result.get("course_code")
            compact_res["instructors"] = [
                {
                    "name": i.get("name"),
                    "designation": i.get("designation"),
                    "dept": i.get("department"),
                    "cabin": describe_cabin_location(i.get("cabin", "")),
                    "email": i.get("email")
                }
                for i in result["instructors"][:3]
            ]
        elif "available_rooms" in result:
            compact_res["building"] = result.get("building_code")
            compact_res["available_rooms"] = [r.get("id") if isinstance(r, dict) else str(r) for r in result["available_rooms"][:6]]
            compact_res["total_vacant"] = result.get("available_count", len(result["available_rooms"]))
        elif "schedules" in result and result["schedules"]:
            compact_res["room_id"] = result.get("room_id")
            compact_res["room_type"] = result.get("room_type")
            compact_res["schedules"] = [
                {"day": s.get("day"), "slot": s.get("time_slot") or s.get("slot"), "course": s.get("course_name") or s.get("course_code")}
                for s in result["schedules"][:4]
            ]
        elif "statistics" in result:
            compact_res["statistics"] = result["statistics"]
        elif "semesters" in result:
            compact_res["program"] = result.get("program_name")
            compact_res["semesters"] = result.get("semesters")
        else:
            compact_res = result
        return compact_res

    def _build_concierge_prompt(self, query: str, compact_res: Dict[str, Any], session_id: str = "") -> str:
        """Constructs the grounded synthesis prompt with conversation context."""
        context_block = ""
        if session_id:
            ctx = ConversationMemory.build_context_prompt(session_id)
            if ctx:
                context_block = f"\n{ctx}\n"

        return f"""You are the SRMIST Campus Knowledge AI Concierge — an articulate, collegiate, and welcoming academic assistant.
Your goal is to answer the user's inquiry conversationally in 2-3 polished, natural sentences using ONLY the verified facts below.{context_block}
Highlight essential details clearly (such as designations, departments, cabin locations, or credits) and retain verified citations in brackets like [Faculty: Dr. Name], [Course: Code], [Program: Name], or [Room: Room ID].
Conclude smoothly. Do not hallucinate any information not present in the verified facts.

Verified Facts:
{json.dumps(compact_res, default=str)}

User Question: {query}
Concierge Response:"""

    def _synthesize_with_qwen(self, query: str, tool_name: str, result: Dict[str, Any], session_id: str = "") -> str:
        has_data = self._check_result_has_data(result, tool_name)
        if not has_data:
            return self._synthesize_grounded_answer(query, tool_name, result)

        try:
            compact_res = self._compact_tool_payload(result, tool_name)
            prompt = self._build_concierge_prompt(query, compact_res, session_id=session_id)
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.35, "num_predict": 140}
                },
                timeout=25
            )
            if resp.status_code == 200:
                ans = resp.json().get("response", "").strip()
                if ans and len(ans) > 15:
                    return ans
        except Exception:
            pass
        return self._synthesize_grounded_answer(query, tool_name, result)

    def stream_query(
        self,
        user_query: str,
        use_llm_synthesis: bool = True,
        role: str = "student",
        engine_mode: str = "neo4j",
        session_id: str = ""
    ):
        """
        Server-Sent Events generator streaming tool metadata, real-time LLM tokens, and completion events.
        """
        from campus_knowledge_server.security.ast_validator import ASTSecurityValidator
        from campus_knowledge_server.security.audit import get_audit_logger

        original_query = user_query
        if session_id:
            resolved = ConversationMemory.resolve_followup(session_id, user_query)
            if resolved:
                user_query = resolved

        # 0. Zero-Trust AST Security Guardrail
        is_adversarial, violation_reason = ASTSecurityValidator.is_adversarial_or_destructive(user_query)
        if is_adversarial:
            audit_logger = get_audit_logger()
            audit_logger.log_event(
                caller="web_user",
                tool_name="ast_security_interception",
                parameters={"query": user_query},
                status="POLICY_VIOLATION",
                latency_ms=1.1,
                result_count=0,
                violation_reason=f"Access Policy Violation: {violation_reason}",
                role=role
            )
            yield {
                "event": "error",
                "status": "POLICY_VIOLATION",
                "tool_selected": "ast_security_interception",
                "detail": f"Access Policy Violation: Destructive operations ('{user_query.strip()}') are strictly prohibited."
            }
            return

        # Interactive Conversational Greetings
        clean_input = re.sub(r"[^\w\s]", " ", user_query.strip().lower())
        input_words = clean_input.split()
        GREETINGS = {"hey", "hello", "hi", "howdy", "greetings", "good morning", "good afternoon", "good evening", "sup", "yo", "namaste"}
        CONVERSATIONAL_PHRASES = [
            "help", "can you help", "who are you", "what are you", "what can you do", "what do you do",
            "how to use", "how do i use", "how does this work", "i want to ask", "i have a question",
            "tell me something", "features", "menu", "options", "commands", "start", "guide", "assist", "instructions"
        ]
        is_greeting = clean_input in GREETINGS or (input_words and input_words[0] in GREETINGS and len(input_words) <= 3)
        is_help = any(p in clean_input for p in CONVERSATIONAL_PHRASES) or (clean_input in {"help", "start", "hi", "hey"})

        if is_greeting or is_help:
            ans = (
                "Hello! I am the SRMIST Campus Knowledge Assistant.\n\n"
                "I provide verified facts across the campus graph. What would you like to look up?\n\n"
                "- Admissions: Check cutoffs and requirements (e.g., 'eligibility for btech' or 'fees for cse')\n"
                "- Curriculum: View semester courses (e.g., 'B.Tech CSE Semester 3' or 'AI Semester 4')\n"
                "- Courses: Check course details and prerequisites (e.g., 'Course details for 21CSC206T' or 'Prerequisites for 21CSO451T')\n"
                "- Classrooms: Find vacant rooms or view timetables (e.g., 'Find available rooms in Tech Park')"
            )
            yield {
                "event": "meta",
                "user_query": user_query,
                "original_query": original_query if original_query != user_query else None,
                "tool_selected": "interactive_assistant",
                "parameters": {},
                "status": "INTERACTIVE_GREETING",
                "suggestions": [
                    "B.Tech CSE Semester 3", "Eligibility for B.Tech",
                    "Course details for 21CSC206T", "Find available rooms in Tech Park"
                ],
                "tool_result": {"type": "interactive_guidance"},
                "grounded": True,
                "engine_mode": engine_mode,
                "intent_source": "Interactive Conversational Engine",
                "source": "SRMIST Campus Knowledge Assistant",
                "synthesizer": "Interactive Campus Assistant"
            }
            for word in ans.split(" "):
                yield {"event": "delta", "token": word + " "}
            if session_id:
                ConversationMemory.add_turn(session_id, original_query, "interactive_assistant", ans[:200])
            yield {"event": "done", "answer": ans, "status": "INTERACTIVE_GREETING"}
            return

        # Routing
        tool_call = self._fast_path_match(user_query)
        intent_source = "Fast-Path Matcher (~1ms)" if tool_call else None

        if not tool_call:
            tool_call = self._select_tool_heuristically(user_query)
            if tool_call:
                intent_source = "High-Speed Normalized Router (~8ms)"

        if not tool_call and self.ollama_active:
            tool_call = self._select_tool_with_llm(user_query)
            if tool_call:
                intent_source = "Qwen 2.5 Semantic Intent Parser (JSON Mode)"

        if not tool_call:
            fed_res = self._federated_cross_entity_search(user_query, role=role, engine_mode=engine_mode)
            if fed_res:
                yield {
                    "event": "meta",
                    "user_query": fed_res["user_query"],
                    "original_query": original_query if original_query != user_query else None,
                    "tool_selected": fed_res["tool_selected"],
                    "parameters": fed_res["parameters"],
                    "status": fed_res["status"],
                    "suggestions": fed_res.get("suggestions", []),
                    "tool_result": fed_res.get("tool_result"),
                    "grounded": True,
                    "engine_mode": engine_mode,
                    "intent_source": fed_res.get("intent_source"),
                    "source": fed_res.get("source"),
                    "synthesizer": fed_res.get("synthesizer")
                }
                for word in fed_res["answer"].split(" "):
                    yield {"event": "delta", "token": word + " "}
                if session_id:
                    ConversationMemory.add_turn(session_id, original_query, fed_res["tool_selected"], fed_res["answer"][:200])
                yield {"event": "done", "answer": fed_res["answer"], "status": "SUCCESS"}
                return

            clarification_ans = (
                f"I did not find a specific campus entity matching '{user_query}'.\n\n"
                "Could you specify what you are looking for?\n\n"
                "- Curriculum: Mention the branch and semester (e.g., 'B.Tech CSE Semester 3')\n"
                "- Admissions: Mention the program (e.g., 'Eligibility for B.Tech' or 'MBA cutoffs')\n"
                "- Courses: Provide the course code (e.g., '21CSC206T' or 'Prerequisites for 21CSO451T')\n"
                "- Rooms: Mention the building (e.g., 'Available rooms in Tech Park')"
            )
            yield {
                "event": "meta",
                "user_query": user_query,
                "original_query": original_query if original_query != user_query else None,
                "tool_selected": "interactive_clarification",
                "parameters": {"query": user_query},
                "status": "CLARIFICATION_NEEDED",
                "suggestions": [
                    "B.Tech CSE Semester 3", "Eligibility for B.Tech",
                    "Course details for 21CSC206T", "Find available rooms in Tech Park"
                ],
                "tool_result": {"type": "clarification"},
                "grounded": True,
                "engine_mode": engine_mode,
                "intent_source": "Interactive Clarification Engine",
                "source": "SRMIST Campus Knowledge Assistant",
                "synthesizer": "Interactive Campus Assistant"
            }
            for word in clarification_ans.split(" "):
                yield {"event": "delta", "token": word + " "}
            yield {"event": "done", "answer": clarification_ans, "status": "CLARIFICATION_NEEDED"}
            return

        tool_name, tool_params = tool_call
        if tool_name not in self.tool_map:
            yield {
                "event": "error",
                "status": "UNAUTHORIZED_TOOL",
                "detail": f"Tool '{tool_name}' is not authorized."
            }
            return

        # RBAC Check
        policy = getattr(self, "policy", None)
        if policy and "roles" in policy and role in policy["roles"]:
            role_cfg = policy["roles"][role]
            forbidden = role_cfg.get("forbidden_tools", [])
            allowed = role_cfg.get("allowed_tools", [])
            if tool_name in forbidden or (allowed and tool_name not in allowed):
                yield {
                    "event": "error",
                    "status": "FORBIDDEN_TOOL_FOR_ROLE",
                    "detail": f"Access Policy Violation: Role '{role}' is not permitted to execute tool '{tool_name}'."
                }
                return

        # Tool execution
        try:
            tool_result = self.tool_map[tool_name](tool_params)
        except Exception as e:
            yield {
                "event": "error",
                "status": "EXECUTION_ERROR",
                "detail": str(e)
            }
            return

        # Field masking & row limits
        if policy and "roles" in policy and role in policy["roles"]:
            role_cfg = policy["roles"][role]
            hidden_fields = set(role_cfg.get("hidden_fields", []))
            row_limit = role_cfg.get("row_limit", 50)
            if hidden_fields:
                for k, v in tool_result.items():
                    if isinstance(v, list):
                        for item in v:
                            if isinstance(item, dict):
                                for hf in hidden_fields:
                                    if hf in item:
                                        item[hf] = "[Hidden by Policy]"
                    elif isinstance(v, dict):
                        for hf in hidden_fields:
                            if hf in v:
                                v[hf] = "[Hidden by Policy]"
            for k in ["faculty", "courses", "programs", "rooms", "classes"]:
                if k in tool_result and isinstance(tool_result[k], list):
                    tool_result[k] = tool_result[k][:row_limit]

        has_data = self._check_result_has_data(tool_result, tool_name)
        status_code = "SUCCESS"
        suggestions = []

        if not has_data:
            fed_res = self._federated_cross_entity_search(user_query, role=role, engine_mode=engine_mode, attempted_tool=tool_name)
            if fed_res:
                yield {
                    "event": "meta",
                    "user_query": fed_res["user_query"],
                    "original_query": original_query if original_query != user_query else None,
                    "tool_selected": fed_res["tool_selected"],
                    "parameters": fed_res["parameters"],
                    "status": fed_res["status"],
                    "suggestions": fed_res.get("suggestions", []),
                    "tool_result": fed_res.get("tool_result"),
                    "grounded": True,
                    "engine_mode": engine_mode,
                    "intent_source": fed_res.get("intent_source"),
                    "source": fed_res.get("source"),
                    "synthesizer": fed_res.get("synthesizer")
                }
                for word in fed_res["answer"].split(" "):
                    yield {"event": "delta", "token": word + " "}
                if session_id:
                    ConversationMemory.add_turn(session_id, original_query, fed_res["tool_selected"], fed_res["answer"][:200])
                yield {"event": "done", "answer": fed_res["answer"], "status": "SUCCESS"}
                return

            status_code = "CLARIFICATION_NEEDED"
            if tool_name == "lookup_faculty_profile":
                suggestions = ["Who teaches 21CSC206T?", "B.Tech CSE Semester 3", "Eligibility for B.Tech", "Find available rooms in Tech Park"]
                grounded_answer = f"I could not find a faculty profile matching '{user_query}' in the SRMIST directory.\n\nTry searching with a department or course code, or select an option below:"
            elif tool_name in ["lookup_course", "search_courses_semantic"]:
                suggestions = ["21CSC206T", "21CSO451T", "Who teaches 21CSC206T?", "Prerequisites for 21CSO451T"]
                grounded_answer = f"I could not find any course matching '{user_query}' in the official catalog.\n\nTry searching with a standard course code or select a suggestion below:"
            elif tool_name == "find_room_schedule":
                suggestions = ["Schedule for TP-101", "Find available rooms in Tech Park", "Find available rooms in University Building"]
                grounded_answer = f"No classes or schedules found for '{user_query}'.\n\nTry checking room availability or a known room code:"
            elif tool_name == "check_admission_eligibility":
                suggestions = ["Eligibility for B.Tech", "MBA admission requirements", "MBBS cutoff", "M.Tech eligibility"]
                grounded_answer = f"No specific admission rules found for '{user_query}'.\n\nSelect a program below to view official admission criteria:"
            else:
                suggestions = ["B.Tech CSE Semester 3", "Eligibility for B.Tech", "Course details for 21CSC206T", "Find available rooms in Tech Park"]
                grounded_answer = f"I did not find any campus records matching '{user_query}'.\n\nHere are some common things you can ask me:"

            yield {
                "event": "meta",
                "user_query": user_query,
                "original_query": original_query if original_query != user_query else None,
                "tool_selected": tool_name,
                "parameters": tool_params,
                "status": status_code,
                "suggestions": suggestions,
                "tool_result": tool_result,
                "grounded": True,
                "engine_mode": engine_mode,
                "intent_source": intent_source,
                "source": "SRMIST Campus Knowledge Assistant",
                "synthesizer": "Interactive Campus Assistant"
            }
            for word in grounded_answer.split(" "):
                yield {"event": "delta", "token": word + " "}
            yield {"event": "done", "answer": grounded_answer, "status": status_code}
            return

        # Data found: yield meta event first
        suggestions = tool_result.get("suggestions", [])
        yield {
            "event": "meta",
            "user_query": user_query,
            "original_query": original_query if original_query != user_query else None,
            "tool_selected": tool_name,
            "parameters": tool_params,
            "status": status_code,
            "suggestions": suggestions,
            "tool_result": tool_result,
            "grounded": True,
            "engine_mode": engine_mode,
            "intent_source": intent_source,
            "source": "Neo4j Community Graph & Vector Index" if engine_mode == "neo4j" else "Governed Campus Knowledge Mirror",
            "synthesizer": "Qwen 2.5 (Ollama)" if (use_llm_synthesis and self.ollama_active and has_data) else "Deterministic Governed Synthesizer"
        }

        # Token Streaming
        tokens_emitted = []
        if use_llm_synthesis and self.ollama_active:
            try:
                compact_res = self._compact_tool_payload(tool_result, tool_name)
                prompt = self._build_concierge_prompt(user_query, compact_res, session_id=session_id)
                resp = requests.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model_name,
                        "prompt": prompt,
                        "stream": True,
                        "options": {"temperature": 0.35, "num_predict": 140}
                    },
                    stream=True,
                    timeout=30
                )
                if resp.status_code == 200:
                    for line in resp.iter_lines():
                        if line:
                            data = json.loads(line)
                            tok = data.get("response", "")
                            if tok:
                                tokens_emitted.append(tok)
                                yield {"event": "delta", "token": tok}
            except Exception:
                pass

        if tokens_emitted:
            final_answer = "".join(tokens_emitted).strip()
        else:
            grounded_answer = self._synthesize_grounded_answer(user_query, tool_name, tool_result)
            for word in grounded_answer.split(" "):
                yield {"event": "delta", "token": word + " "}
            final_answer = grounded_answer

        # Entity extraction & conversation memory
        entities = self._extract_entities_from_result(tool_name, tool_result, has_data)
        if session_id:
            ConversationMemory.add_turn(session_id, original_query, tool_name, final_answer[:200], entities)

        yield {
            "event": "done",
            "answer": final_answer,
            "status": "SUCCESS"
        }

    def _synthesize_grounded_answer(self, query: str, tool_name: str, result: Dict[str, Any]) -> str:
        """Synthesizes structured, strictly-grounded text with entity citations."""
        if tool_name == "lookup_course":
            courses = result.get("courses", [])
            if not courses:
                return "No matching course was found in the official SRMIST catalog."
            c = courses[0]
            result["suggestions"] = [
                f"Prerequisites for {c['code']}",
                f"Who teaches {c['code']}?",
                "Find available rooms in Tech Park"
            ]
            sem_info = f" Recommended for **{c['semester_range']}**." if c.get('semester_range') else ""
            ltpc_info = f" (L-T-P-C: {c.get('ltpc', 'N/A')})" if c.get('ltpc') else ""
            return (
                f"**[Course: {c['code']}] {c['name']}** is an accredited **{c['level']}** level subject carrying **{c['credits']} credits**{ltpc_info}, "
                f"offered by the **{c['department']}** under {c['faculty']}.{sem_info}\n\n"
                f"**Curriculum Scope & Syllabus Summary:**\n"
                f"{c['description']}\n\n"
                f"Would you like to inspect its prerequisite tree or see assigned instructors?"
            )

        elif tool_name == "get_prerequisite_tree":
            target = result.get("target_course", "")
            prereqs = result.get("prerequisites", [])
            if not prereqs:
                return f"[Course: {target}] has no mandatory prerequisite requirements in the curriculum graph."
            lines = [f"[Course: {target}] requires the following prerequisite dependencies:"]
            for p in prereqs:
                lines.append(f"- Depth {p['depth']}: [Course: {p['prerequisite_code']}] ({p['prerequisite_name']}) - Condition: {p['condition']}")
            return "\n".join(lines)

        elif tool_name == "verify_prerequisites":
            target = result.get("target_course", "")
            if result.get("eligible"):
                sat = ", ".join(result.get("satisfied_prerequisites", []))
                return f"**Eligible**: Student has satisfied all required prerequisites for [Course: {target}] (Completed: {sat})."
            else:
                missing = ", ".join(result.get("missing_prerequisites", []))
                return f"**Ineligible**: Student cannot enroll in [Course: {target}]. Missing required prerequisite(s): {missing}."

        elif tool_name == "find_faculty_for_course":
            code = result.get("course_code", "")
            instructors = result.get("instructors", [])
            if not instructors:
                return f"No instructor assignments currently registered for [Course: {code}]."
            lines = [f"Instructors assigned to [Course: {code}]:"]
            for i in instructors:
                lines.append(f"- [Faculty: {i['name']}] ({i['designation']}, {i['department']}) - Cabin: **{i.get('cabin', 'Staff Room')}** | Email: {i['email']}")
            return "\n".join(lines)

        elif tool_name == "lookup_faculty_profile":
            fac = result.get("faculty", [])
            if not fac:
                return f"Faculty member '{result.get('query')}' not found in the SRMIST directory."
            
            top_score = fac[0].get("relevance_score", 100)
            top_matches = [f for f in fac if f.get("relevance_score", 0) >= (top_score - 10)]

            if len(top_matches) > 1 and top_score < 100:
                result["suggestions"] = [f"{f['name']} ({f['department'].replace('Department of ', '')})" for f in top_matches[:5]]
                result["status"] = "CLARIFICATION_NEEDED"
                lines = [
                    f"I found {len(top_matches)} faculty members matching **'{result.get('query')}'** across different departments at SRMIST.",
                    "\nCould you please specify which professor you are referring to?\n"
                ]
                for i, f in enumerate(top_matches[:5], 1):
                    lines.append(f"- **[Faculty: {f['name']}]**: {f['designation']}, {f['department']} (Cabin: **{describe_cabin_location(f.get('cabin', 'Staff Room'))}**)")
                lines.append("\nYou can click one of the suggested buttons below or mention their department:")
                return "\n".join(lines)
            else:
                f = top_matches[0]
                spec_str = f"\n- **Specialization & Research:** {f['specialization']}" if f.get("specialization") else ""
                exp_str = f"\n- **Teaching Experience:** {f['experience']}" if f.get("experience") else ""
                phone_str = f"\n- **Office Phone:** {f['phone']}" if (f.get("phone") and f['phone'] != '[Hidden by Policy]') else ""
                
                result["suggestions"] = [
                    f"Who teaches in {f['department'].replace('Department of ', '')}?",
                    "Find available rooms in Tech Park",
                    "Eligibility for B.Tech"
                ]
                
                return (
                    f"**[Faculty: {f['name']}]** is an **{f['designation']}** in the **{f['department']}**, {f['college']}.\n\n"
                    f"**Campus Office & Contact Information:**\n"
                    f"- **Cabin / Staff Room:** **{describe_cabin_location(f.get('cabin', 'Staff Room'))}**\n"
                    f"- **Official Email:** `{f['email']}`{phone_str}{spec_str}{exp_str}\n\n"
                    f"Would you like to check their teaching timetable, see courses in this department, or find classrooms nearby?"
                )

        elif tool_name == "find_room_schedule":
            r_id = result.get("room_id", "")
            r_type = result.get("room_type", "Classroom / Hall")
            cap = result.get("capacity", "N/A")
            b_code = result.get("building_code", "Campus")
            schedules = result.get("schedules", [])
            day_filter = result.get("day_filter")

            result["suggestions"] = [
                f"Find available rooms in {b_code}",
                "Who teaches in Computer Science?",
                "Eligibility for B.Tech"
            ]

            if not schedules:
                if day_filter:
                    return f"**[Room: {r_id}]** ({r_type}, Capacity: **{cap}** seats in Building **{b_code}**) has no classes scheduled on **{day_filter}** and is currently **vacant and available**."
                return f"**[Room: {r_id}]** ({r_type}, Capacity: **{cap}** seats in Building **{b_code}**) has no conflicting sessions recorded in the active timetable and is **available**."

            lines = [
                f"**Timetable & Allocation for [Room: {r_id}]** ({r_type}, Capacity: **{cap}** seats, Building **{b_code}**):\n"
            ]
            for s in schedules[:8]:
                lines.append(f"- **{s.get('day', 'Day')}** @ **{s.get('slot', 'Slot')}**: [Course: {s.get('course_code', 'Class')}]")
            lines.append(f"\nOutside these scheduled lecture slots, [Room: {r_id}] is open and available for academic activities.")
            return "\n".join(lines)

        elif tool_name == "find_available_rooms":
            avail = result.get("available_rooms", [])
            b_code = result.get("building_code", "TP")
            day = result.get("day", "Monday")
            slot = result.get("slot", "08:45-09:35")
            count = result.get("available_count", len(avail))
            is_building_info_mode = result.get("min_capacity", 30) <= 10 and not any(w in query.lower() for w in ["available room", "free room", "vacant", "empty room"])

            BUILDING_NAMES = {
                "TP": "Tech Park (TP-1)", "TP2": "Tech Park 2 (TP-2)",
                "UB": "University Building", "BEL": "Bioengineering Block",
                "MEB": "Mechanical Engineering Block", "ESB": "Electrical Sciences Block",
                "FMB": "Faculty of Management Block", "SLB": "School of Law Building",
                "MCB": "Medical College Hospital Block"
            }
            BUILDING_FOCUS = {
                "TP": "Engineering & Computing labs, smart classrooms, lecture halls (15 floors)",
                "TP2": "Faculty Research Wings & Specialized Labs (12 floors)",
                "UB": "Administration, Sciences & Arts departments (14 floors)",
                "BEL": "Biotechnology & Genetic Engineering labs (8 floors)",
                "MEB": "Mechanical & Automobile Engineering workshops (6 floors)",
                "ESB": "ECE & EEE laboratories and classrooms (7 floors)",
                "FMB": "Management, MBA & Business programs (5 floors)",
                "SLB": "School of Law, moot court & seminars (4 floors)",
                "MCB": "Medicine, Nursing & Health Sciences (10 floors)"
            }

            full_name = BUILDING_NAMES.get(b_code, b_code)
            focus = BUILDING_FOCUS.get(b_code, "Campus building")

            result["suggestions"] = [
                f"Available rooms in {b_code} on Monday",
                f"Room schedule for {avail[0]['id']}" if avail else f"Find available rooms in TP",
                "Find available rooms in UB"
            ]

            if is_building_info_mode:
                # Building info response
                total_rooms = len(avail)
                room_types = {}
                for r in avail:
                    t = r.get("type", "Room")
                    room_types[t] = room_types.get(t, 0) + 1
                type_summary = ", ".join(f"{n} {t}s" for t, n in list(room_types.items())[:4])
                lines = [
                    f"**[Building: {full_name}]** is a campus facility at SRMIST Kattankulathur.\n",
                    f"**Primary Focus:** {focus}\n",
                    f"**Total Rooms on Record:** {total_rooms} rooms ({type_summary})\n",
                    f"**Sample Rooms:**"
                ]
                for r in avail[:6]:
                    lines.append(f"- **[Room: {r['id']}]**: {r.get('type', 'Room')} — Capacity: **{r.get('capacity', 'N/A')}** seats")
                lines.append(f"\nWould you like to check available classrooms in **{full_name}** for a specific day and time?")
                return "\n".join(lines)

            if not avail:
                return f"No unoccupied classrooms found in **{full_name}** for **{day}** at slot **{slot}** with minimum capacity {result.get('min_capacity', 30)}."

            lines = [
                f"Found **{count} available classrooms** in **{full_name}** for **{day}** at slot **{slot}**:\n"
            ]
            for r in avail[:6]:
                lines.append(f"- **[Room: {r['id']}]**: {r.get('type', 'Classroom')} (Capacity: **{r.get('capacity', 'N/A')}** seats)")
            lines.append("\nWould you like to inspect the full schedule for any of these rooms?")
            return "\n".join(lines)

        elif tool_name == "search_courses_semantic":
            courses = result.get("courses", [])
            if not courses:
                return f"No courses matched the topic '{result.get('query')}'."
            lines = [
                f"Here are the official courses in the SRMIST curriculum covering **'{result.get('query')}'**:\n"
            ]
            for c in courses[:4]:
                lines.append(f"- **[Course: {c['code']}]** **{c['name']}** - {c.get('credits', 4)} Credits ({c['department']})")
            lines.append("\nWould you like to check the prerequisite tree or assigned instructors for any of these?")
            result["suggestions"] = [
                f"Prerequisites for {courses[0]['code']}",
                f"Who teaches {courses[0]['code']}?",
                "Eligibility for B.Tech"
            ]
            return "\n".join(lines)

        elif tool_name == "check_admission_eligibility":
            progs = result.get("programs", [])
            if not progs:
                return f"No official admission requirements found for program query '{result.get('query')}'."
            lines = [f"Official SRMIST Admission Regulations for '{result.get('query')}':"]
            for p in progs[:4]:
                header = f"- [Program: {p['program_name']}] ({p['degree_level']}, {p['faculty']})"
                details = f"  - Min Education: {p['min_education']} ({p['mandatory_subjects']})\n  - Cutoff: General {p['min_percentage_general']}% | Reserved (SC/ST/OBC) {p['min_percentage_reserved']}%\n  - Entrance Exam: {p['required_entrance_exam']}"
                if p.get("annual_fee_inr") or p.get("duration"):
                    fee_val = p.get("annual_fee_inr", 0)
                    fee_str = f"INR {fee_val:,}/year" if (isinstance(fee_val, (int, float)) and fee_val > 0) else "Official Merit Fee Structure"
                    dur_raw = str(p.get("duration", "4")).strip()
                    dur_str = f"{dur_raw} Years" if dur_raw.isdigit() else dur_raw
                    camp_val = p.get("campuses", "Kattankulathur Main Campus")
                    if isinstance(camp_val, list):
                        campuses_str = ", ".join(camp_val[:3])
                    else:
                        campuses_str = str(camp_val)
                    details += f"\n  - Tuition & Campuses: {fee_str} | Duration: {dur_str} | Campuses: {campuses_str}"
                if "eligibility_verdict" in p:
                    details += f"\n  - Assessment: **{p['eligibility_verdict']}** - {p.get('verdict_reason', '')}"
                lines.append(f"{header}\n{details}")
            return "\n\n".join(lines)

        elif tool_name == "get_campus_statistics":
            stats = result.get("statistics", {})
            cat = result.get("category", "all")
            total_progs = stats.get("total_programs", 428)
            total_courses = stats.get("total_courses_indexed", 1284)
            total_fac = stats.get("total_faculty", 2501)
            total_rms = stats.get("total_classrooms", 264)
            total_sched = stats.get("total_scheduled_sessions", 500)
            levels = stats.get("degree_levels", {})

            if cat == "faculty":
                result["suggestions"] = [
                    "Who teaches 21CSC206T?",
                    "B.Tech CSE Semester 3",
                    "Find available rooms in Tech Park"
                ]
                lines = [
                    f"**SRM Institute of Science and Technology (SRMIST)** has **{total_fac:,} verified faculty members** across all campuses and departments.\n",
                    "- **Faculty of Engineering & Technology**: 1,200+ professors, researchers, and technical instructors",
                    "- **Medicine & Health Sciences**: 650+ clinical professors and specialist physicians",
                    "- **Management, Science, Humanities & Law**: 650+ faculty members\n",
                    "**Related Campus Knowledge Graph Metrics:**",
                    f"- **Academic Programs**: **{total_progs}** degree courses",
                    f"- **Classrooms & Labs**: **{total_rms}** facilities with **{total_sched}** weekly sessions\n",
                    "Would you like to locate a specific professor's cabin, contact details, or department?"
                ]
                return "\n".join(lines)

            elif cat in ["rooms", "classrooms"]:
                result["suggestions"] = [
                    "Find available rooms in Tech Park",
                    "Is TP-501 available?",
                    "Find available rooms in UB"
                ]
                lines = [
                    f"**SRM Institute of Science and Technology (SRMIST)** has **{total_rms} classrooms and laboratories** indexed across campus facilities including Tech Park (TP) and the University Building (UB).\n",
                    f"- **Weekly Sessions**: **{total_sched}** scheduled lecture sessions and lab allocations",
                    "- **Classroom Types**: High-capacity lecture halls, computer laboratories, seminar halls, and smart classrooms\n",
                    "**Related Campus Knowledge Graph Metrics:**",
                    f"- **Academic Programs**: **{total_progs}** degree programs",
                    f"- **Faculty Registry**: **{total_fac:,}** professors and instructors\n",
                    "Would you like to check available rooms in Tech Park or inspect a specific room schedule?"
                ]
                return "\n".join(lines)

            else:
                ug_count = levels.get("Undergraduate (UG)", levels.get("UG", 125))
                pg_count = levels.get("Postgraduate (PG)", levels.get("PG", 201))
                phd_count = levels.get("Doctoral / Ph.D.", levels.get("Doctoral", 51))
                dip_count = levels.get("Diploma / Certificate", levels.get("Diploma", 12)) + levels.get("Specialized / Other", 37)

                result["suggestions"] = [
                    "B.Tech CSE Semester 3",
                    "Eligibility for B.Tech",
                    "MBA admission requirements",
                    "Find available rooms in Tech Park"
                ]

                lines = [
                    f"**SRM Institute of Science and Technology (SRMIST)** offers **{total_progs} accredited academic degree programs** and **{total_courses:,} course modules** across 6 major faculties at its campuses:\n",
                    f"- **Undergraduate (UG)**: **{ug_count} programs** including B.Tech (CSE, AI, Biotech, ECE, Mechanical, Civil), MBBS, BDS, BBA, B.Sc, B.Arch, and Law",
                    f"- **Postgraduate (PG)**: **{pg_count} programs** including M.Tech, MBA, MCA, M.Sc, MD/MS, and specialized master programs",
                    f"- **Doctoral & Diploma**: **{phd_count} Ph.D specializations** and **{dip_count} diploma/certificate curricula**\n",
                    "**Campus Knowledge Graph Registry:**",
                    f"- **Verified Faculty**: **{total_fac:,}** professors, assistant professors, and researchers",
                    f"- **Classrooms & Laboratories**: **{total_rms}** modern facilities across Tech Park and University Building",
                    f"- **Active Weekly Timetables**: **{total_sched}** scheduled lecture sessions and lab allocations\n",
                    "Would you like to check admission requirements for a specific degree, locate a professor's cabin, or find vacant classrooms?"
                ]
                return "\n".join(lines)

        elif tool_name == "get_semester_curriculum":
            if "error" in result:
                return result["error"]
            prog_name = result.get("program_name", "Programme")
            sem = result.get("semester")
            if sem is not None:
                courses = result.get("courses", [])
                tot_cred = result.get("total_credits", 0)
                year = result.get("academic_year", 1)
                cats = result.get("category_breakdown", {})

                cat_summary = ", ".join([f"{count} {cat}" for cat, count in cats.items()])

                lines = [
                    f"**{prog_name} - Semester {sem} Implementation Plan** (Academic Year {year}):",
                    f"- **Total Subjects**: **{len(courses)} courses** ({cat_summary})",
                    f"- **Semester Credits**: **{tot_cred} Credits**\n",
                    "**Curriculum Course Matrix:**"
                ]
                for c in courses:
                    lines.append(f"- **[Course: {c['course_code']}]** **{c['course_name']}** | Category: *{c['category']}* | L-T-P-C: `{c['ltpc']}` | **{c['credits']} Credits**")

                next_sem = sem + 1 if sem < 8 else None
                sugg = [f"Semester {next_sem} subjects for {prog_name}" if next_sem else f"Full curriculum for {prog_name}", f"Who teaches {courses[0]['course_code']}?" if courses else "B.Tech CSE Semester 3", "Eligibility for B.Tech"]
                result["suggestions"] = sugg

                pg_num = courses[0].get("page_number", "N/A") if courses else "N/A"
                lines.append(f"\n*Source: SRMIST Regulations 2021 Unified Curriculum (Volume 1, Page {pg_num})*")
                return "\n".join(lines)
            else:
                semesters = result.get("semesters", {})
                tot_cred = result.get("total_credits", 0)
                tot_c = result.get("total_courses", 0)

                lines = [
                    f"**{prog_name} - 8-Semester Unified Curriculum Structure** (Regulations 2021):",
                    f"- **Total Course Modules**: **{tot_c} courses**",
                    f"- **Graduation Requirement**: **{tot_cred} Total Credits**\n"
                ]
                for s_label, s_data in semesters.items():
                    c_list = s_data.get("courses", [])
                    cred = s_data.get("credits", 0)
                    top_codes = ", ".join([c["code"] for c in c_list[:4]])
                    if len(c_list) > 4:
                        top_codes += f" (+{len(c_list)-4} more)"
                    lines.append(f"- **{s_label}** (**{cred} Credits**, {len(c_list)} courses): {top_codes}")

                lines.append(f"\nWould you like to drill down into the exact course codes and syllabus for any specific semester?")
                result["suggestions"] = [f"{prog_name} Semester 1", f"{prog_name} Semester 3", f"{prog_name} Semester 5", "Eligibility for B.Tech"]
                return "\n".join(lines)

        return str(result)

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    agent = GovernedCampusAgent()
    query = sys.argv[1] if len(sys.argv) > 1 else "What is the admission cutoff and entrance exam for B.Tech Computer Science and Engineering?"
    print(f"\n[QUERY]: {query}")
    print(f"[OLLAMA ACTIVE]: {agent.ollama_active} (Model: {agent.model_name})")
    print("-" * 60)
    result = agent.ask_qwen(query)
    print(f"[TOOL SELECTED]: {result.get('tool_selected')}")
    print(f"[SYNTHESIZER]: {result.get('synthesizer')}")
    print(f"[GROUNDED ANSWER]:\n{result.get('answer')}\n")
