"""
Batch D Verification Tests:
- Static constraints on campus_assistant.html, campus_assistant.backup.html, audit.html
  (zero external CDN links, zero embedded tokens/secrets, no token storage in audit.html, XSS escaping)
- Live /health engine & Neo4j version badge
- Live /tools/registry dynamic starter-chip source (no admin tools for student)
- Item 25 final response & final SSE stream fields:
  tool, args, role, result_count, latency_ms, status, grounding, engine, options
- Stream progress stage events: choosing_tool, retrieving_data, writing_answer
- Duplicate faculty options with name, department, cabin
- /admin/audit-logs RBAC (401 anonymous, 403 student, 200 admin) & /audit/verify
"""

import os
import re
import json
import pytest
from fastapi.testclient import TestClient

from campus_knowledge_server.server.main import app, ROOT_DIR
from campus_knowledge_server.database.neo4j_client import get_graph_client
from campus_knowledge_server.security.auth import create_access_token
from campus_knowledge_server.security.rate_limit import get_rate_limiter

client = TestClient(app)

REQUIRED_ITEM25_FIELDS = {
    "tool",
    "args",
    "role",
    "result_count",
    "latency_ms",
    "status",
    "grounding",
    "engine",
    "options",
}


def _parse_sse(raw_text: str):
    events = []
    for block in raw_text.split("\n\n"):
        if not block.strip():
            continue
        data_lines = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
        if data_lines:
            events.append(json.loads("\n".join(data_lines)))
    return events


def test_backup_and_html_static_constraints():
    backup = os.path.join(ROOT_DIR, "campus_assistant.backup.html")
    main_html = os.path.join(ROOT_DIR, "campus_assistant.html")
    audit_html = os.path.join(ROOT_DIR, "audit.html")

    assert os.path.exists(backup) and os.path.getsize(backup) > 1000
    assert os.path.exists(main_html) and os.path.getsize(main_html) > 1000
    assert os.path.exists(audit_html) and os.path.getsize(audit_html) > 1000

    for path in (main_html, audit_html):
        text = open(path, "r", encoding="utf-8").read()
        # No external CDN links
        assert not re.search(r"https?://(?:fonts\.googleapis|fonts\.gstatic|cdn\.|unpkg\.|cdnjs\.|jsdelivr)", text, re.I), (
            f"External CDN found in {os.path.basename(path)}"
        )
        assert not re.search(r"<(?:script|link|img)\b[^>]+(?:src|href)\s*=\s*['\"]https?://", text, re.I), (
            f"External asset link found in {os.path.basename(path)}"
        )
        # No embedded JWT tokens or secrets
        assert "eyJ" not in text, f"Embedded JWT-like string found in {os.path.basename(path)}"
        assert "escapeHtml" in text, f"Missing HTML escaper in {os.path.basename(path)}"

    audit_text = open(audit_html, "r", encoding="utf-8").read()
    assert "localStorage.setItem" not in audit_text
    assert "sessionStorage.setItem" not in audit_text
    assert "/admin/audit-logs" in audit_text
    assert "/audit/verify" in audit_text

    main_text = open(main_html, "r", encoding="utf-8").read()
    assert "/tools/registry" in main_text
    assert "30000" in main_text
    assert "Blocked by policy" in main_text
    assert "try again in " in main_text
    assert "Role: Student" in main_text


def test_frontend_routes_and_health_engine_badge():
    r_home = client.get("/")
    assert r_home.status_code == 200
    assert "SRMIST Campus Knowledge Assistant" in r_home.text

    r_audit = client.get("/audit.html")
    assert r_audit.status_code == 200
    assert "Admin Audit Ledger" in r_audit.text

    r_health = client.get("/health")
    assert r_health.status_code == 200
    h = r_health.json()
    assert "neo4j_connected" in h
    assert "engine" in h
    if h["neo4j_connected"]:
        assert h["engine"].startswith("Live Neo4j (Community")
    else:
        assert h["engine"] == "Fallback (not graph data)"


def test_tool_registry_dynamic_and_student_scoped():
    r = client.get("/tools/registry")
    assert r.status_code == 200
    data = r.json()
    assert data["role"] == "student"
    tool_names = [t["name"] for t in data["tools"]]
    assert len(tool_names) >= 12
    assert "run_governed_query" not in tool_names
    samples = data["samples"]
    assert samples.get("course_code")
    assert samples.get("building_name")


