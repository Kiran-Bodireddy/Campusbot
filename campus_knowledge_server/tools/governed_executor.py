"""
Centralized Governed Tool Executor for SRMIST Campus Knowledge Server
Enforces least-privilege RBAC, schema validation, AST safety, field masking,
result caps, standardized entity emission, and SHA-256 hash-chained auditing
across all execution paths (Agent, REST, MCP, and tests).
"""

import os
import sys
import time
import logging
from typing import Dict, Any, Optional, List
from pydantic import ValidationError

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from campus_knowledge_server.security.auth import Principal
from campus_knowledge_server.security.ast_validator import ASTSecurityValidator, SecurityViolationError
from campus_knowledge_server.security.audit import get_audit_logger
from campus_knowledge_server.tools.campus_tools import (
    CampusKnowledgeTools,
    CourseLookupRequest,
    CourseScheduleRequest,
    PrerequisiteTreeRequest,
    PrerequisiteVerifyRequest,
    FacultyCourseRequest,
    FacultyProfileRequest,
    RoomScheduleRequest,
    AvailableRoomsRequest,
    SemanticSearchRequest,
    AdmissionEligibilityRequest,
    CampusStatisticsRequest,
    SemesterCurriculumRequest,
    GovernedQueryTemplateRequest,
    BuildingLookupRequest,
    DependentCoursesRequest,
    FacultySearchRequest,
    FacultyCoursesRequest,
    CourseListRequest,
    ProgramSearchRequest,
    ProgramsForCourseRequest,
    CompareProgramsRequest,
    DepartmentOverviewRequest
)

logger = logging.getLogger("governed_executor")

# Tool entity type declarations (declaring accepted parameters and returned structured entity types)
TOOL_ENTITY_REGISTRY: Dict[str, Dict[str, Dict[str, str]]] = {
    "lookup_course": {
        "accepts": {"query": "COURSE_CODE_OR_TITLE"},
        "returns": {"code": "COURSE_CODE", "name": "COURSE_TITLE", "prerequisites": "COURSE_CODE_LIST"}
    },
    "find_course_schedule": {
        "accepts": {"course_code": "COURSE_CODE", "day_of_week": "DAY_NAME"},
        "returns": {"course_code": "COURSE_CODE", "room_id": "ROOM_ID", "schedules": "SCHEDULE_LIST"}
    },
    "get_prerequisite_tree": {
        "accepts": {"course_code": "COURSE_CODE"},
        "returns": {"code": "COURSE_CODE", "prerequisites": "COURSE_CODE_LIST"}
    },
    "verify_prerequisites": {
        "accepts": {"target_course": "COURSE_CODE", "completed_courses": "COURSE_CODE_LIST"},
        "returns": {"target_course": "COURSE_CODE", "missing_prerequisites": "COURSE_CODE_LIST"}
    },
    "find_faculty_for_course": {
        "accepts": {"course_code": "COURSE_CODE"},
        "returns": {"faculty_id": "FACULTY_ID", "faculty_name": "FACULTY_NAME", "instructors": "FACULTY_LIST"}
    },
    "lookup_faculty_profile": {
        "accepts": {"faculty_name": "FACULTY_NAME"},
        "returns": {"faculty_id": "FACULTY_ID", "cabin": "CABIN_LOCATION", "department": "DEPARTMENT_NAME"}
    },
    "find_room_schedule": {
        "accepts": {"room_id": "ROOM_ID", "day_of_week": "DAY_NAME"},
        "returns": {"room_id": "ROOM_ID", "schedules": "SCHEDULE_LIST", "course_code": "COURSE_CODE"}
    },
    "find_available_rooms": {
        "accepts": {"building_code": "BUILDING_CODE"},
        "returns": {"room_id": "ROOM_ID", "available_rooms": "ROOM_LIST"}
    },
    "search_courses_semantic": {
        "accepts": {"query": "TOPIC_STRING"},
        "returns": {"code": "COURSE_CODE", "courses": "COURSE_LIST"}
    },
    "check_admission_eligibility": {
        "accepts": {"program_query": "PROGRAM_NAME"},
        "returns": {"program_id": "PROGRAM_ID"}
    },
    "get_campus_statistics": {
        "accepts": {"category": "STATISTICS_CATEGORY"},
        "returns": {"statistics": "STATISTICS_OBJECT"}
    },
    "get_semester_curriculum": {
        "accepts": {"program_query": "PROGRAM_NAME", "semester": "SEMESTER_INT"},
        "returns": {"code": "COURSE_CODE", "courses": "COURSE_LIST"}
    },
    "lookup_building": {
        "accepts": {"query": "BUILDING_CODE_OR_NAME"},
        "returns": {"building_code": "BUILDING_CODE", "rooms": "ROOM_ID_LIST"}
    },
    "run_governed_query": {
        "accepts": {"template_id": "TEMPLATE_ID", "parameters": "OBJECT"},
        "returns": {"records": "RECORD_LIST"}
    },
    "find_dependent_courses": {
        "accepts": {"course_code": "COURSE_CODE"},
        "returns": {"code": "COURSE_CODE", "unlocks": "COURSE_CODE_LIST"}
    },
    "search_faculty": {
        "accepts": {"specialization": "TOPIC_STRING", "department": "DEPARTMENT_NAME"},
        "returns": {"faculty": "FACULTY_LIST"}
    },
    "get_faculty_courses": {
        "accepts": {"faculty_name": "FACULTY_NAME"},
        "returns": {"courses": "COURSE_CODE_LIST", "slots": "SLOT_MAP"}
    },
    "list_courses": {
        "accepts": {"department": "DEPARTMENT_NAME", "category": "CATEGORY_STRING", "credits": "CREDIT_INT"},
        "returns": {"courses": "COURSE_LIST", "codes": "COURSE_CODE_LIST"}
    },
    "search_programs": {
        "accepts": {"degree_level": "DEGREE_LEVEL_STRING", "sort": "SORT_STRING"},
        "returns": {"programs": "PROGRAM_LIST"}
    },
    "find_programs_for_course": {
        "accepts": {"course_code": "COURSE_CODE"},
        "returns": {"programs": "PROGRAM_LIST"}
    },
    "compare_programs": {
        "accepts": {"program_a": "PROGRAM_NAME", "program_b": "PROGRAM_NAME"},
        "returns": {"comparison": "COMPARISON_OBJECT"}
    },
    "get_department_overview": {
        "accepts": {"department": "DEPARTMENT_NAME"},
        "returns": {"department": "DEPARTMENT_NAME", "faculty_count": "COUNT_INT", "heads": "HEAD_LIST"}
    }
}

