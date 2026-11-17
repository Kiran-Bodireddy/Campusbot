"""
Unit and Integration Tests for Multi-Turn Memory, SSE Streaming,
Multi-Constraint Complex Queries, and Engine Parity.
"""

import pytest
import json
from fastapi.testclient import TestClient
from campus_knowledge_server.server.main import app
from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent, ConversationMemory

client = TestClient(app)

@pytest.fixture
def agent():
    return GovernedCampusAgent()

# -------------------------------------------------------------
# 1. Multi-Turn Conversational Memory & Pronoun Resolution
# -------------------------------------------------------------
def test_faculty_multi_turn_followup(agent):
    sess_id = "test-session-faculty-1"
    
    # Turn 1: Initial query mentioning faculty member
    res1 = agent.execute_query("Where is Dr. Godfrey cabin?", use_llm_synthesis=False, session_id=sess_id)
    assert res1["status"] == "SUCCESS"
    assert res1["tool_selected"] == "lookup_faculty_profile"
    assert "Godfrey" in res1["answer"]

    # Verify memory recorded the entity
    last_ents = ConversationMemory.get_last_entities(sess_id)
    assert "faculty_name" in last_ents
    assert "Godfrey" in last_ents["faculty_name"]

    # Turn 2: Follow-up asking for email with pronoun 'his'
    res2 = agent.execute_query("What is his email?", use_llm_synthesis=False, session_id=sess_id)
    assert res2["status"] == "SUCCESS"
    assert res2["tool_selected"] == "lookup_faculty_profile"
    assert "godfrey" in res2["answer"].lower() or "srmist.edu.in" in res2["answer"].lower()

    # Turn 3: Follow-up asking what he teaches
    res3 = agent.execute_query("what does he teach?", use_llm_synthesis=False, session_id=sess_id)
    assert res3["status"] == "SUCCESS"
    assert "Godfrey" in res3["answer"]

def test_course_multi_turn_followup(agent):
    sess_id = "test-session-course-1"
    
    # Turn 1: Initial course query
    res1 = agent.execute_query("Tell me about 21CSC206T", use_llm_synthesis=False, session_id=sess_id)
    assert res1["status"] == "SUCCESS"
    assert res1["tool_selected"] == "lookup_course"
    assert "21CSC206T" in res1["answer"]

    # Turn 2: Follow-up asking about prerequisites
    res2 = agent.execute_query("What are its prerequisites?", use_llm_synthesis=False, session_id=sess_id)
    assert res2["status"] == "SUCCESS"
    assert res2["tool_selected"] == "get_prerequisite_tree"
    assert "21CSC206T" in res2["answer"]

def test_program_multi_turn_followup(agent):
    sess_id = "test-session-prog-1"

    # Turn 1: Initial program query
    res1 = agent.execute_query("Eligibility for B.Tech in CSE", use_llm_synthesis=False, session_id=sess_id)
    assert res1["status"] == "SUCCESS"
    assert res1["tool_selected"] == "check_admission_eligibility"

    # Turn 2: Follow-up asking about fees
    res2 = agent.execute_query("What is the fee for it?", use_llm_synthesis=False, session_id=sess_id)
    assert res2["status"] == "SUCCESS"
    assert res2["tool_selected"] == "check_admission_eligibility"
    assert "fee" in res2["answer"].lower() or "inr" in res2["answer"].lower()

# -------------------------------------------------------------
# 2. Multi-Constraint Complex Queries
# -------------------------------------------------------------
def test_multi_constraint_room_search_building_day_slot_capacity(agent):
    # Query with building, day, time slot, and capacity constraints
    query = "Find available room in Tech Park on Tuesday 10:35-11:25 with capacity 50"
    tool_name, params = agent._select_tool_heuristically(query)
    
    assert tool_name == "find_available_rooms"
    assert params["building_code"] == "TP"
    assert params["day"] == "Tuesday"
    assert params["slot"] == "10:35-11:25"
    assert params["min_capacity"] == 50

    # Execution verification
    res = agent.execute_query(query, use_llm_synthesis=False)
    assert res["status"] == "SUCCESS"
    assert "TP" in res["answer"]

def test_multi_constraint_curriculum_semester_and_branch(agent):
    # Query with branch + semester
    query = "curriculum for mechanical semester 4"
    tool_name, params = agent._select_tool_heuristically(query)
    
    assert tool_name == "get_semester_curriculum"
    assert "Mechanical" in params["program_query"]
    assert params["semester"] == 4

# -------------------------------------------------------------
# 3. Server-Sent Events (SSE) Streaming Generator
# -------------------------------------------------------------
def test_agent_stream_query_generator(agent):
    events = list(agent.stream_query("hi", use_llm_synthesis=False, session_id="test-sse-1"))
    event_types = [e.get("event") for e in events]
    
    assert "meta" in event_types
    assert "delta" in event_types
    assert "done" in event_types

    # Find the meta event
    meta_event = next(e for e in events if e.get("event") == "meta")
    assert meta_event["tool_selected"] == "interactive_assistant"

    # Find the done event
    done_event = next(e for e in events if e.get("event") == "done")
    assert "SRMIST Campus Knowledge Assistant" in done_event["answer"]

def test_sse_endpoint_fastapi():
    payload = {
        "query": "Where is Dr. Godfrey cabin?",
        "use_qwen": False,
        "role": "student",
        "engine_mode": "neo4j",
        "session_id": "test-sse-endpoint"
    }
    response = client.post("/agent/ask/stream", json=payload)
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")

    # Read SSE events from body
    lines = response.text.split("\n\n")
    events = []
    for block in lines:
        if block.strip():
            for line in block.split("\n"):
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

    meta = next(e for e in events if e.get("event") == "meta")
    assert meta["tool_selected"] == "lookup_faculty_profile"

    done = next(e for e in events if e.get("event") == "done")
    assert done["status"] == "SUCCESS"
    assert "Godfrey" in done["answer"]

# -------------------------------------------------------------
# 4. Engine Parity: Neo4j vs In-Memory Mirror
# -------------------------------------------------------------
def test_engine_mode_parity(agent):
    q = "Where is Dr. Godfrey cabin?"
    
    res_neo4j = agent.execute_query(q, use_llm_synthesis=False, engine_mode="neo4j")
    res_backup = agent.execute_query(q, use_llm_synthesis=False, engine_mode="backup")

    assert res_neo4j["tool_selected"] == res_backup["tool_selected"]
    assert res_neo4j["status"] == res_backup["status"]
    assert "Godfrey" in res_neo4j["answer"]
    assert "Godfrey" in res_backup["answer"]
    assert res_neo4j["parameters"] == res_backup["parameters"]
