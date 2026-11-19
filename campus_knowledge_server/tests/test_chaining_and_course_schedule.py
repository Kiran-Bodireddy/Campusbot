"""
Automated Generic Tests for Governed Tool Chaining (Option A) and find_course_schedule.
All entities chosen from the graph at runtime (zero hardcoded names or IDs).
Tests independent multi-part, dependent chains, role cutoff, limits enforcement,
and clean stoppage on empty first hop.
"""

import pytest
from pydantic import ValidationError

from campus_knowledge_server.security.auth import Principal
from campus_knowledge_server.security.ast_validator import SecurityViolationError
from campus_knowledge_server.tools.governed_executor import execute_tool, TOOL_ENTITY_REGISTRY
from campus_knowledge_server.agent.chain_executor import (
    GovernedChainExecutor,
    validate_structured_entity
)
from campus_knowledge_server.database.neo4j_client import get_graph_client


@pytest.fixture(scope="module")
def graph_client():
    client = get_graph_client()
    return client


@pytest.fixture(scope="module")
def student_principal():
    return Principal(user_id="test_student", role="student", caller_type="test")


@pytest.fixture(scope="module")
def admin_principal():
    return Principal(user_id="test_admin", role="admin", caller_type="test")


def test_tool_entity_registry_declarations():
    """Verifies that all governed tools declare accepted and returned entity types in the registry."""
    assert "lookup_course" in TOOL_ENTITY_REGISTRY
    assert "find_course_schedule" in TOOL_ENTITY_REGISTRY
    assert "get_prerequisite_tree" in TOOL_ENTITY_REGISTRY
    assert "find_faculty_for_course" in TOOL_ENTITY_REGISTRY

    schedule_decl = TOOL_ENTITY_REGISTRY["find_course_schedule"]
    assert "course_code" in schedule_decl["accepts"]
    assert "schedules" in schedule_decl["returns"]


def test_find_course_schedule_tool(graph_client, student_principal):
    """Verifies find_course_schedule returns classroom allocations for a dynamic graph course."""
    # Find a course from the live graph that has scheduled slots
    target_code = None
    if graph_client._schedules_by_course:
        target_code = next(iter(graph_client._schedules_by_course.keys()))
    if not target_code and graph_client._course_by_code:
        target_code = next(iter(graph_client._course_by_code.keys()))

    assert target_code is not None, "At least one course must exist in graph cache"

    res = execute_tool("find_course_schedule", {"course_code": target_code}, principal=student_principal)
    assert "course_code" in res
    assert res["course_code"] == target_code
    assert "schedules" in res
    assert "scheduled_slots_count" in res
    assert res["scheduled_slots_count"] == len(res["schedules"])


def test_find_course_schedule_validation(student_principal):
    """Verifies Pydantic validation rejects blank or whitespace course codes."""
    with pytest.raises(ValidationError):
        execute_tool("find_course_schedule", {"course_code": "   "}, principal=student_principal)


def test_structured_entity_validation(graph_client):
    """Verifies that only structured codes matching strict formats and graph existence pass validation."""
    if graph_client._course_by_code:
        c_code = next(iter(graph_client._course_by_code.keys()))
        is_valid, clean = validate_structured_entity("COURSE_CODE", c_code, graph_client)
        assert is_valid is True
        assert clean == c_code

    # Malicious free text must be rejected
    is_valid, _ = validate_structured_entity("COURSE_CODE", "SELECT * FROM courses; DROP TABLE", graph_client)
    assert is_valid is False

    is_valid, _ = validate_structured_entity("COURSE_CODE", "tell me about operating systems", graph_client)
    assert is_valid is False


def test_independent_multipart_chain(graph_client, student_principal):
    """Verifies independent multi-part chain execution (same entity, multiple tools)."""
    # Pick a course from the graph
    c_code = None
    if graph_client._prereqs_by_target:
        c_code = next(iter(graph_client._prereqs_by_target.keys()))
    if not c_code and graph_client._course_by_code:
        c_code = next(iter(graph_client._course_by_code.keys()))

    executor = GovernedChainExecutor()
    res = executor.execute_independent_chain(
        template_id="course_prereqs_and_faculty",
        entity_id=c_code,
        principal=student_principal
    )

    assert res["status"] in ("SUCCESS", "PARTIAL_SUCCESS")
    assert res["chain_type"] == "independent"
    assert "chain_id" in res
    assert res["chain_id"].startswith("chn-")
    assert "answer" in res
    assert len(res["answer"]) > 10

    # Evidence drawer verification
    evidence = res["evidence"]
    assert evidence["chain_id"] == res["chain_id"]
    assert len(evidence["hops"]) >= 2
    for hop in evidence["hops"]:
        assert "tool" in hop
        assert "parameters" in hop
        assert "status" in hop
        assert "latency_ms" in hop


