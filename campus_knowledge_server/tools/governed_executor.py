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
    BuildingLookupRequest
)

logger = logging.getLogger("governed_executor")

# Tool parameter model mapping for zero-trust schema validation
TOOL_SCHEMA_MAP = {
    "lookup_course": CourseLookupRequest,
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
    "run_governed_query": GovernedQueryTemplateRequest
}

# Tool implementation dispatch table
TOOL_FUNC_MAP = {
    "lookup_course": CampusKnowledgeTools.lookup_course,
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
    "run_governed_query": CampusKnowledgeTools.run_governed_query
}

def execute_tool(tool_name: str, args: Dict[str, Any], principal: Optional[Principal] = None) -> Dict[str, Any]:
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
            role=principal.role
        )
        raise SecurityViolationError(err)

    # 2. RBAC Policy Enforcement
    from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent
    # Read policy rules
    import yaml
    policy_path = os.path.join(BASE_DIR, "campus_knowledge_server", "config", "policy.yaml")
    policy_cfg = {}
    if os.path.exists(policy_path):
        try:
            with open(policy_path, "r", encoding="utf-8") as pf:
                policy_cfg = yaml.safe_load(pf) or {}
        except Exception as e:
            logger.warning(f"Could not load policy.yaml: {e}")

    role_rules = policy_cfg.get("roles", {}).get(principal.role, {})
    allowed_tools = role_rules.get("allowed_tools", [])
    forbidden_tools = role_rules.get("forbidden_tools", [])

    if tool_name in forbidden_tools or (allowed_tools and tool_name not in allowed_tools):
        err = f"Access Policy Violation: Role '{principal.role}' is forbidden from executing tool '{tool_name}'."
        audit.log_event(
            caller=caller_id,
            tool_name=tool_name,
            parameters=args,
            status="POLICY_VIOLATION",
            latency_ms=(time.time() - t0) * 1000,
            violation_reason=err,
            role=principal.role
        )
        raise SecurityViolationError(err)

    # 3. Pre-Validation Argument Sanitization (drop nulls, coerce semester strings like 'Sem 3' -> 3)
    import re as _re
    sanitized_args: Dict[str, Any] = {}
    for k, v in (args or {}).items():
        if v is None:
            continue
        if k == "semester" and isinstance(v, str):
            m_sem = _re.search(r"(\d+)", v)
            if m_sem:
                sanitized_args[k] = int(m_sem.group(1))
                continue
        if k == "slot" and isinstance(v, str):
            m_slot = _re.match(r"^\s*slot\s+(\d+)\s*$", v, _re.IGNORECASE)
            if m_slot:
                sanitized_args[k] = int(m_slot.group(1))
                continue
        if k in ("min_capacity", "max_depth", "top_k") and isinstance(v, str):
            m_int = _re.search(r"(\d+)", v)
            if m_int:
                sanitized_args[k] = int(m_int.group(1))
                continue
        sanitized_args[k] = v

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
            role=principal.role
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
            role=principal.role
        )
        raise e

    # 6. Field-Level Masking & Row Caps
    hidden_fields = set(role_rules.get("hidden_fields", []))
    row_limit = role_rules.get("row_limit", 50)

    if hidden_fields:
        for k, v in raw_result.items():
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

    for list_key in ["courses", "faculty", "instructors", "rooms", "available_rooms", "schedules", "programs", "prerequisites", "classes", "allocations", "departments"]:
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
        role=principal.role
    )

    return raw_result


def extract_standardized_entities(tool_name: str, result: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extracts standardized entity descriptors (code, ID, room) for post-generation grounding check."""
    entities: List[Dict[str, str]] = []

    if tool_name in ("lookup_course", "search_courses_semantic"):
        for c in result.get("courses", []):
            if isinstance(c, dict) and "code" in c:
                entities.append({"type": "course", "id": c["code"], "name": c.get("name", "")})

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
        for s in result.get("schedule", []):
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