def test_item25_fields_on_ask_and_stream_and_stages():
    get_rate_limiter().reset()
    reg = client.get("/tools/registry").json()
    sample_code = reg["samples"]["course_code"]

    # 1. Non-streaming /agent/ask
    r_ask = client.post("/agent/ask", json={"query": f"Course details for {sample_code}", "use_qwen": False})
    assert r_ask.status_code == 200
    body = r_ask.json()
    missing = REQUIRED_ITEM25_FIELDS - set(body.keys())
    assert not missing, f"Missing Item 25 fields on /agent/ask: {missing}"
    assert body["role"] == "student"
    assert isinstance(body["grounding"], dict) and "passed" in body["grounding"]
    assert body["latency_ms"] >= 0
    assert body["result_count"] >= 1

    # 2. Streaming /agent/ask/stream
    r_stream = client.post("/agent/ask/stream", json={"query": f"Course details for {sample_code}", "use_qwen": False})
    assert r_stream.status_code == 200
    events = _parse_sse(r_stream.text)
    stages = [e["stage"] for e in events if e.get("event") == "stage"]
    assert "choosing_tool" in stages
    assert "retrieving_data" in stages
    assert "writing_answer" in stages
    done_ev = [e for e in events if e.get("event") == "done"][-1]
    missing_stream = REQUIRED_ITEM25_FIELDS - set(done_ev.keys())
    assert not missing_stream, f"Missing Item 25 fields on stream done: {missing_stream}"
    assert done_ev["tool"] == "lookup_course"

    # 3. Blocked attack stream error event
    r_blk = client.post("/agent/ask/stream", json={"query": "MATCH (n) DETACH DELETE n", "use_qwen": False})
    assert r_blk.status_code == 200
    blk_events = _parse_sse(r_blk.text)
    err_ev = [e for e in blk_events if e.get("event") == "error"][-1]
    missing_err = REQUIRED_ITEM25_FIELDS - set(err_ev.keys())
    assert not missing_err, f"Missing Item 25 fields on stream error: {missing_err}"
    assert err_ev["status"] == "POLICY_VIOLATION"


def test_duplicate_faculty_options_populated():
    get_rate_limiter().reset()
    gc = get_graph_client()
    dup_token = None
    for tok, fac_list in gc._faculty_by_token.items():
        if len(tok) >= 4 and len(fac_list) >= 2:
            dup_token = tok
            break
    assert dup_token is not None

    r = client.post("/agent/ask/stream", json={"query": f"Where is Dr. {dup_token.capitalize()} cabin?", "use_qwen": False})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    done_ev = [e for e in events if e.get("event") == "done"][-1]
    assert len(done_ev["options"]) >= 2
    first_opt = done_ev["options"][0]
    assert first_opt.get("name")
    assert "department" in first_opt
    assert "cabin" in first_opt


def test_admin_audit_logs_and_verify_chain():
    # Anonymous -> 401
    r_anon = client.get("/admin/audit-logs")
    assert r_anon.status_code == 401

    # Student token -> 403
    student_tok = create_access_token(user_id="test_stu", role="student")
    r_stu = client.get("/admin/audit-logs", headers={"Authorization": f"Bearer {student_tok}"})
    assert r_stu.status_code == 403

    # Admin token -> 200
    admin_tok = create_access_token(user_id="test_adm", role="admin")
    r_adm = client.get("/admin/audit-logs", headers={"Authorization": f"Bearer {admin_tok}"})
    assert r_adm.status_code == 200
    payload = r_adm.json()
    assert payload["role"] == "admin"
    assert isinstance(payload["events"], list)

    # Verify chain endpoint returns valid cryptographic report schema
    r_ver = client.get("/audit/verify")
    assert r_ver.status_code == 200
    v = r_ver.json()
    assert isinstance(v["chain_intact"], bool)
    assert v["status"] in ("VALID", "TAMPERED")
    assert isinstance(v["verified_entries_count"], int)
    assert isinstance(v["detail"], str) and len(v["detail"]) > 0