def test_dependent_chain(graph_client, student_principal):
    """Verifies dependent chain: Hop 2 consumes structured codes produced by Hop 1."""
    # Find a course that has official prerequisites in graph
    target_code = None
    if graph_client._prereqs_by_target:
        for code, prereqs in graph_client._prereqs_by_target.items():
            if len(prereqs) >= 1:
                target_code = code
                break

    if not target_code:
        pytest.skip("No prerequisite relationships found in test environment graph")

    executor = GovernedChainExecutor()
    res = executor.execute_dependent_chain(
        template_id="prerequisite_instructors",
        entity_id=target_code,
        principal=student_principal
    )

    assert res["status"] == "SUCCESS"
    assert res["chain_type"] == "dependent"
    assert "chain_id" in res
    assert len(res["evidence"]["hops"]) >= 2
    assert "Instructors" in res["answer"] or "Prerequisites" in res["answer"]


def test_chain_empty_first_hop_stops(student_principal):
    """Verifies that if Hop 1 returns 0 records, the chain halts cleanly and does not call Hop 2 with empty values."""
    executor = GovernedChainExecutor()
    res = executor.execute_dependent_chain(
        template_id="prerequisite_instructors",
        entity_id="21NONEXIST999",
        principal=student_principal
    )

    assert res["status"] == "FIRST_HOP_NO_RESULTS"
    # Hop 2 must never have been called
    assert res["evidence"]["total_tool_calls"] == 1
    assert len(res["evidence"]["hops"]) == 1
    assert "No prerequisites records found" in res["answer"] or "further dependent inquiries" in res["answer"].lower()


def test_chain_hop_cutoff_by_role(graph_client, student_principal):
    """Verifies that if a hop requires a tool forbidden to the role, the chain stops safely and returns prior hop results."""
    executor = GovernedChainExecutor()

    # Temporarily insert an independent template with a forbidden tool for students (run_governed_query)
    c_code = next(iter(graph_client._course_by_code.keys())) if graph_client._course_by_code else "21CSC206T"
    test_template_id = "_test_cutoff_template"
    executor.config["independent_templates"].append({
        "id": test_template_id,
        "entity_type": "COURSE_CODE",
        "tools": [
            {"tool_name": "lookup_course", "param_key": "query", "section_title": "Allowed Course Information"},
            {"tool_name": "run_governed_query", "param_key": "template_id", "section_title": "Admin Restricted Section"}
        ]
    })

    try:
        res = executor.execute_independent_chain(
            template_id=test_template_id,
            entity_id=c_code,
            principal=student_principal
        )

        assert res["status"] == "PARTIAL_SUCCESS"
        # Hop 1 succeeded
        assert len(res["hop_results"]) == 1
        assert res["hop_results"][0]["courses"][0]["code"] == c_code
        # Hop 2 was intercepted and recorded as policy violation
        hops = res["evidence"]["hops"]
        assert len(hops) == 2
        assert hops[0]["status"] == "SUCCESS"
        assert hops[1]["status"] == "POLICY_VIOLATION"
        assert "forbidden for role 'student'" in res["answer"]
    finally:
        executor.config["independent_templates"] = [
            t for t in executor.config["independent_templates"] if t["id"] != test_template_id
        ]


def test_chain_limits_enforced(graph_client, student_principal):
    """Verifies that max_rows_passed_forward truncates intermediate lists and appends truncation notice."""
    # Dynamically find a course with >= 2 total prerequisites across graph depths
    target_code = None
    if graph_client.is_connected and graph_client.driver:
        try:
            rows = graph_client.query_read(
                "MATCH (c:Course)-[:REQUIRES_PREREQUISITE*1..4]->(p:Course) "
                "WITH c.code as code, count(distinct p) as cnt WHERE cnt >= 2 RETURN code LIMIT 1"
            )
            if rows:
                target_code = rows[0]["code"]
        except Exception:
            pass

    if not target_code and graph_client._prereqs_by_target:
        # Fallback recursive search over in-memory graph
        for code in graph_client._prereqs_by_target.keys():
            visited = set()
            def count_prereqs(c):
                cnt = 0
                for p in graph_client._prereqs_by_target.get(c, []):
                    req_c = p["prerequisite_course_code"].upper()
                    if req_c not in visited:
                        visited.add(req_c)
                        cnt += 1 + count_prereqs(req_c)
                return cnt
            if count_prereqs(code) >= 2:
                target_code = code
                break

    if not target_code:
        pytest.skip("No course with >= 2 prerequisites available in graph for limit test")

    executor = GovernedChainExecutor()
    # Force max_rows_forward to 1
    executor.max_rows_forward = 1

    res = executor.execute_dependent_chain(
        template_id="prerequisite_instructors",
        entity_id=target_code,
        principal=student_principal
    )

    assert res["status"] == "SUCCESS"
    assert "truncated" in res["answer"].lower()
