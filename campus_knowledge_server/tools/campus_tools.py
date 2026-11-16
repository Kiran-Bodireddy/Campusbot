"""
Governed Campus Knowledge Toolset
Implements least-privilege, parameterized query execution for courses,
prerequisites, faculty, rooms, and schedules with schema validation and audit logging.
"""

import time
import math
import re
import difflib
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field, field_validator

from campus_knowledge_server.database.neo4j_client import get_graph_client
from campus_knowledge_server.security.ast_validator import ASTSecurityValidator, SecurityViolationError
from campus_knowledge_server.security.audit import get_audit_logger

# ----------------- Pydantic v2 Request Schemas -----------------

class CourseLookupRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=100, description="Course code (e.g., '21CSC206T') or course title.")

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

class RoomScheduleRequest(BaseModel):
    room_id: str = Field(..., min_length=2, max_length=20, description="Room ID (e.g., 'TP-101', 'UB-203').")
    day_of_week: Optional[str] = Field(default=None, description="Optional filter by day (e.g., 'Monday').")

class AvailableRoomsRequest(BaseModel):
    building_code: str = Field(..., min_length=2, max_length=10, description="Building code (e.g. 'TP', 'UB', 'BEL').")
    min_capacity: int = Field(default=30, ge=10, le=500, description="Minimum room seating capacity.")
    day: str = Field(default="Monday", description="Day of week (Monday-Friday).")
    slot: str = Field(default="08:45-09:35", description="Timeslot string.")

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
    category: str = Field(default="all", description="Category for statistics: 'all', 'courses', 'programs', 'faculty', 'rooms'.")

# ----------------- Pre-Approved Cypher Templates -----------------

WHITELISTED_TEMPLATES = {
    "courses_by_department": "MATCH (c:Course) WHERE toLower(c.department) CONTAINS toLower($department) RETURN c.code AS code, c.name AS name, c.credits AS credits, c.level AS level",
    "faculty_by_department": "MATCH (f:FacultyMember) WHERE toLower(f.department) CONTAINS toLower($department) RETURN f.id AS id, f.name AS name, f.designation AS designation, f.specialization AS specialization",
    "building_rooms_summary": "MATCH (r:Room)-[:LOCATED_IN]->(b:Building {code: $building_code}) RETURN r.id AS room_id, r.type AS type, r.capacity AS capacity",
    "course_prerequisite_chain": "MATCH (target:Course {code: $course_code})-[:REQUIRES_PREREQUISITE*1..3]->(prereq:Course) RETURN DISTINCT prereq.code AS prereq_code, prereq.name AS prereq_name"
}

# ----------------- Governed Tool Implementations -----------------

