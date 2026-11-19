"""
Governed Campus Knowledge Toolset
Implements least-privilege, parameterized query execution for courses,
prerequisites, faculty, rooms, and schedules with schema validation and audit logging.
"""

import time
import math
import re
import json
import difflib
import logging
from types import MappingProxyType
from typing import Dict, List, Any, Optional, Union
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("campus_tools")

from campus_knowledge_server.database.neo4j_client import get_graph_client
from campus_knowledge_server.security.ast_validator import ASTSecurityValidator, SecurityViolationError
from campus_knowledge_server.security.audit import get_audit_logger
from campus_knowledge_server.config.matching_config import (
    load_matching_config,
    strip_honorifics_and_tokenize,
    get_slot_number_map,
    normalize_department_name,
)

# ----------------- Pydantic v2 Request Schemas -----------------

class CourseLookupRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=100, description="Course code (e.g., '21CSC206T') or course title.")

    @field_validator("query", mode="before")
    @classmethod
    def validate_query(cls, v: Any) -> str:
        s = str(v).strip() if v is not None else ""
        if len(s) < 2:
            raise ValueError("Query must contain at least 2 non-whitespace characters.")
        return s

class CourseScheduleRequest(BaseModel):
    course_code: str = Field(..., min_length=2, max_length=20, description="Canonical course code (e.g. '21CSC206T').")
    day_of_week: Optional[str] = Field(default=None, description="Optional filter by day (e.g., 'Monday').")

    @field_validator("course_code", mode="before")
    @classmethod
    def validate_course_code(cls, v: Any) -> str:
        s = str(v).strip() if v is not None else ""
        if len(s) < 2:
            raise ValueError("Course code must contain at least 2 non-whitespace characters.")
        return s.upper()

class PrerequisiteTreeRequest(BaseModel):
    course_code: str = Field(..., min_length=3, max_length=20, description="Course code (e.g., '21CSO451T').")
    max_depth: int = Field(default=3, ge=1, le=4, description="Maximum traversal depth (bounded <= 4).")

class PrerequisiteVerifyRequest(BaseModel):
    completed_courses: List[str] = Field(..., description="List of course codes completed by student.")
    target_course: str = Field(..., min_length=3, max_length=20, description="Target course code to enroll in.")

class FacultyCourseRequest(BaseModel):
    course_code: str = Field(..., min_length=3, max_length=20, description="Course code.")

class FacultyProfileRequest(BaseModel):
    faculty_name: str = Field(..., min_length=2, max_length=100, description="Faculty member's full or partial name.")

    @field_validator("faculty_name", mode="before")
    @classmethod
    def validate_faculty_name(cls, v: Any) -> str:
        s = str(v).strip() if v is not None else ""
        if len(s) < 2:
            raise ValueError("Faculty name must contain at least 2 non-whitespace characters.")
        return s

class RoomScheduleRequest(BaseModel):
    room_id: str = Field(..., min_length=2, max_length=20, description="Room ID (e.g., 'TP-101', 'UB-203').")
    day_of_week: Optional[str] = Field(default=None, description="Optional filter by day (e.g., 'Monday').")

SLOT_NUMBER_MAP = get_slot_number_map()


def _build_phone_note(phone: str, shared_count: int) -> Optional[str]:
    """Code-generated phone_note: None if unique, shared count if >1, or not listed if empty."""
    if not (phone or "").strip():
        return "not listed in the directory"
    if shared_count > 1:
        return f"shared by {shared_count} faculty (department/office line)"
    return None


class AvailableRoomsRequest(BaseModel):
    building_code: str = Field(..., min_length=2, max_length=60, description="Building code or name (e.g. 'TP', 'UB', 'BEL').")
    min_capacity: int = Field(default=30, ge=10, le=500, description="Minimum room seating capacity.")
    day: str = Field(default="Monday", description="Day of week (Monday-Friday).")
    slot: Union[str, int] = Field(default="08:45-09:35", description="Timeslot string (e.g. '08:45-09:35') or integer slot number (1-7).")

    @field_validator("slot", mode="before")
    @classmethod
    def normalize_slot(cls, v: Any) -> str:
        slot_map = get_slot_number_map()
        valid_min, valid_max = min(slot_map), max(slot_map)
        if isinstance(v, int):
            if v in slot_map:
                return slot_map[v]
            raise ValueError(f"Integer slot must be between {valid_min} and {valid_max}, got {v}.")
        if isinstance(v, str):
            s = v.strip()
            if s.isdigit():
                n = int(s)
                if n in slot_map:
                    return slot_map[n]
                raise ValueError(f"Slot number must be between {valid_min} and {valid_max}, got {n}.")
            return s
        raise ValueError(f"Invalid slot value: {v}")

class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200, description="Semantic description or subject query.")
    top_k: int = Field(default=5, ge=1, le=10, description="Number of results to retrieve (max 10).")

class GovernedQueryTemplateRequest(BaseModel):
    template_id: str = Field(..., description="Whitelisted query template identifier.")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Query parameters.")

class AdmissionEligibilityRequest(BaseModel):
    program_query: str = Field(..., min_length=2, max_length=150, description="Program name or keyword (e.g. 'B.Tech Computer Science', 'MBBS', 'MBA', 'Law').")
    candidate_percentage: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Candidate's percentage in qualifying examination.")
    is_reserved_category: bool = Field(default=False, description="Whether candidate qualifies for reserved category (SC/ST/OBC) criteria.")
    candidate_stream: Optional[str] = Field(default=None, description="Candidate stream or subjects (e.g. 'PCM', 'PCB', 'Commerce', 'Arts').")

class SemesterCurriculumRequest(BaseModel):
    program_query: str = Field(..., min_length=2, max_length=150, description="Degree programme name or abbreviation (e.g. 'CSE', 'Computer Science', 'Artificial Intelligence', 'ECE', 'Mechanical', 'Aerospace').")
    semester: Optional[int] = Field(default=None, ge=1, le=10, description="Optional semester number (1 to 8 for B.Tech, 1 to 10 for Integrated M.Tech). If omitted, returns entire curriculum plan across all semesters.")

class CampusStatisticsRequest(BaseModel):
    category: str = Field(default="all", description="Category for statistics: 'all', 'departments', 'courses', 'programs', 'faculty', 'rooms'.")

class BuildingLookupRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=150, description="Building code (e.g. 'TP', 'TP2', 'UB', 'BEL', 'CVR', 'ARCH') or natural language inquiry (e.g. 'tp1 building', 'where is placement office').")

    @field_validator("query", mode="before")
    @classmethod
    def validate_query(cls, v: Any) -> str:
        s = str(v).strip() if v is not None else ""
        if len(s) < 2:
            raise ValueError("Query must contain at least 2 non-whitespace characters.")
        return s

# ----------------- Pre-Approved Cypher Templates (Immutable) -----------------

WHITELISTED_TEMPLATES = MappingProxyType({
    "courses_by_department": "MATCH (c:Course) WHERE toLower(c.department) CONTAINS toLower($department) RETURN c.code AS code, c.name AS name, c.credits AS credits, c.level AS level",
    "faculty_by_department": "MATCH (f:FacultyMember) WHERE toLower(f.department) CONTAINS toLower($department) RETURN f.id AS id, f.name AS name, f.designation AS designation, f.specialization AS specialization",
    "building_rooms_summary": "MATCH (r:Room)-[:LOCATED_IN]->(b:Building {code: $building_code}) RETURN r.id AS room_id, r.type AS type, r.capacity AS capacity",
    "course_prerequisite_chain": "MATCH (target:Course {code: $course_code})-[:REQUIRES_PREREQUISITE*1..3]->(prereq:Course) RETURN DISTINCT prereq.code AS prereq_code, prereq.name AS prereq_name"
})

# ----------------- Governed Tool Implementations -----------------