# Tool parameter model mapping for zero-trust schema validation
TOOL_SCHEMA_MAP = {
    "lookup_course": CourseLookupRequest,
    "find_course_schedule": CourseScheduleRequest,
    "get_prerequisite_tree": PrerequisiteTreeRequest,
    "verify_prerequisites": PrerequisiteVerifyRequest,
    "find_faculty_for_course": FacultyCourseRequest,
    "lookup_faculty_profile": FacultyProfileRequest,
    "find_room_schedule": RoomScheduleRequest,
    "find_available_rooms": AvailableRoomsRequest,
    "search_courses_semantic": SemanticSearchRequest,
    "check_admission_eligibility": AdmissionEligibilityRequest,
    "get_campus_statistics": CampusStatisticsRequest,
    "get_semester_curriculum": SemesterCurriculumRequest,
    "lookup_building": BuildingLookupRequest,
    "run_governed_query": GovernedQueryTemplateRequest,
    "find_dependent_courses": DependentCoursesRequest,
    "search_faculty": FacultySearchRequest,
    "get_faculty_courses": FacultyCoursesRequest,
    "list_courses": CourseListRequest,
    "search_programs": ProgramSearchRequest,
    "find_programs_for_course": ProgramsForCourseRequest,
    "compare_programs": CompareProgramsRequest,
    "get_department_overview": DepartmentOverviewRequest
}