class CampusKnowledgeTools:

    @staticmethod
    def lookup_course(req: CourseLookupRequest, caller: str = "agent") -> Dict[str, Any]:
        """Looks up course details by course code or partial course name."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()
        q_norm = req.query.strip().upper()

        results = []
        # 1. Check exact code match in-memory index
        if q_norm in client._course_by_code:
            results.append(client._course_by_code[q_norm])
        else:
            # 2. Substring / partial search
            q_lower = req.query.strip().lower()
            for c in client.in_memory_data.get("courses", []):
                if q_lower in c["name"].lower() or q_lower in c["code"].lower():
                    results.append(c)
                if len(results) >= 10:
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
            "source": "SRMIST Property Graph",
            "grounding": f"Found {len(results)} courses matching '{req.query}'."
        }

    @staticmethod
    def get_prerequisite_tree(req: PrerequisiteTreeRequest, caller: str = "agent") -> Dict[str, Any]:
        """Recursively traverses prerequisite relationships up to max_depth."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()
        target = req.course_code.strip().upper()

        tree = []
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
            "source": "SRMIST Prerequisite DAG",
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

        # Retrieve direct prerequisites
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
            "source": "SRMIST Prerequisite DAG"
        }

    @staticmethod
    def find_faculty_for_course(req: FacultyCourseRequest, caller: str = "agent") -> Dict[str, Any]:
        """Retrieves verified faculty instructors teaching a specified course."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()
        c_code = req.course_code.strip().upper()

        teaching = client._teaching_by_course.get(c_code, [])
        instructors = []
        for t in teaching:
            fac = client._faculty_by_id.get(t["faculty_id"])
            if fac:
                instructors.append({
                    "id": fac["id"],
                    "name": fac["name"],
                    "designation": fac["designation"],
                    "department": fac["department"],
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
            "source": "SRMIST Faculty Directory (Kattankulathur Campus)",
            "grounding": f"Found {len(instructors)} instructors assigned to {c_code}."
        }

    @staticmethod
    def lookup_faculty_profile(req: FacultyProfileRequest, caller: str = "agent") -> Dict[str, Any]:
        """Searches faculty profiles by name and returns qualifications, experience, and research."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()
        name_clean = re.sub(r"[^\w\s]", " ", req.faculty_name.lower())
        req_terms = [t for t in name_clean.split() if t not in ["dr", "prof", "professor", "mr", "mrs", "ms"]]

        scored_matches = []
        q_phrase = " ".join(req_terms)
        meaningful_terms = [t for t in req_terms if len(t) > 1]

        for fac in client.in_memory_data.get("faculty", []):
            fac_clean = re.sub(r"[^\w\s]", " ", fac["name"].lower())
            f_words = [w for w in fac_clean.split() if w not in ["dr", "prof", "professor", "mr", "mrs", "ms"]]
            f_phrase = " ".join(f_words)

            score = 0.0
            # 1. Exact canonical name match (ignoring titles): score 100
            if q_phrase and q_phrase == f_phrase:
                score = 100.0
            # 2. Exact word-boundary phrase match: score 90
            elif q_phrase and re.search(r"\b" + re.escape(q_phrase) + r"\b", f_phrase):
                score = 90.0
            # 3. All query words present as exact distinct words: score 85
            elif req_terms and all(t in f_words for t in req_terms):
                score = 85.0
            # 4. Meaningful words match: score 70-75
            elif meaningful_terms:
                matched_count = sum(1 for t in meaningful_terms if t in f_words)
                if matched_count == len(meaningful_terms):
                    score = 75.0
                elif matched_count > 0 and len(meaningful_terms) > 1:
                    score = 50.0 + (matched_count / len(meaningful_terms)) * 15.0

            # 5. Fuzzy typo match for faculty names via sequence similarity
            if score == 0.0 and meaningful_terms:
                max_sim = 0.0
                for t in meaningful_terms:
                    sim = max((difflib.SequenceMatcher(None, t, w).ratio() for w in f_words if len(w) > 2), default=0.0)
                    if sim > max_sim:
                        max_sim = sim
                if max_sim >= 0.78:
                    score = 40.0 + max_sim * 20.0

            if score > 0.0:
                scored_matches.append((
                    score,
                    {
                        "id": fac["id"],
                        "name": fac["name"],
                        "designation": fac["designation"],
                        "department": fac["department"],
                        "cabin": fac.get("cabin", "Staff Room (TBA)"),
                        "college": fac["college"],
                        "specialization": fac["specialization"],
                        "email": fac["email"],
                        "experience": fac["experience"],
                        "qualifications": fac["qualifications"],
                        "relevance_score": round(score, 1)
                    }
                ))

        # Sort descending by relevance score, then shorter name length
        scored_matches.sort(key=lambda x: (-x[0], len(x[1]["name"])))
        matches = [m[1] for m in scored_matches[:10]]

        latency = (time.time() - t0) * 1000
        audit.log_event(
            caller=caller,
            tool_name="lookup_faculty_profile",
            parameters=req.model_dump(),
            status="SUCCESS",
            latency_ms=latency,
            result_count=len(matches)
        )

        return {
            "query": req.faculty_name,
            "match_count": len(matches),
            "faculty": matches,
            "source": "SRMIST Faculty Master Directory"
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
    def find_available_rooms(req: AvailableRoomsRequest, caller: str = "agent") -> Dict[str, Any]:
        """Finds unoccupied classrooms in a building during a specified day and slot."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()
        b_code = req.building_code.strip().upper()
        target_day = req.day.strip().capitalize()
        target_slot = req.slot.strip()

        # Find all rooms in building meeting capacity
        candidate_rooms = [
            r for r in client.in_memory_data.get("rooms", [])
            if r["building_code"] == b_code and r["capacity"] >= req.min_capacity
        ]

        # Find occupied rooms at this day and slot
        occupied_room_ids = {
            s["room_id"] for s in client.in_memory_data.get("schedules", [])
            if s.get("day") == target_day and s.get("slot") == target_slot
        }

        available = [r for r in candidate_rooms if r["id"] not in occupied_room_ids]

        latency = (time.time() - t0) * 1000
        audit.log_event(caller=caller, tool_name="find_available_rooms", parameters=req.model_dump(), status="SUCCESS", latency_ms=latency, result_count=len(available))

        return {
            "building_code": b_code,
            "day": target_day,
            "slot": target_slot,
            "min_capacity": req.min_capacity,
            "available_count": len(available),
            "available_rooms": available[:20],
            "source": "SRMIST Space Allocation Matrix"
        }

    @staticmethod
    def search_courses_semantic(req: SemanticSearchRequest, caller: str = "agent") -> Dict[str, Any]:
        """Performs lexical and semantic hybrid discovery over course descriptions and syllabi."""
        t0 = time.time()
        client = get_graph_client()
        audit = get_audit_logger()
        STOP_WORDS = {"for", "and", "the", "with", "from", "about", "what", "where", "how", "who", "which", "are", "is", "can", "take", "course", "courses", "study", "want", "related", "to", "in", "on", "at", "by", "all", "of", "a", "an", "i"}
        raw_tokens = re.findall(r"\w+", req.query.lower())
        query_terms = [t for t in raw_tokens if (len(t) > 2 or t in ("ai", "ml", "ds", "it", "cs", "ui")) and t not in STOP_WORDS]
        # Expand common computer science abbreviations
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
                # Score threshold guardrail: must score at least 2 to be relevant
                if score >= 2:
                    scored_courses.append((score, c))

            # Also search official degree programs
            for p in getattr(client, "admission_eligibility", []):
                p_content = f"{p['program_name']} {p['department']} {p['faculty']} {p.get('mandatory_subjects', '')}".lower()
                score = 0
                for term in search_terms:
                    if term in p_content:
                        score += 4
                    if term in p["program_name"].lower():
                        score += 6
                if score >= 3:
                    scored_courses.append((score, {
                        "code": f"PROG-{p['program_id']}",
                        "name": p["program_name"],
                        "department": p["department"],
                        "faculty": p["faculty"],
                        "level": p["degree_level"],
                        "description": f"Degree Program under {p['faculty']}. Min Education: {p['min_education']}. Cutoff: {p['min_percentage_general']}%.",
                        "credits": "Full Degree"
                    }))

        scored_courses.sort(key=lambda x: x[0], reverse=True)
        top_results = [item[1] for item in scored_courses[:req.top_k]]

        latency = (time.time() - t0) * 1000
        audit.log_event(caller=caller, tool_name="search_courses_semantic", parameters=req.model_dump(), status="SUCCESS", latency_ms=latency, result_count=len(top_results))

        return {
            "query": req.query,
            "top_k": req.top_k,
            "results_found": len(top_results),
            "courses": top_results,
            "source": "SRMIST Semantic Course Catalog"
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
        programs = client.in_memory_data.get("programs", []) or client.in_memory_data.get("admission_rules", [])
        faculty = client.in_memory_data.get("faculty", [])
        rooms = client.in_memory_data.get("rooms", [])
        schedules = client.in_memory_data.get("schedules", [])
        courses = client.in_memory_data.get("courses", [])

        level_counts = {}
        faculty_groups = {}
        for p in programs:
            lvl = p.get("degree_level", "UG")
            level_counts[lvl] = level_counts.get(lvl, 0) + 1
            f_group = p.get("faculty", "General")
            faculty_groups[f_group] = faculty_groups.get(f_group, 0) + 1

        stats = {
            "category": cat,
            "total_programs": len(programs),
            "total_courses_indexed": len(courses),
            "total_faculty": len(faculty),
            "total_classrooms": len(rooms),
            "total_scheduled_sessions": len(schedules),
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
            status="SUCCESS",
            latency_ms=latency,
            result_count=len(programs)
        )

        return {
            "category": cat,
            "statistics": stats,
            "source": "SRMIST Official Academic Registry & Campus Graph"
        }

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