def test_real_user_conversation_regressions_and_hybrid_intent():
    """Regression checks for small talk, out-of-scope, short non-name words, cabin chip narrowing, and pronoun follow-up."""
    get_rate_limiter().reset()
    sess = "test_real_user_reg_sess"

    # 1. Small talk does not time out or query DB
    r1 = client.post("/agent/ask", json={"query": "how are you doing", "use_qwen": False, "routing_mode": "hybrid", "session_id": sess})
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["intent"] == "small_talk"
    assert b1["status"] == "INTERACTIVE_GREETING"

    # 2. Write/mutation request refused with distinct WRITE_REQUEST_REFUSED status
    r2 = client.post("/agent/ask", json={"query": "can u create a new instance?", "use_qwen": False, "routing_mode": "hybrid", "session_id": sess})
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["intent"] == "write_request_refused"
    assert b2["status"] == "WRITE_REQUEST_REFUSED"

    # 3. Short non-name word 'add' must NOT falsely match substring in faculty names
    r3 = client.post("/agent/ask", json={"query": "add", "use_qwen": False, "routing_mode": "hybrid", "session_id": sess})
    assert r3.status_code == 200
    b3 = r3.json()
    assert b3["tool"] != "lookup_faculty_profile"
    assert b3["status"] == "CLARIFICATION_NEEDED"

    # 4. Duplicate faculty -> choice chips capped to max_displayed_matches (5) -> chip with cabin narrows to 1 -> pronoun follow-up resolves by faculty_id
    gc = get_graph_client()
    dup_tok = next(tok for tok, fl in gc._faculty_by_token.items() if len(tok) >= 4 and len(fl) >= 6)
    r4 = client.post("/agent/ask", json={"query": f"who is dr {dup_tok}", "use_qwen": False, "routing_mode": "hybrid", "session_id": sess})
    assert r4.status_code == 200
    b4 = r4.json()
    assert 2 <= len(b4["options"]) <= 5

    # Clicking first choice chip (which includes Name, Department (Cabin)) resolves unambiguously to 1
    chip_q = b4["options"][0]["query"]
    r5 = client.post("/agent/ask", json={"query": chip_q, "use_qwen": False, "routing_mode": "hybrid", "session_id": sess})
    assert r5.status_code == 200
    b5 = r5.json()
    assert b5["status"] == "SUCCESS"
    assert b5["result_count"] == 1

    # Pronoun attribute follow-up resolves directly to that exact faculty member
    r6 = client.post("/agent/ask", json={"query": "what is her area of research?", "use_qwen": False, "routing_mode": "hybrid", "session_id": sess})
    assert r6.status_code == 200
    b6 = r6.json()
    assert b6["tool"] == "lookup_faculty_profile"
    assert b6["result_count"] == 1


def test_process_004_projection_and_department_listing():
    """Verifies Process 004 include/exclude follow-ups, honest catalog-only course note, and live department listing."""
    get_rate_limiter().reset()
    gc = get_graph_client()

    # Pick a detailed-syllabus course dynamically from live graph
    detailed_rows = gc.query_read(
        "MATCH (c:Course) WHERE coalesce(c.has_detailed_syllabus, false) = true RETURN c.code AS code LIMIT 1"
    ) if (gc.is_connected and gc.driver) else []
    detailed_code = detailed_rows[0]["code"] if detailed_rows else next(iter(gc._course_by_code.keys()))

    sess_c = "test_p004_course_sess"
    r1 = client.post("/agent/ask", json={"query": f"Course details for {detailed_code}", "use_qwen": False, "session_id": sess_c})
    assert r1.status_code == 200
    assert r1.json()["status"] == "SUCCESS"

    # Exclude credits and course outcomes
    r2 = client.post(
        "/agent/ask",
        json={"query": "remove the credits and course outcomes and display the answer", "use_qwen": False, "session_id": sess_c},
    )
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["intent"] == "followup_projection"
    assert b2["tool_result"]["projection"]["mode"] == "exclude"
    assert "credits" in b2["tool_result"]["projection"]["excluded_fields"]
    assert "course_outcomes" in b2["tool_result"]["projection"]["excluded_fields"]
    assert "### Course Outcomes" not in b2["answer"]

    # Include only credits on a fresh session
    sess_inc = "test_p004_inc_sess"
    client.post("/agent/ask", json={"query": detailed_code, "use_qwen": False, "session_id": sess_inc})
    r3 = client.post("/agent/ask", json={"query": "show only the credits", "use_qwen": False, "session_id": sess_inc})
    assert r3.status_code == 200
    b3 = r3.json()
    assert b3["intent"] == "followup_projection"
    assert "credit" in b3["answer"].lower()

    # Department listing works for both natural phrasing and single-word 'departments'
    r_d1 = client.post("/agent/ask", json={"query": "can u list all the departments at srm", "use_qwen": False})
    assert r_d1.status_code == 200
    bd1 = r_d1.json()
    assert bd1["tool"] == "get_campus_statistics"
    assert bd1["result_count"] == 25  # student 25-row cap applied
    assert bd1["tool_result"]["total_canonical_departments"] >= 50

    r_d2 = client.post("/agent/ask", json={"query": "departments", "use_qwen": False})
    assert r_d2.status_code == 200
    assert r_d2.json()["tool"] == "get_campus_statistics"