# Tool implementation dispatch table
TOOL_FUNC_MAP = {
    "lookup_course": CampusKnowledgeTools.lookup_course,
    "find_course_schedule": CampusKnowledgeTools.find_course_schedule,
    "get_prerequisite_tree": CampusKnowledgeTools.get_prerequisite_tree,
    "verify_prerequisites": CampusKnowledgeTools.verify_prerequisites,
    "find_faculty_for_course": CampusKnowledgeTools.find_faculty_for_course,
    "lookup_faculty_profile": CampusKnowledgeTools.lookup_faculty_profile,
    "find_room_schedule": CampusKnowledgeTools.find_room_schedule,
    "find_available_rooms": CampusKnowledgeTools.find_available_rooms,
    "search_courses_semantic": CampusKnowledgeTools.search_courses_semantic,
    "check_admission_eligibility": CampusKnowledgeTools.check_admission_eligibility,
    "get_campus_statistics": CampusKnowledgeTools.get_campus_statistics,
    "get_semester_curriculum": CampusKnowledgeTools.get_semester_curriculum,
    "lookup_building": CampusKnowledgeTools.lookup_building,
    "run_governed_query": CampusKnowledgeTools.run_governed_query,
    "find_dependent_courses": CampusKnowledgeTools.find_dependent_courses,
    "search_faculty": CampusKnowledgeTools.search_faculty,
    "get_faculty_courses": CampusKnowledgeTools.get_faculty_courses,
    "list_courses": CampusKnowledgeTools.list_courses,
    "search_programs": CampusKnowledgeTools.search_programs,
    "find_programs_for_course": CampusKnowledgeTools.find_programs_for_course,
    "compare_programs": CampusKnowledgeTools.compare_programs,
    "get_department_overview": CampusKnowledgeTools.get_department_overview
}