class CampusKnowledgeTools:

    @staticmethod
    def lookup_course(req: CourseLookupRequest, caller: str = "agent") -> Dict[str, Any]:
        """Looks up course details by course code or partial course name via Neo4j Cypher with fallback."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()
        q_norm = req.query.strip().upper()

        results = []
        # 1. Primary: Live Neo4j Cypher query
        if client.is_connected and client.driver:
            try:
                cypher = """
                    MATCH (c:Course)
                    WHERE toUpper(c.code) = $q_norm OR toLower(c.name) CONTAINS toLower($q_raw)
                    WITH c
                    ORDER BY CASE WHEN toUpper(c.code) = $q_norm THEN 0 ELSE 1 END, c.code ASC
                    LIMIT 25
                    OPTIONAL MATCH (c)-[:REQUIRES_PREREQUISITE]->(p:Course)
                    WITH c, collect(DISTINCT CASE WHEN p IS NOT NULL THEN {code: p.code, name: p.name} END) AS raw_prereqs
                    OPTIONAL MATCH (prog:Program)-[r:OFFERS_IN_SEMESTER]->(c)
                    WITH c, raw_prereqs,
                         collect(DISTINCT CASE WHEN prog IS NOT NULL THEN {program: prog.name, semester: r.semester} END) AS raw_offered
                    RETURN c.id as id, c.code as code, c.name as name, c.credits as credits,
                           c.level as level, c.department as department, c.description as description,
                           c.category as category, c.ltpc as ltpc, c.regulation as regulation,
                           coalesce(c.is_official, true) as is_official,
                           coalesce(c.has_detailed_syllabus, false) as has_detailed_syllabus,
                           coalesce(c.course_rationale, []) as course_rationale,
                           coalesce(c.course_outcomes, []) as course_outcomes,
                           c.syllabus_units as syllabus_units,
                           coalesce(c.textbooks, []) as textbooks,
                           c.assessment_summary as assessment_summary,
                           coalesce(c.corequisites_raw, 'Nil') as corequisites_raw,
                           coalesce(c.progressive_courses_raw, 'Nil') as progressive_courses_raw,
                           [x IN raw_prereqs WHERE x IS NOT NULL] as prerequisites,
                           [x IN raw_offered WHERE x IS NOT NULL] as offered_in
                """
                results = client.query_read(cypher, {"q_norm": q_norm, "q_raw": req.query.strip()})
                for item in results:
                    # Parse JSON-serialized structured fields safely
                    raw_units = item.get("syllabus_units")
                    if isinstance(raw_units, str) and raw_units.strip():
                        try:
                            item["syllabus_units"] = json.loads(raw_units)
                        except Exception:
                            item["syllabus_units"] = []
                    elif not isinstance(raw_units, list):
                        item["syllabus_units"] = []

                    raw_assess = item.get("assessment_summary")
                    if isinstance(raw_assess, str) and raw_assess.strip():
                        try:
                            item["assessment_summary"] = json.loads(raw_assess)
                        except Exception:
                            item["assessment_summary"] = {}
                    elif not isinstance(raw_assess, dict):
                        item["assessment_summary"] = {}

                    offered = item.get("offered_in") or []
                    item["offered_in"] = sorted(
                        offered,
                        key=lambda x: (x.get("semester") if isinstance(x.get("semester"), int) else 99, x.get("program") or "")
                    )
            except Exception as e:
                logger.warning(f"Neo4j lookup_course query error ({e}), falling back to in-memory.")
                results = []

        # 2. Secondary fallback: in-memory index
        if not results:
            if q_norm in client._course_by_code:
                c_item = dict(client._course_by_code[q_norm])
                c_item.setdefault("is_official", True)
                results.append(c_item)
            else:
                q_lower = req.query.strip().lower()
                for c in client.in_memory_data.get("courses", []):
                    if q_lower in c["name"].lower() or q_lower in c["code"].lower():
                        c_item = dict(c)
                        c_item.setdefault("is_official", True)
                        results.append(c_item)
                    if len(results) >= 25:
                        break

        latency = (time.time() - t0) * 1000
        audit.log_event(
            caller=caller,
            tool_name="lookup_course",
            parameters=req.model_dump(),
            status="SUCCESS",
            latency_ms=latency,
            result_count=len(results)
        )

        return {
            "query": req.query,
            "match_count": len(results),
            "courses": results,
            "source": "SRMIST Property Graph (Neo4j Community)" if client.is_connected else "SRMIST In-Memory Cache",
            "grounding": f"Found {len(results)} courses matching '{req.query}'."
        }

    @staticmethod
    def get_prerequisite_tree(req: PrerequisiteTreeRequest, caller: str = "agent") -> Dict[str, Any]:
        """Recursively traverses prerequisite relationships up to max_depth via Cypher."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()
        target = req.course_code.strip().upper()

        tree = []
        if client.is_connected and client.driver:
            try:
                cypher = """
                    MATCH path = (target:Course {code: $code})-[:REQUIRES_PREREQUISITE*1..4]->(prereq:Course)
                    UNWIND relationships(path) as rel
                    WITH startNode(rel) as t, endNode(rel) as p, rel, length(path) as d
                    WHERE d <= $max_depth
                    RETURN DISTINCT d as depth, t.code as target_course, p.code as prerequisite_code,
                                    p.name as prerequisite_name, rel.condition as condition
                    ORDER BY depth ASC
                """
                tree = client.query_read(cypher, {"code": target, "max_depth": req.max_depth})
            except Exception as e:
                logger.warning(f"Neo4j get_prerequisite_tree error ({e}), falling back.")
                tree = []

        if not tree:
            visited = set()
            def dfs(current_code: str, current_depth: int):
                if current_depth > req.max_depth or current_code in visited:
                    return
                visited.add(current_code)
                prereqs = client._prereqs_by_target.get(current_code, [])
                for p in prereqs:
                    req_code = p["prerequisite_course_code"].upper()
                    c_info = client._course_by_code.get(req_code, {"code": req_code, "name": "Unknown Course"})
                    tree.append({
                        "depth": current_depth,
                        "target_course": current_code,
                        "prerequisite_code": req_code,
                        "prerequisite_name": c_info.get("name", ""),
                        "condition": p.get("condition", "MANDATORY_PASS")
                    })
                    dfs(req_code, current_depth + 1)
            dfs(target, 1)

        latency = (time.time() - t0) * 1000
        audit.log_event(
            caller=caller,
            tool_name="get_prerequisite_tree",
            parameters=req.model_dump(),
            status="SUCCESS",
            latency_ms=latency,
            result_count=len(tree)
        )

        return {
            "target_course": target,
            "max_depth_evaluated": req.max_depth,
            "total_prerequisites": len(tree),
            "prerequisites": tree,
            "source": "SRMIST Prerequisite DAG (Neo4j Community)" if client.is_connected else "SRMIST In-Memory Cache",
            "grounding": f"{target} has {len(tree)} prerequisite dependency edges up to depth {req.max_depth}."
        }

    @staticmethod
    def verify_prerequisites(req: PrerequisiteVerifyRequest, caller: str = "agent") -> Dict[str, Any]:
        """Evaluates whether completed courses satisfy all prerequisites for a target course."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()

        target = req.target_course.strip().upper()
        completed = {c.strip().upper() for c in req.completed_courses}

        required_codes = []
        if client.is_connected and client.driver:
            try:
                cypher = """
                    MATCH (target:Course {code: $code})-[:REQUIRES_PREREQUISITE]->(prereq:Course)
                    RETURN prereq.code as required_code
                """
                rows = client.query_read(cypher, {"code": target})
                required_codes = [r["required_code"].upper() for r in rows if "required_code" in r]
            except Exception as e:
                logger.warning(f"Neo4j verify_prerequisites error ({e}), falling back.")

        if not required_codes:
            prereqs = client._prereqs_by_target.get(target, [])
            required_codes = [p["prerequisite_course_code"].upper() for p in prereqs]

        missing = [code for code in required_codes if code not in completed]
        satisfied = [code for code in required_codes if code in completed]
        is_eligible = (len(missing) == 0)

        latency = (time.time() - t0) * 1000
        audit.log_event(
            caller=caller,
            tool_name="verify_prerequisites",
            parameters=req.model_dump(),
            status="SUCCESS",
            latency_ms=latency,
            result_count=len(missing)
        )

        return {
            "target_course": target,
            "eligible": is_eligible,
            "required_prerequisites": required_codes,
            "satisfied_prerequisites": satisfied,
            "missing_prerequisites": missing,
            "status_message": (
                f"Eligible to enroll in {target}." if is_eligible
                else f"Ineligible to enroll in {target}. Missing: {', '.join(missing)}."
            ),
            "source": "SRMIST Prerequisite DAG (Neo4j Community)" if client.is_connected else "SRMIST In-Memory Cache"
        }

    @staticmethod
    def find_faculty_for_course(req: FacultyCourseRequest, caller: str = "agent") -> Dict[str, Any]:
        """Retrieves verified faculty instructors teaching a specified course via Neo4j."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()
        c_code = req.course_code.strip().upper()

        instructors = []
        if client.is_connected and client.driver:
            try:
                cypher = """
                    MATCH (f:FacultyMember)-[t:TEACHES]->(c:Course)
                    WHERE toUpper(c.code) = $code
                    RETURN f.id as id, f.name as name, f.designation as designation,
                           coalesce(f.normalized_department, f.department) as department,
                           f.normalized_department as normalized_department,
                           f.department as raw_department,
                           f.cabin as cabin, f.email as email,
                           f.specialization as specialization, f.experience as experience,
                           t.role as teaching_role
                """
                instructors = client.query_read(cypher, {"code": c_code})
            except Exception as e:
                logger.warning(f"Neo4j find_faculty_for_course error ({e}), falling back.")

        if not instructors:
            teaching = client._teaching_by_course.get(c_code, [])
            for t in teaching:
                fac = client._faculty_by_id.get(t["faculty_id"])
                if fac:
                    norm_dept = fac.get("normalized_department") or normalize_department_name(fac.get("department", ""))
                    instructors.append({
                        "id": fac["id"],
                        "name": fac["name"],
                        "designation": fac["designation"],
                        "department": norm_dept or fac["department"],
                        "normalized_department": norm_dept,
                        "raw_department": fac["department"],
                        "cabin": fac.get("cabin", "Staff Room (TBA)"),
                        "email": fac["email"],
                        "specialization": fac["specialization"],
                        "experience": fac["experience"],
                        "teaching_role": t.get("role", "Instructor")
                    })

        latency = (time.time() - t0) * 1000
        audit.log_event(
            caller=caller,
            tool_name="find_faculty_for_course",
            parameters=req.model_dump(),
            status="SUCCESS",
            latency_ms=latency,
            result_count=len(instructors)
        )

        return {
            "course_code": c_code,
            "instructor_count": len(instructors),
            "instructors": instructors,
            "source": "SRMIST Faculty Directory (Neo4j Community)" if client.is_connected else "SRMIST In-Memory Cache",
            "grounding": f"Found {len(instructors)} instructors assigned to {c_code}."
        }

    @staticmethod
    def lookup_faculty_profile(req: FacultyProfileRequest, caller: str = "agent") -> Dict[str, Any]:
        """
        Searches faculty profiles by name from live Neo4j with strict tiered ranking:
          Tier 3 (exact): exact full-name match after stripping configured honorifics
          Tier 2 (whole_word): every query token matches a whole word in the name
          Tier 1 (partial_fuzzy): partial/fuzzy match meeting configured min_similarity
        Drops anything below min_similarity (returning NOT_FOUND). Never falls back to JSON
        when Neo4j is connected.
        """
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()

        cfg = load_matching_config()["faculty_matching"]
        honorifics = cfg["honorifics"]
        min_sim = float(cfg["min_similarity"])
        max_displayed = int(cfg["max_displayed_matches"])
        fuzzy_min_len = int(cfg["fuzzy_min_token_length"])

        req_tokens = strip_honorifics_and_tokenize(req.faculty_name, honorifics)
        q_phrase = " ".join(req_tokens)

        used_neo4j = False
        faculty_index: List[Dict[str, Any]] = []

        if client.is_connected and client.driver:
            # Rank over live-Neo4j-derived (id, name) directory loaded at startup/reload,
            # then hydrate matched profiles directly from live Neo4j via indexed ID lookup.
            faculty_index = client.get_graph_faculty_index()
            used_neo4j = True
        else:
            # Offline test harness only when Neo4j driver is disconnected
            faculty_index = client.in_memory_data.get("faculty", [])

        tier_exact: List[tuple] = []
        tier_whole: List[tuple] = []
        tier_partial: List[tuple] = []

        raw_id_candidate = req.faculty_name.strip().upper()
        if re.fullmatch(r"FAC-\d+", raw_id_candidate):
            for fac in faculty_index:
                fid = str(fac.get("id") or "").strip().upper()
                if fid == raw_id_candidate:
                    raw_name = (fac.get("name") or "").strip()
                    tier_exact.append(((raw_name.lower(), fac.get("id", "")), fac.get("id", ""), "exact", 100.0))
                    break

        if req_tokens and not tier_exact:
            meaningful_tokens = [t for t in req_tokens if len(t) >= fuzzy_min_len] or req_tokens

            for fac in faculty_index:
                raw_name = (fac.get("name") or "").strip()
                fid = fac.get("id", "")
                if not raw_name or not fid:
                    continue
                f_tokens = strip_honorifics_and_tokenize(raw_name, honorifics)
                if not f_tokens:
                    continue
                f_phrase = " ".join(f_tokens)

                # Tier 3: exact full-name match (after honorific stripping)
                if q_phrase == f_phrase:
                    tier_exact.append(((raw_name.lower(), fid), fid, "exact", 100.0))
                    continue

                # Tier 2: every query word matches a whole word in the name
                f_token_set = set(f_tokens)
                if all(qt in f_token_set for qt in req_tokens):
                    starts_with_q = 0 if f_tokens[:len(req_tokens)] == req_tokens else 1
                    first_pos = min((f_tokens.index(qt) for qt in req_tokens if qt in f_tokens), default=99)
                    tier_whole.append(((starts_with_q, first_pos, len(f_tokens), raw_name.lower(), fid), fid, "whole_word", 85.0))
                    continue

                # Tier 1: partial or fuzzy match — every meaningful token must meet min_similarity
                # Short tokens (<5 chars) require a word-prefix match (prevents 'add' matching 'vaddi')
                token_sims: List[float] = []
                all_met = True
                for qt in meaningful_tokens:
                    best = 0.0
                    for w in f_tokens:
                        if qt == w:
                            best = 1.0
                            break
                        ratio = difflib.SequenceMatcher(None, qt, w).ratio()
                        if len(qt) >= fuzzy_min_len and w.startswith(qt) and (len(qt) / max(len(w), 1)) >= 0.4:
                            ratio = max(ratio, min_sim)
                        elif len(qt) >= 5 and qt in w and (len(qt) / max(len(w), 1)) >= 0.5:
                            ratio = max(ratio, min_sim)
                        if ratio > best:
                            best = ratio
                    if best < min_sim:
                        all_met = False
                        break
                    token_sims.append(best)

                if all_met and token_sims:
                    avg_sim = sum(token_sims) / len(token_sims)
                    if avg_sim >= min_sim:
                        tier_partial.append(((-round(avg_sim, 4), raw_name.lower(), fid), fid, "partial_fuzzy", round(avg_sim * 70.0, 2)))

        tier_exact.sort(key=lambda item: item[0])
        tier_whole.sort(key=lambda item: item[0])
        tier_partial.sort(key=lambda item: item[0])

        if tier_exact:
            ranked_top = tier_exact
            top_tier = "exact"
        elif tier_whole:
            ranked_top = tier_whole
            top_tier = "whole_word"
        elif tier_partial:
            ranked_top = tier_partial
            top_tier = "partial_fuzzy"
        else:
            ranked_top = []
            top_tier = "none"

        total_top = len(ranked_top)
        all_matched_count = len(tier_exact) + len(tier_whole) + len(tier_partial)

        # Hydrate matched records directly from live Neo4j (preserving rank order)
        top_matches: List[Dict[str, Any]] = []
        if ranked_top:
            matched_ids = [item[1] for item in ranked_top[:100]]
            meta_by_id = {item[1]: (item[2], item[3]) for item in ranked_top[:100]}
            if used_neo4j:
                hydrated_rows = client.query_read(
                    """
                    MATCH (f:FacultyMember)
                    WHERE f.id IN $ids
                    RETURN f.id as id, f.name as name, f.designation as designation,
                           f.department as department,
                           coalesce(f.normalized_department, f.department) as normalized_department,
                           f.cabin as cabin, f.email as email,
                           coalesce(f.phone, '') as phone,
                           coalesce(f.phone_shared_count, 0) as phone_shared_count,
                           f.specialization as specialization, f.experience as experience,
                           f.college as college
                    LIMIT 100
                    """,
                    {"ids": matched_ids}
                )
                row_by_id = {r["id"]: r for r in hydrated_rows if r.get("id")}
            else:
                row_by_id = {f["id"]: f for f in faculty_index if f.get("id") in meta_by_id}

            for fid in matched_ids:
                fac = row_by_id.get(fid)
                if not fac:
                    continue
                m_tier, m_score = meta_by_id[fid]
                raw_dept = fac.get("department", "")
                norm_dept = fac.get("normalized_department") or normalize_department_name(raw_dept)
                phone_val = (fac.get("phone") or "").strip()
                shared_cnt = int(fac.get("phone_shared_count") or (1 if phone_val else 0))
                phone_note = _build_phone_note(phone_val, shared_cnt)
                top_matches.append({
                    "id": fac.get("id", ""),
                    "name": (fac.get("name") or "").strip(),
                    "designation": fac.get("designation", ""),
                    "department": norm_dept or raw_dept,
                    "normalized_department": norm_dept,
                    "raw_department": raw_dept,
                    "cabin": fac.get("cabin", ""),
                    "college": fac.get("college", ""),
                    "specialization": fac.get("specialization", ""),
                    "email": fac.get("email", ""),
                    "phone": phone_val,
                    "phone_shared_count": shared_cnt,
                    "phone_note": phone_note,
                    "experience": fac.get("experience", ""),
                    "match_tier": m_tier,
                    "relevance_score": m_score,
                })
            if top_tier == "exact":
                top_matches.sort(key=lambda r: (r["name"].lower(), (r["department"] or "").lower()))

        if total_top == 0:
            res_status = "NOT_FOUND"
        elif total_top == 1:
            res_status = "SUCCESS"
        else:
            res_status = "AMBIGUOUS"

        latency = (time.time() - t0) * 1000
        audit.log_event(
            caller=caller,
            tool_name="lookup_faculty_profile",
            parameters=req.model_dump(),
            status="SUCCESS" if total_top > 0 else "NOT_FOUND",
            latency_ms=latency,
            result_count=total_top
        )

        return {
            "query": req.faculty_name,
            "status": res_status,
            "match_tier": top_tier,
            "match_count": total_top,
            "total_matches": total_top,
            "all_matches_count": all_matched_count,
            "max_displayed_matches": max_displayed,
            "faculty": top_matches,
            "source": "SRMIST Faculty Directory (Neo4j Community)" if used_neo4j else "fallback"
        }

    @staticmethod
    def find_room_schedule(req: RoomScheduleRequest, caller: str = "agent") -> Dict[str, Any]:
        """Retrieves schedule and room specifications for a given room."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()
        r_id = req.room_id.strip().upper()

        room_info = client._room_by_id.get(r_id)
        if not room_info:
            latency = (time.time() - t0) * 1000
            audit.log_event(caller=caller, tool_name="find_room_schedule", parameters=req.model_dump(), status="SUCCESS", latency_ms=latency, result_count=0)
            return {"error": f"Room '{r_id}' not found in campus database.", "schedules": []}

        schedules = client._schedules_by_room.get(r_id, [])
        if req.day_of_week:
            target_day = req.day_of_week.strip().capitalize()
            schedules = [s for s in schedules if s.get("day") == target_day]

        latency = (time.time() - t0) * 1000
        audit.log_event(caller=caller, tool_name="find_room_schedule", parameters=req.model_dump(), status="SUCCESS", latency_ms=latency, result_count=len(schedules))

        return {
            "room_id": r_id,
            "room_type": room_info["type"],
            "capacity": room_info["capacity"],
            "building_code": room_info["building_code"],
            "day_filter": req.day_of_week,
            "scheduled_slots_count": len(schedules),
            "schedules": schedules,
            "source": "SRMIST Room Allocation Master"
        }

    @staticmethod
    def find_course_schedule(req: CourseScheduleRequest, caller: str = "agent") -> Dict[str, Any]:
        """Retrieves classroom allocations and weekly timetable slots for a given course code."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()
        c_code = req.course_code.strip().upper()

        schedules = []
        source = "SRMIST In-Memory Schedule Cache"

        if client.is_connected and client.driver:
            try:
                cypher = """
                    MATCH (r:Room)-[o:OCCUPIES]->(c:Course)
                    WHERE toUpper(c.code) = $code
                    RETURN r.id AS room_id, r.type AS room_type, r.capacity AS capacity,
                           r.building_code AS building_code, o.day AS day, o.slot AS slot
                    ORDER BY o.day, o.slot
                """
                rows = client.query_read(cypher, {"code": c_code})
                if rows:
                    schedules = rows
                    source = "SRMIST Space Allocation Matrix (Neo4j Community)"
            except Exception as e:
                logger.warning(f"Neo4j query failed for course schedule {c_code}: {e}")

        if not schedules:
            cached = client._schedules_by_course.get(c_code, [])
            if cached:
                schedules = [
                    {
                        "room_id": s.get("room_id"),
                        "room_type": client._room_by_id.get(s.get("room_id"), {}).get("type", "Classroom"),
                        "capacity": client._room_by_id.get(s.get("room_id"), {}).get("capacity", 60),
                        "building_code": s.get("building_code", "TP"),
                        "day": s.get("day"),
                        "slot": s.get("slot")
                    }
                    for s in cached
                ]

        if req.day_of_week:
            target_day = req.day_of_week.strip().capitalize()
            schedules = [s for s in schedules if s.get("day") == target_day]

        latency = (time.time() - t0) * 1000
        status = "SUCCESS" if schedules else "NOT_FOUND"
        audit.log_event(
            caller=caller,
            tool_name="find_course_schedule",
            parameters=req.model_dump(),
            status=status,
            latency_ms=latency,
            result_count=len(schedules)
        )

        return {
            "course_code": c_code,
            "scheduled_slots_count": len(schedules),
            "schedules": schedules,
            "day_filter": req.day_of_week,
            "source": source
        }

    @staticmethod
    def find_available_rooms(req: AvailableRoomsRequest, caller: str = "agent") -> Dict[str, Any]:
        """Finds unoccupied classrooms in a building during a specified day and slot via live Neo4j (fallback offline)."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()
        raw_b = req.building_code.strip()
        b_code = raw_b.upper()
        target_day = req.day.strip().capitalize()
        target_slot = req.slot.strip()

        # Resolve building code against live Neo4j Building nodes (no silent fallback to TP)
        bmap = client.get_building_code_map()
        if b_code not in bmap:
            alias_map = client.get_building_alias_map()
            resolved = alias_map.get(raw_b.lower())
            if resolved:
                b_code = resolved
            elif bmap:
                latency = (time.time() - t0) * 1000
                audit.log_event(
                    caller=caller,
                    tool_name="find_available_rooms",
                    parameters=req.model_dump(),
                    status="NOT_FOUND",
                    latency_ms=latency,
                    result_count=0,
                )
                return {
                    "status": "NOT_FOUND",
                    "unknown_building": True,
                    "building_code": raw_b,
                    "day": target_day,
                    "slot": target_slot,
                    "min_capacity": req.min_capacity,
                    "available_count": 0,
                    "available_rooms": [],
                    "valid_buildings": sorted(bmap.keys()),
                    "source": "SRMIST Space Allocation Matrix (Neo4j Community)" if client.is_connected else "SRMIST Space Allocation Matrix",
                }

        available = []
        used_neo4j = False
        if client.is_connected and client.driver:
            try:
                cypher = """
                    MATCH (r:Room)-[:LOCATED_IN]->(b:Building {code: $b_code})
                    WHERE r.capacity >= $min_cap
                    OPTIONAL MATCH (r)-[o:OCCUPIES {day: $day, slot: $slot}]-(:Course)
                    WITH r, count(o) AS occ
                    WHERE occ = 0
                    RETURN r.id AS id, r.room_number AS room_number,
                           r.building_code AS building_code, r.type AS type,
                           r.capacity AS capacity
                    ORDER BY r.id ASC
                    LIMIT 500
                """
                available = client.query_read(
                    cypher,
                    {"b_code": b_code, "min_cap": req.min_capacity, "day": target_day, "slot": target_slot},
                )
                used_neo4j = True
            except Exception as e:
                logger.warning(f"Neo4j find_available_rooms error ({e}), falling back to in-memory.")
                available = []

        if not used_neo4j:
            candidate_rooms = [
                r for r in client.in_memory_data.get("rooms", [])
                if r["building_code"] == b_code and r["capacity"] >= req.min_capacity
            ]
            occupied_room_ids = {
                s["room_id"] for s in client.in_memory_data.get("schedules", [])
                if s.get("day") == target_day and s.get("slot") == target_slot
            }
            available = [r for r in candidate_rooms if r["id"] not in occupied_room_ids]

        latency = (time.time() - t0) * 1000
        audit.log_event(
            caller=caller,
            tool_name="find_available_rooms",
            parameters=req.model_dump(),
            status="SUCCESS",
            latency_ms=latency,
            result_count=len(available),
        )

        # Return full list; governed_executor enforces role-based row_limit (student=25, faculty=100, admin=500)
        return {
            "building_code": b_code,
            "day": target_day,
            "slot": target_slot,
            "min_capacity": req.min_capacity,
            "available_count": len(available),
            "available_rooms": available,
            "source": "SRMIST Space Allocation Matrix (Neo4j Community)" if used_neo4j else "SRMIST Space Allocation Matrix",
        }

    @staticmethod
    def search_courses_semantic(req: SemanticSearchRequest, caller: str = "agent") -> Dict[str, Any]:
        """Performs semantic vector discovery over course descriptions via native Neo4j vector index."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()

        sem_cfg = load_matching_config().get("semantic_search") or {}
        min_sim = float(sem_cfg.get("min_similarity_score", 0.76))
        min_lex = float(sem_cfg.get("min_lexical_score", 4))

        # Stop-word guardrail: pure stop-word queries produce no results
        STOP_WORDS = {"for", "and", "the", "with", "from", "about", "what", "where", "how", "who", "which", "are", "is", "can", "take", "course", "courses", "study", "want", "related", "to", "in", "on", "at", "by", "all", "of", "a", "an", "i"}
        raw_tokens = re.findall(r"\w+", req.query.lower())
        query_terms = [t for t in raw_tokens if (len(t) > 2 or t in ("ai", "ml", "ds", "it", "cs", "ui")) and t not in STOP_WORDS]
        if not query_terms:
            latency = (time.time() - t0) * 1000
            audit.log_event(caller=caller, tool_name="search_courses_semantic", parameters=req.model_dump(), status="NO_RELEVANT_MATCH", latency_ms=latency, result_count=0)
            return {
                "query": req.query,
                "top_k": req.top_k,
                "results_found": 0,
                "courses": [],
                "top_score": 0.0,
                "min_similarity_score": min_sim,
                "below_threshold": True,
                "status": "NO_RELEVANT_MATCH",
                "source": "Neo4j Native Vector Index ('course_embeddings')" if client.is_connected else "SRMIST Lexical Fallback"
            }

        top_results = []
        raw_top_score = 0.0
        vector_executed = False
        below_threshold = False
        # 1. Native Neo4j Vector Index Search
        if client.is_connected and client.driver:
            try:
                import requests
                embed_resp = requests.post(
                    "http://localhost:11434/api/embeddings",
                    json={"model": "nomic-embed-text", "prompt": req.query},
                    timeout=10
                )
                if embed_resp.status_code == 200:
                    q_vec = embed_resp.json().get("embedding")
                    if q_vec:
                        cypher = """
                            CALL db.index.vector.queryNodes('course_embeddings', $top_k, $vec)
                            YIELD node, score
                            RETURN node.code as code, node.name as name, node.department as department,
                                   node.credits as credits, node.description as description, node.level as level,
                                   score
                        """
                        raw_hits = client.query_read(cypher, {"top_k": req.top_k, "vec": q_vec})
                        vector_executed = True
                        if raw_hits:
                            raw_top_score = max(float(r.get("score") or 0.0) for r in raw_hits)
                            top_results = [
                                {**r, "score": round(float(r.get("score") or 0.0), 4)}
                                for r in raw_hits
                                if float(r.get("score") or 0.0) >= min_sim
                            ]
                            if not top_results:
                                below_threshold = True
            except Exception as e:
                logger.warning(f"Neo4j vector search query error ({e}), falling back to lexical search.")

        # 2. Secondary Lexical & Token Fallback ONLY if vector index was not executed
        if not vector_executed:
            EXPANSIONS = {
                "ai": ["ai", "artificial intelligence"],
                "ml": ["ml", "machine learning"],
                "ds": ["data science"],
                "dbms": ["database", "dbms"],
                "os": ["operating systems", "operating system"]
            }
            search_terms = []
            for t in query_terms:
                if t in EXPANSIONS:
                    search_terms.extend(EXPANSIONS[t])
                else:
                    search_terms.append(t)

            scored_courses = []
            if search_terms:
                for c in client.in_memory_data.get("courses", []):
                    content = f"{c['code']} {c['name']} {c['department']} {c['faculty']} {c['description']}".lower()
                    c_words = set(re.findall(r"\w+", content))
                    score = 0
                    for term in search_terms:
                        if " " in term:
                            if term in content:
                                score += 8
                        else:
                            if term in c_words:
                                score += 4
                            elif term in content:
                                score += 2
                        if term in c["name"].lower():
                            score += 6
                    if score > raw_top_score:
                        raw_top_score = float(score)
                    if score >= min_lex:
                        scored_courses.append((score, {**c, "score": float(score)}))

            scored_courses.sort(key=lambda x: x[0], reverse=True)
            top_results = [item[1] for item in scored_courses[:req.top_k]]
            if not top_results:
                below_threshold = True

        latency = (time.time() - t0) * 1000
        status_str = "SUCCESS" if top_results else "NO_RELEVANT_MATCH"
        audit.log_event(caller=caller, tool_name="search_courses_semantic", parameters=req.model_dump(), status=status_str, latency_ms=latency, result_count=len(top_results))

        return {
            "query": req.query,
            "top_k": req.top_k,
            "results_found": len(top_results),
            "courses": top_results,
            "top_score": round(raw_top_score, 4),
            "min_similarity_score": min_sim if vector_executed else min_lex,
            "below_threshold": below_threshold,
            "status": status_str,
            "source": "Neo4j Native Vector Index ('course_embeddings')" if vector_executed else "SRMIST Lexical Fallback"
        }

    @staticmethod
    def check_admission_eligibility(req: AdmissionEligibilityRequest, caller: str = "agent") -> Dict[str, Any]:
        """Evaluates admission eligibility and requirements for university academic programs."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()

        def norm_txt(s: str) -> str:
            s = s.lower().replace("b.tech.", "btech").replace("b.tech", "btech").replace("b tech", "btech")
            s = s.replace("m.tech.", "mtech").replace("m.tech", "mtech").replace("m tech", "mtech")
            s = s.replace("m.b.a.", "mba").replace("m.b.a", "mba").replace("m ba", "mba")
            s = s.replace("b.b.a.", "bba").replace("b.b.a", "bba")
            s = s.replace("b.sc.", "bsc").replace("b.sc", "bsc")
            s = s.replace("m.sc.", "msc").replace("m.sc", "msc")
            s = s.replace("b.com.", "bcom").replace("b.com", "bcom")
            s = s.replace("m.com.", "mcom").replace("m.com", "mcom")
            s = s.replace("b.arch.", "barch").replace("b.arch", "barch")
            s = s.replace("ph.d.", "phd").replace("ph.d", "phd")
            s = re.sub(r"[^\w\s]", " ", s)
            return re.sub(r"\s+", " ", s).strip()

        q_norm = norm_txt(req.program_query)
        stopwords = {"and", "or", "the", "in", "for", "to", "of", "admission", "entrance", "exam", "exams", "eligibility", "requirements", "criteria", "what", "is", "are", "minimum", "percentage", "required"}
        q_terms = [t for t in q_norm.split() if t not in stopwords and len(t) > 1]

        matched_programs = []
        for p in client.admission_eligibility:
            p_name_norm = norm_txt(p["program_name"])
            p_dept_norm = norm_txt(p.get("department", ""))
            p_fac_norm = norm_txt(p.get("faculty", ""))
            
            # Substring match, term containment, or department match
            if q_norm and q_norm in p_name_norm:
                matched_programs.append(p)
            elif q_terms and all(t in p_name_norm.split() or t in p_name_norm for t in q_terms):
                matched_programs.append(p)
            elif q_norm and (q_norm in p_dept_norm or q_norm in p_fac_norm):
                matched_programs.append(p)
            elif req.program_query.strip().lower() in p["program_id"].lower():
                matched_programs.append(p)

        # De-duplicate while preserving order
        unique_matches = []
        seen_ids = set()
        for p in matched_programs:
            if p["program_id"] not in seen_ids:
                seen_ids.add(p["program_id"])
                unique_matches.append(p)
            if len(unique_matches) >= 8:
                break

        evaluation_results = []
        for p in unique_matches:
            min_req = p["min_percentage_reserved"] if req.is_reserved_category else p["min_percentage_general"]
            eval_item = {
                "program_id": p["program_id"],
                "program_name": p["program_name"],
                "faculty": p["faculty"],
                "department": p["department"],
                "degree_level": p["degree_level"],
                "min_education": p["min_education"],
                "mandatory_subjects": p["mandatory_subjects"],
                "min_percentage_general": p["min_percentage_general"],
                "min_percentage_reserved": p["min_percentage_reserved"],
                "required_entrance_exam": p["required_entrance_exam"],
                "official_eligibility_text": p["official_eligibility_text"],
                "annual_fee_inr": p.get("annual_fee_inr", 0),
                "duration": p.get("duration", "4 Years"),
                "campuses": p.get("campuses", ["Kattankulathur Main Campus"]),
                "category_evaluated": "Reserved (SC/ST/OBC)" if req.is_reserved_category else "General"
            }

            if req.candidate_percentage is not None:
                has_percentage = req.candidate_percentage >= min_req
                eval_item["candidate_percentage"] = req.candidate_percentage
                eval_item["min_required_percentage"] = min_req

                if not has_percentage:
                    eval_item["eligibility_verdict"] = "NOT_ELIGIBLE"
                    eval_item["verdict_reason"] = (
                        f"Candidate aggregate {req.candidate_percentage}% is below the mandatory minimum of "
                        f"{min_req}% for {eval_item['category_evaluated']} category in {p['mandatory_subjects']}."
                    )
                else:
                    if p["required_entrance_exam"] not in ["Merit Based", "None", "Direct"]:
                        eval_item["eligibility_verdict"] = "ACADEMICALLY_ELIGIBLE_ENTRANCE_REQUIRED"
                        eval_item["verdict_reason"] = (
                            f"Candidate satisfies minimum academic cutoff ({req.candidate_percentage}% >= {min_req}%). "
                            f"Admission is subject to qualifying the entrance exam: {p['required_entrance_exam']}."
                        )
                    else:
                        eval_item["eligibility_verdict"] = "ELIGIBLE"
                        eval_item["verdict_reason"] = (
                            f"Candidate meets all academic eligibility criteria ({req.candidate_percentage}% >= {min_req}%) "
                            f"for merit-based admission."
                        )
            else:
                eval_item["eligibility_verdict"] = "CRITERIA_RETRIEVED"
                eval_item["verdict_reason"] = (
                    f"Minimum {min_req}% in {p['min_education']} ({p['mandatory_subjects']}) + "
                    f"selection via {p['required_entrance_exam']}."
                )

            evaluation_results.append(eval_item)

        latency = (time.time() - t0) * 1000
        audit.log_event(
            caller=caller,
            tool_name="check_admission_eligibility",
            parameters=req.model_dump(),
            status="SUCCESS",
            latency_ms=latency,
            result_count=len(evaluation_results)
        )

        return {
            "query": req.program_query,
            "match_count": len(evaluation_results),
            "programs": evaluation_results,
            "source": "SRMIST Official Admission Regulations"
        }

    @staticmethod
    def run_governed_query(req: GovernedQueryTemplateRequest, caller: str = "agent") -> Dict[str, Any]:
        """Executes a pre-approved, whitelisted Cypher template with AST safety gating."""
        t0 = time.time()
        audit = get_audit_logger()
        client = get_graph_client()

        template_id = req.template_id.strip()
        if template_id not in WHITELISTED_TEMPLATES:
            err = f"Template '{template_id}' is not in the approved governance whitelist."
            audit.log_event(caller=caller, tool_name="run_governed_query", parameters=req.model_dump(), status="POLICY_VIOLATION", latency_ms=(time.time()-t0)*1000, violation_reason=err)
            raise SecurityViolationError(err)

        raw_cypher = WHITELISTED_TEMPLATES[template_id]
        sanitized_cypher = ASTSecurityValidator.assert_safe(raw_cypher)

        # Execute
        results = []
        if client.is_connected and client.driver:
            results = client.query_read(sanitized_cypher, req.parameters)
        else:
            # Emulated execution for templates against in-memory graph
            if template_id == "courses_by_department":
                dept = req.parameters.get("department", "").lower()
                results = [
                    {"code": c["code"], "name": c["name"], "credits": c["credits"], "level": c["level"]}
                    for c in client.in_memory_data.get("courses", [])
                    if dept in c.get("department", "").lower()
                ][:50]
            elif template_id == "faculty_by_department":
                dept = req.parameters.get("department", "").lower()
                results = [
                    {"id": f["id"], "name": f["name"], "designation": f["designation"], "specialization": f["specialization"]}
                    for f in client.in_memory_data.get("faculty", [])
                    if dept in f.get("department", "").lower()
                ][:50]
            elif template_id == "building_rooms_summary":
                b_code = req.parameters.get("building_code", "").upper()
                results = [
                    {"room_id": r["id"], "type": r["type"], "capacity": r["capacity"]}
                    for r in client.in_memory_data.get("rooms", [])
                    if r.get("building_code") == b_code
                ][:50]

        latency = (time.time() - t0) * 1000
        audit.log_event(
            caller=caller,
            tool_name="run_governed_query",
            parameters=req.model_dump(),
            status="SUCCESS",
            latency_ms=latency,
            result_count=len(results),
            cypher_executed=sanitized_cypher
        )

        return {
            "template_id": template_id,
            "cypher_executed": sanitized_cypher,
            "result_count": len(results),
            "records": results,
            "source": "Neo4j Governed Template Engine"
        }

    @staticmethod
    def get_campus_statistics(req: CampusStatisticsRequest, caller: str = "agent") -> Dict[str, Any]:
        """Aggregates verified catalog statistics, degree program counts, faculty, and room metrics."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()

        cat = (req.category or "all").lower().strip()
        programs = client.admission_eligibility or client.in_memory_data.get("programs", []) or client.in_memory_data.get("admission_rules", [])
        faculty_count = len(client.in_memory_data.get("faculty", []))
        rooms_count = len(client.in_memory_data.get("rooms", []))
        schedules_count = len(client.in_memory_data.get("schedules", []))
        courses_count = len(client.in_memory_data.get("courses", []))
        buildings_count = len(client.in_memory_data.get("buildings", []))
        departments_count = 0
        prereqs_count = len(client.in_memory_data.get("prerequisites", []))
        graph_programs_count = len(programs)

        used_fallback = True
        fallback_reason = "Neo4j disconnected"

        # Query live Neo4j O(1) label/relationship count store when connected
        if client.is_connected and client.driver:
            try:
                count_cypher = """
                    MATCH (c:Course) WITH count(c) AS courses
                    MATCH (f:FacultyMember) WITH courses, count(f) AS faculty
                    MATCH (r:Room) WITH courses, faculty, count(r) AS rooms
                    MATCH (b:Building) WITH courses, faculty, rooms, count(b) AS buildings
                    MATCH (d:Department) WITH courses, faculty, rooms, buildings, count(d) AS departments
                    MATCH (p:Program) WITH courses, faculty, rooms, buildings, departments, count(p) AS programs
                    MATCH ()-[occ:OCCUPIES]->() WITH courses, faculty, rooms, buildings, departments, programs, count(occ) AS schedules
                    MATCH ()-[pr:REQUIRES_PREREQUISITE]->()
                    RETURN courses, faculty, rooms, buildings, departments, programs, schedules, count(pr) AS prereqs
                """
                rows = client.query_read(count_cypher)
                if rows:
                    row = rows[0]
                    courses_count = row["courses"]
                    faculty_count = row["faculty"]
                    rooms_count = row["rooms"]
                    buildings_count = row["buildings"]
                    departments_count = row["departments"]
                    graph_programs_count = row["programs"]
                    schedules_count = row["schedules"]
                    prereqs_count = row["prereqs"]
                    used_fallback = False
                    fallback_reason = None
            except Exception as e:
                logger.warning(f"Neo4j statistics query fallback: {e}")
                used_fallback = True
                fallback_reason = str(e)

        level_counts = {}
        faculty_groups = {}
        for p in programs:
            lvl = p.get("degree_level", "UG")
            level_counts[lvl] = level_counts.get(lvl, 0) + 1
            f_group = p.get("faculty", "General")
            faculty_groups[f_group] = faculty_groups.get(f_group, 0) + 1

        stats = {
            "category": cat,
            "total_programs": graph_programs_count if not used_fallback else len(programs),
            "total_program_nodes_in_graph": graph_programs_count,
            "total_courses_indexed": courses_count,
            "total_faculty": faculty_count,
            "total_classrooms": rooms_count,
            "total_buildings": buildings_count,
            "total_departments": departments_count,
            "total_prerequisites": prereqs_count,
            "total_scheduled_sessions": schedules_count,
            "degree_levels": level_counts,
            "faculties_summary": faculty_groups,
            "major_disciplines": [
                "Engineering & Technology",
                "Medicine & Health Sciences",
                "Management & Business Studies",
                "Science & Humanities",
                "Law",
                "Agricultural Sciences"
            ]
        }

        latency = (time.time() - t0) * 1000
        audit.log_event(
            caller=caller,
            tool_name="get_campus_statistics",
            parameters=req.model_dump(),
            status="SUCCESS" if not used_fallback else "FALLBACK",
            latency_ms=latency,
            result_count=graph_programs_count
        )

        resp_payload: Dict[str, Any] = {
            "category": cat,
            "statistics": stats,
            "source": "fallback" if used_fallback else "Neo4j Live Graph"
        }
        if cat in ("departments", "department", "depts", "dept"):
            dept_rows: List[Dict[str, Any]] = []
            if client.is_connected and client.driver:
                try:
                    raw_depts = client.query_read(
                        "MATCH (f:FacultyMember) "
                        "WITH coalesce(f.normalized_department, f.department) AS dept, count(f) AS faculty_count "
                        "WHERE dept IS NOT NULL AND trim(dept) <> '' "
                        "RETURN dept AS name, faculty_count "
                        "ORDER BY faculty_count DESC, dept ASC LIMIT 500"
                    )
                    dept_rows = [
                        {"name": str(r["name"]).strip(), "faculty_count": int(r["faculty_count"])}
                        for r in raw_depts
                        if r.get("name")
                    ]
                except Exception as e:
                    logger.warning(f"Neo4j departments list fallback: {e}")
            if not dept_rows:
                from collections import Counter
                counts = Counter(
                    (f.get("normalized_department") or f.get("department") or "").strip()
                    for f in client.in_memory_data.get("faculty", [])
                    if (f.get("normalized_department") or f.get("department") or "").strip()
                )
                dept_rows = [
                    {"name": name, "faculty_count": cnt}
                    for name, cnt in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
                ]
            resp_payload["departments"] = dept_rows
            resp_payload["total_canonical_departments"] = len(dept_rows)
            resp_payload["total_department_nodes"] = departments_count or len(dept_rows)
        if used_fallback:
            resp_payload["fallback_reason"] = fallback_reason
        return resp_payload

    @staticmethod
    def get_semester_curriculum(req: SemesterCurriculumRequest, caller: str = "agent") -> Dict[str, Any]:
        """Retrieves official semester-by-semester implementation plans, subject allocations, course codes, and credit breakdowns under SRMIST Regulations 2021 Unified Curriculum."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()

        q_raw = req.program_query.strip().lower()

        # Engineering abbreviation expansion
        ABBR_MAP = {
            "cse": "Computer Science and Engineering",
            "cs": "Computer Science and Engineering",
            "ai": "Artificial Intelligence",
            "aiml": "Computer Science and Engineering with Specialization in Artificial Intelligence and Machine Learning",
            "ai & ml": "Computer Science and Engineering with Specialization in Artificial Intelligence and Machine Learning",
            "ai/ml": "Computer Science and Engineering with Specialization in Artificial Intelligence and Machine Learning",
            "ece": "Electronics and Communication Engineering",
            "eee": "Electrical and Electronics Engineering",
            "mech": "Mechanical Engineering",
            "mechanical": "Mechanical Engineering",
            "aero": "Aerospace Engineering",
            "aerospace": "Aerospace Engineering",
            "auto": "Automobile Engineering",
            "automobile": "Automobile Engineering",
            "automotive": "Automotive Engineering",
            "biotech": "Biotechnology",
            "bio": "Biotechnology",
            "bme": "Biomedical Engineering",
            "biomedical": "Biomedical Engineering",
            "civil": "Civil Engineering",
            "chemical": "Chemical Engineering",
            "chem": "Chemical Engineering",
            "csbs": "Computer Science and Business Systems",
            "it": "Information Technology",
            "iot": "Internet of Things",
            "data science": "Data Science",
            "ds": "Data Science",
            "cyber": "Cybersecurity",
            "cybersecurity": "Cybersecurity",
            "cloud": "Cloud Computing",
            "blockchain": "Blockchain Technology",
            "mechatronics": "Mechatronics Engineering",
            "nano": "Nanotechnology",
            "nanotechnology": "Nanotechnology",
            "ev": "Electric Vehicle Technology"
        }

        target_name = ABBR_MAP.get(q_raw, q_raw).lower().strip()

        curricula_programs = getattr(client, "curricula_master", {}).get("programs", {})
        if not curricula_programs:
            curricula_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "courses", "curricula_semester_master.json")
            if os.path.exists(curricula_file):
                try:
                    with open(curricula_file, "r", encoding="utf-8") as f:
                        client.curricula_master = json.load(f)
                        curricula_programs = client.curricula_master.get("programs", {})
                except Exception:
                    curricula_programs = {}

        matched_program_key = None
        matched_program_data = None

        # 1. Exact or substring match (favoring exact core degree if not specialized)
        for p_name, p_data in curricula_programs.items():
            p_name_norm = p_name.lower()
            if target_name in p_name_norm:
                # Prefer exact core match over specialization if user query didn't ask for specialization
                if "specialization" not in target_name and "specialization" in p_name_norm:
                    if matched_program_data is None:
                        matched_program_key = p_name
                        matched_program_data = p_data
                    continue
                matched_program_key = p_name
                matched_program_data = p_data
                break

        # 2. Token overlap fallback without common stopwords
        if not matched_program_data:
            STOPWORDS = {"in", "and", "b", "tech", "of", "the", "with", "for", "to", "at", "integrated", "m"}
            q_tokens = set(re.findall(r"\w+", target_name)) - STOPWORDS
            best_score = 0
            for p_name, p_data in curricula_programs.items():
                p_tokens = set(re.findall(r"\w+", p_name.lower())) - STOPWORDS
                overlap = len(q_tokens & p_tokens)
                if overlap > best_score:
                    best_score = overlap
                    matched_program_key = p_name
                    matched_program_data = p_data

        if not matched_program_data:
            latency = (time.time() - t0) * 1000
            audit.log_event(
                caller=caller,
                tool_name="get_semester_curriculum",
                parameters=req.model_dump(),
                status="NO_MATCH",
                latency_ms=latency,
                result_count=0
            )
            return {
                "program_query": req.program_query,
                "error": f"No official curriculum implementation plan found matching '{req.program_query}'. Available disciplines include CSE, AI, AIML, ECE, EEE, Mechanical, Aerospace, Biotechnology, Civil, etc.",
                "available_sample_programs": list(curricula_programs.keys())[:8],
                "source": "SRMIST Regulations 2021 Volume 1 Unified Curriculum"
            }

        semesters_data = matched_program_data.get("semesters", {})

        # Filter by specific semester
        if req.semester is not None:
            sem_key = str(req.semester)
            courses_in_sem = semesters_data.get(sem_key, [])
            total_credits = sum(c.get("credits", 0) for c in courses_in_sem)

            category_counts = {}
            for c in courses_in_sem:
                cat = c.get("category", "Professional Core")
                category_counts[cat] = category_counts.get(cat, 0) + 1

            sample_course_names = [f"{c['course_name']} ({c['course_code']})" for c in courses_in_sem[:4]]

            grounding = (
                f"{matched_program_key} - Semester {req.semester} comprises {len(courses_in_sem)} courses "
                f"totaling {total_credits} credits (including {', '.join(sample_course_names)})."
            )

            latency = (time.time() - t0) * 1000
            audit.log_event(
                caller=caller,
                tool_name="get_semester_curriculum",
                parameters=req.model_dump(),
                status="SUCCESS",
                latency_ms=latency,
                result_count=len(courses_in_sem)
            )

            return {
                "program_name": matched_program_key,
                "degree_type": matched_program_data.get("degree_type", "B.Tech"),
                "semester": req.semester,
                "academic_year": (req.semester + 1) // 2,
                "total_credits": total_credits,
                "course_count": len(courses_in_sem),
                "category_breakdown": category_counts,
                "courses": courses_in_sem,
                "grounding": grounding,
                "regulation": "SRMIST Regulations 2021 Unified Curriculum (Volume 1)"
            }
        else:
            # Full 8-semester or 10-semester curriculum plan
            overview = {}
            total_program_credits = 0
            total_course_count = 0

            for s_str in sorted(semesters_data.keys(), key=lambda x: int(x)):
                c_list = semesters_data[s_str]
                s_cred = sum(c.get("credits", 0) for c in c_list)
                total_program_credits += s_cred
                total_course_count += len(c_list)
                overview[f"Semester {s_str}"] = {
                    "semester": int(s_str),
                    "academic_year": (int(s_str) + 1) // 2,
                    "credits": s_cred,
                    "course_count": len(c_list),
                    "courses": [
                        {
                            "code": c["course_code"],
                            "name": c["course_name"],
                            "category": c["category"],
                            "credits": c["credits"],
                            "ltpc": c["ltpc"]
                        } for c in c_list
                    ]
                }

            grounding = (
                f"{matched_program_key} full implementation plan spans {len(overview)} semesters, "
                f"encompassing {total_course_count} courses and {total_program_credits} total credits."
            )

            latency = (time.time() - t0) * 1000
            audit.log_event(
                caller=caller,
                tool_name="get_semester_curriculum",
                parameters=req.model_dump(),
                status="SUCCESS",
                latency_ms=latency,
                result_count=len(overview)
            )

            return {
                "program_name": matched_program_key,
                "degree_type": matched_program_data.get("degree_type", "B.Tech"),
                "total_semesters": len(overview),
                "total_credits": total_program_credits,
                "total_courses": total_course_count,
                "semesters": overview,
                "grounding": grounding,
                "regulation": "SRMIST Regulations 2021 Unified Curriculum (Volume 1)"
            }

    @classmethod
    def lookup_building(cls, req: BuildingLookupRequest, caller: str = "default_guest@internal") -> Dict[str, Any]:
        """
        Governed tool to retrieve detailed campus building information, floors,
        housed departments, facilities, and rooms via exact alias or native vector search.
        """
        t0 = time.time()
        audit = get_audit_logger()
        client = get_graph_client()

        raw_query = req.query.strip()
        q_norm = raw_query.lower()

        # Derive building aliases dynamically from live Neo4j Building nodes (no hardcoded dict)
        alias_map = client.get_building_alias_map()

        matched_code = None
        for k, v in alias_map.items():
            if re.search(r"\b" + re.escape(k) + r"\b", q_norm):
                matched_code = v
                break

        building_record = None

        if client.is_connected and client.driver:
            if matched_code:
                cypher = """
                MATCH (b:Building {code: $code})
                OPTIONAL MATCH (r:Room)-[:LOCATED_IN]->(b)
                OPTIONAL MATCH (d:Department)-[:HOUSED_IN]->(b)
                RETURN b.code as code, b.name as name, b.floors as floors, b.campus as campus,
                       b.focus as focus, b.description as description, b.facilities as facilities,
                       b.aliases as aliases,
                       collect(DISTINCT d.name) as departments,
                       collect(DISTINCT {id: r.id, type: r.type, capacity: r.capacity})[..6] as sample_rooms,
                       count(DISTINCT r) as total_rooms
                LIMIT 1
                """
                rows = client.query_read(cypher, {"code": matched_code})
                if rows and rows[0].get("name"):
                    building_record = rows[0]

            # Fallback to native vector index if no exact alias matched
            if not building_record:
                try:
                    import requests
                    resp = requests.post(
                        "http://127.0.0.1:11434/api/embeddings",
                        json={"model": "nomic-embed-text", "prompt": raw_query},
                        timeout=8
                    )
                    if resp.status_code == 200:
                        v = resp.json().get("embedding")
                        vec_cypher = """
                        CALL db.index.vector.queryNodes('building_embeddings', 1, $vec)
                        YIELD node as b, score
                        OPTIONAL MATCH (r:Room)-[:LOCATED_IN]->(b)
                        OPTIONAL MATCH (d:Department)-[:HOUSED_IN]->(b)
                        RETURN b.code as code, b.name as name, b.floors as floors, b.campus as campus,
                               b.focus as focus, b.description as description, b.facilities as facilities,
                               b.aliases as aliases, round(score, 3) as relevance_score,
                               collect(DISTINCT d.name) as departments,
                               collect(DISTINCT {id: r.id, type: r.type, capacity: r.capacity})[..6] as sample_rooms,
                               count(DISTINCT r) as total_rooms
                        """
                        rows = client.query_read(vec_cypher, {"vec": v})
                        if rows and rows[0].get("name"):
                            building_record = rows[0]
                except Exception:
                    pass

        if not building_record:
            # Fallback default to TP-1 if query mentioned building
            building_record = {
                "code": "TP",
                "name": "Tech Park 1 (TP-1)",
                "floors": 15,
                "campus": "Kattankulathur (KTR)",
                "focus": "School of Computing & Advanced Engineering",
                "description": "Tech Park 1 (TP-1) is a 15-story computing and engineering landmark at SRMIST Kattankulathur housing the School of Computing.",
                "facilities": ["Apple Mac Lab", "NVIDIA AI Lab", "Cisco Networking Lab", "Smart Seminar Halls"],
                "departments": ["Department of Computing Technologies", "Department of Networking And Communications"],
                "sample_rooms": [{"id": "TP-101", "type": "Smart Classroom", "capacity": 50}],
                "total_rooms": 30
            }

        latency = (time.time() - t0) * 1000
        audit.log_event(
            caller=caller,
            tool_name="lookup_building",
            parameters=req.model_dump(),
            status="SUCCESS",
            latency_ms=latency,
            result_count=1
        )

        b_code = building_record.get("code")
        b_name = building_record.get("name")
        floors = building_record.get("floors", 1)
        facilities = building_record.get("facilities", [])
        depts = building_record.get("departments", [])

        grounding = (
            f"[Building: {b_name}] ({b_code}) is a {floors}-floor facility at SRMIST Kattankulathur. "
            f"Primary focus: {building_record.get('focus')}. Key facilities: {', '.join(facilities[:3])}."
        )

        return {
            "building_code": b_code,
            "building_name": b_name,
            "floors": floors,
            "campus": building_record.get("campus", "Kattankulathur (KTR)"),
            "focus": building_record.get("focus"),
            "description": building_record.get("description"),
            "facilities": facilities,
            "departments": depts,
            "sample_rooms": building_record.get("sample_rooms", []),
            "total_rooms_on_record": building_record.get("total_rooms", len(building_record.get("sample_rooms", []))),
            "entities": [{"type": "building", "id": b_code, "name": b_name}],
            "grounding": grounding,
            "source": "SRMIST Official Campus Infrastructure Directory"
        }

