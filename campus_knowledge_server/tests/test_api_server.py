"""
FastAPI Server Test Suite
Verifies endpoints /health, /tools/*, /audit/logs, and HTTP 403 safety responses.
"""

import pytest
from fastapi.testclient import TestClient

from campus_knowledge_server.server.main import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "indexed_courses" in data
    assert "indexed_faculty" in data

def test_api_lookup_course():
    payload = {"query": "CSE201"}
    response = client.post("/tools/lookup_course", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["match_count"] >= 1
    assert any(c["code"] == "CSE201" for c in data["courses"])

def test_api_verify_prerequisites():
    from campus_knowledge_server.database.neo4j_client import get_graph_client
    gclient = get_graph_client()
    rows = gclient.query_read(
        "MATCH (t:Course)-[:REQUIRES_PREREQUISITE]->(p:Course) RETURN t.code AS target, p.code AS prereq LIMIT 1"
    ) if (gclient.is_connected and gclient.driver) else []
    assert rows, "Expected at least one prerequisite edge in Neo4j"
    payload = {"completed_courses": [rows[0]["prereq"]], "target_course": rows[0]["target"]}
    response = client.post("/tools/verify_prerequisites", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["eligible"] is True

def test_api_find_room_schedule():
    payload = {"room_id": "TP-101"}
    response = client.post("/tools/find_room_schedule", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["room_id"] == "TP-101"

def test_api_audit_logs():
    response = client.get("/audit/logs?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "events" in data
    assert len(data["events"]) >= 1

def test_api_adversarial_template_blocked():
    payload = {"template_id": "malicious_unapproved_template", "parameters": {}}
    response = client.post("/tools/run_governed_query", json=payload)
    assert response.status_code == 403
    data = response.json()
    assert data["status"] == "BLOCKED"

def test_api_check_admission_eligibility():
    payload = {"program_query": "B.Tech Computer Science", "candidate_percentage": 70.0}
    response = client.post("/tools/check_admission_eligibility", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["match_count"] >= 1
    prog = data["programs"][0]
    assert "Computer Science" in prog["program_name"]
    assert prog["eligibility_verdict"] == "ACADEMICALLY_ELIGIBLE_ENTRANCE_REQUIRED"

if __name__ == "__main__":
    pytest.main(["-v", __file__])