def sanitize_tool_arguments(tool_name: str, args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Sanitizes, coerces, and cleans tool arguments before schema validation:
    - Drops None values.
    - Coerces semester strings like 'Sem 3' or 'semester 4' -> integer 3 or 4.
    - Coerces slot strings like 'Slot 1' -> integer 1.
    - Coerces string numbers for min_capacity, max_depth, top_k, candidate_percentage.
    - Splits string lists like '21CSC101T, 21CSC102T' into list of strings for completed_courses.
    - Strips leading/trailing whitespace from string parameters.
    """
    import re as _re
    sanitized: Dict[str, Any] = {}
    for k, v in (args or {}).items():
        if v is None:
            continue
        if isinstance(v, str):
            v_stripped = v.strip()
            if k == "semester":
                m_sem = _re.search(r"(\d+)", v_stripped)
                if m_sem:
                    sanitized[k] = int(m_sem.group(1))
                    continue
            elif k == "slot":
                m_slot = _re.match(r"^\s*slot\s*(\d+)\s*$", v_stripped, _re.IGNORECASE)
                if m_slot:
                    sanitized[k] = int(m_slot.group(1))
                    continue
                elif v_stripped.isdigit():
                    sanitized[k] = int(v_stripped)
                    continue
            elif k in ("min_capacity", "max_depth", "top_k"):
                m_int = _re.search(r"(\d+)", v_stripped)
                if m_int:
                    sanitized[k] = int(m_int.group(1))
                    continue
            elif k in ("candidate_percentage", "cutoff_score"):
                try:
                    sanitized[k] = float(v_stripped)
                    continue
                except ValueError:
                    pass
            elif k == "completed_courses":
                sanitized[k] = [c.strip() for c in v_stripped.split(",") if c.strip()]
                continue
            sanitized[k] = v_stripped
            continue

        if k == "completed_courses" and isinstance(v, list):
            sanitized[k] = [str(item).strip() for item in v if item is not None and str(item).strip()]
            continue

        sanitized[k] = v
    return sanitized


def mask_fields_recursive(obj: Any, hidden_fields: set) -> Any:
    """Recursively masks sensitive fields across nested dictionaries and lists."""
    if not hidden_fields:
        return obj
    if isinstance(obj, dict):
        masked: Dict[str, Any] = {}
        for k, v in obj.items():
            if k in hidden_fields:
                masked[k] = "[Hidden by Policy]"
            else:
                masked[k] = mask_fields_recursive(v, hidden_fields)
        return masked
    elif isinstance(obj, list):
        return [mask_fields_recursive(item, hidden_fields) for item in obj]
    return obj


_cached_governance_policy: Optional[Dict[str, Any]] = None

def get_governance_policy() -> Dict[str, Any]:
    """Loads and caches governance policy once at startup with strict fail-closed validation."""
    global _cached_governance_policy
    if _cached_governance_policy is None:
        import yaml
        policy_path = os.path.join(BASE_DIR, "campus_knowledge_server", "config", "policy.yaml")
        if not os.path.exists(policy_path):
            raise SecurityViolationError("CRITICAL: Governance policy file 'policy.yaml' is missing. Failing closed.")
        try:
            with open(policy_path, "r", encoding="utf-8") as pf:
                _cached_governance_policy = yaml.safe_load(pf) or {}
        except Exception as e:
            raise SecurityViolationError(f"CRITICAL: Governance policy file corrupted: {e}. Failing closed.")
    return _cached_governance_policy


def execute_tool(tool_name: str, args: Dict[str, Any], principal: Optional[Principal] = None, chain_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Unified, single governed executor for all campus tools.
    1. Schema Validation (Pydantic models)
    2. RBAC Policy Enforcement (least privilege via policy.yaml)
    3. AST Security Check (read-only verification)
    4. Execution (Parameterized Cypher on Neo4j Community)
    5. Field Masking & Row Caps
    6. SHA-256 Hash-Chained Audit Logging
    """
    t0 = time.time()
    audit = get_audit_logger()
    if principal is None:
        principal = Principal(user_id="default_guest", role="student", caller_type="internal")

    caller_id = f"{principal.user_id}@{principal.caller_type}"

    # 1. Tool Existence Check
    if tool_name not in TOOL_FUNC_MAP:
        err = f"Unknown or unregistered tool: '{tool_name}'."
        audit.log_event(
            caller=caller_id,
            tool_name=tool_name,
            parameters=args,
            status="POLICY_VIOLATION",
            latency_ms=(time.time() - t0) * 1000,
            violation_reason=err,
            role=principal.role,
            chain_id=chain_id
        )
        raise SecurityViolationError(err)

    # 2. RBAC Policy Enforcement (Strict Fail-Closed)
    policy_cfg = get_governance_policy()
    roles_cfg = policy_cfg.get("roles", {})
    if principal.role not in roles_cfg:
        err = f"Access Policy Violation: Role '{principal.role}' is not declared in governance policy (Fail-Closed)."
        audit.log_event(caller=caller_id, tool_name=tool_name, parameters=args, status="POLICY_VIOLATION", latency_ms=(time.time() - t0) * 1000, violation_reason=err, role=principal.role, chain_id=chain_id)
        raise SecurityViolationError(err)

    role_rules = roles_cfg[principal.role]
    allowed_tools = role_rules.get("allowed_tools", [])
    forbidden_tools = role_rules.get("forbidden_tools", [])

    if not allowed_tools or tool_name in forbidden_tools or tool_name not in allowed_tools:
        err = f"Access Policy Violation: Role '{principal.role}' is forbidden from executing tool '{tool_name}'."
        audit.log_event(
            caller=caller_id,
            tool_name=tool_name,
            parameters=args,
            status="POLICY_VIOLATION",
            latency_ms=(time.time() - t0) * 1000,
            violation_reason=err,
            role=principal.role,
            chain_id=chain_id
        )
        raise SecurityViolationError(err)

    # 3. Pre-Validation Argument Sanitization
    sanitized_args = sanitize_tool_arguments(tool_name, args)

    schema_cls = TOOL_SCHEMA_MAP[tool_name]
    try:
        req_obj = schema_cls(**sanitized_args)
    except ValidationError as ve:
        err = f"Schema validation error on tool '{tool_name}': {ve}"
        audit.log_event(
            caller=caller_id,
            tool_name=tool_name,
            parameters=sanitized_args,
            status="VALIDATION_ERROR",
            latency_ms=(time.time() - t0) * 1000,
            violation_reason=err,
            role=principal.role,
            chain_id=chain_id
        )
        raise ve

    # 4. AST Security Validation for Direct Cypher Templates
    if tool_name == "run_governed_query":
        raw_cypher = args.get("template_id", "")
        # Verified inside run_governed_query via ASTSecurityValidator

    # 5. Tool Execution
    try:
        raw_result = TOOL_FUNC_MAP[tool_name](req_obj, caller=caller_id)
    except Exception as e:
        audit.log_event(
            caller=caller_id,
            tool_name=tool_name,
            parameters=args,
            status="EXECUTION_ERROR",
            latency_ms=(time.time() - t0) * 1000,
            violation_reason=str(e),
            role=principal.role,
            chain_id=chain_id
        )
        raise e

    # 6. Recursive Field-Level Masking & Row Caps
    hidden_fields = set(role_rules.get("hidden_fields", []))
    row_limit = role_rules.get("row_limit", 50)

    if hidden_fields and isinstance(raw_result, dict):
        raw_result = mask_fields_recursive(raw_result, hidden_fields)

    for list_key in ["courses", "faculty", "instructors", "rooms", "available_rooms", "schedules", "programs", "prerequisites", "classes", "allocations", "departments", "records"]:
        if list_key in raw_result and isinstance(raw_result[list_key], list):
            orig_len = len(raw_result[list_key])
            if orig_len > row_limit:
                raw_result[list_key] = raw_result[list_key][:row_limit]
                raw_result["row_cap_applied"] = row_limit
                raw_result["total_before_cap"] = orig_len

    # 7. Standardized Entity Extraction for Grounding Verification (S1)
    entities = extract_standardized_entities(tool_name, raw_result)
    raw_result["entities"] = entities

    # 8. Audit Logging
    latency = (time.time() - t0) * 1000
    res_count = len(entities)
    audit.log_event(
        caller=caller_id,
        tool_name=tool_name,
        parameters=args,
        status="SUCCESS",
        latency_ms=latency,
        result_count=res_count,
        role=principal.role,
        chain_id=chain_id
    )

    return raw_result


def extract_standardized_entities(tool_name: str, result: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extracts standardized entity descriptors (code, ID, room) for post-generation grounding check."""
    entities: List[Dict[str, str]] = []

    if tool_name in ("lookup_course", "search_courses_semantic"):
        for c in result.get("courses", []):
            if isinstance(c, dict) and "code" in c:
                entities.append({"type": "course", "id": c["code"], "name": c.get("name", "")})

    elif tool_name == "find_course_schedule":
        if "course_code" in result:
            entities.append({"type": "course", "id": result["course_code"]})
        for s in result.get("schedules", []):
            if isinstance(s, dict) and "room_id" in s:
                entities.append({"type": "room", "id": s["room_id"], "day": s.get("day", ""), "slot": s.get("slot", "")})

    elif tool_name == "get_prerequisite_tree":
        for p in result.get("prerequisites", []):
            if isinstance(p, dict) and "prerequisite_code" in p:
                entities.append({"type": "course", "id": p["prerequisite_code"], "name": p.get("prerequisite_name", "")})

    elif tool_name == "verify_prerequisites":
        if "target_course" in result:
            entities.append({"type": "course", "id": result["target_course"]})
        for c in result.get("required_prerequisites", []):
            entities.append({"type": "course", "id": c})

    elif tool_name == "find_faculty_for_course":
        if "course_code" in result:
            entities.append({"type": "course", "id": result["course_code"]})
        for f in result.get("instructors", []):
            if isinstance(f, dict):
                entities.append({"type": "faculty", "id": f.get("id", ""), "name": f.get("name", ""), "cabin": f.get("cabin", "")})

    elif tool_name == "lookup_faculty_profile":
        for f in result.get("faculty", []):
            if isinstance(f, dict):
                entities.append({"type": "faculty", "id": f.get("id", ""), "name": f.get("name", ""), "cabin": f.get("cabin", "")})

    elif tool_name == "find_room_schedule":
        if "room_id" in result:
            entities.append({"type": "room", "id": result["room_id"]})
        for s in (result.get("schedules") or result.get("schedule") or []):
            if isinstance(s, dict) and "course_code" in s:
                entities.append({"type": "course", "id": s["course_code"]})

    elif tool_name == "find_available_rooms":
        for r in result.get("available_rooms", []):
            if isinstance(r, dict) and "room_id" in r:
                entities.append({"type": "room", "id": r["room_id"]})

    elif tool_name == "check_admission_eligibility":
        for p in result.get("programs", []):
            if isinstance(p, dict):
                entities.append({"type": "program", "id": p.get("program_id", ""), "name": p.get("program_name", "")})

    elif tool_name == "get_semester_curriculum":
        for a in result.get("allocations", []):
            if isinstance(a, dict) and "course_code" in a:
                entities.append({"type": "course", "id": a["course_code"], "name": a.get("course_name", "")})

    return entities
