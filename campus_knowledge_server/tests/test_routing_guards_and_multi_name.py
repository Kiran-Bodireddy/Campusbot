"""
Generic tests for Items 2–6 (zero hardcoding — entities fetched dynamically from live Neo4j at runtime):
  - Item 2: Strict small talk (config templates, zero Qwen calls, falls through when extra content exists)
  - Item 3: Write-request guard (config verbs, WRITE_REQUEST_REFUSED, never a greeting, both routing modes)
  - Item 4: Semantic search min_similarity_score threshold, relevance_score in metadata, no-match wording
  - Item 5: Multi-name faculty splitting on 'and', '&', ',', execute_tool per name, max_names cap & disambiguation
  - Item 6: Per-stage timings (routing_ms, tool_ms, generation_ms) and zero LLM calls on small talk
"""

import json
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from campus_knowledge_server.server.main import app
from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent, ConversationMemory
from campus_knowledge_server.config.matching_config import load_matching_config
from campus_knowledge_server.database.neo4j_client import get_graph_client
from campus_knowledge_server.security.rate_limit import get_rate_limiter
from campus_knowledge_server.tools.campus_tools import CampusKnowledgeTools, SemanticSearchRequest

client = TestClient(app)


def _pick_live_faculty_names():
    """Fetches two distinct single-match names and one ambiguous surname dynamically from live Neo4j."""
    gc = get_graph_client()
    fac_idx = gc.get_graph_faculty_index() if (gc.is_connected and gc.driver) else gc.in_memory_data.get("faculty", [])

    from collections import Counter
    name_counts = Counter((f.get("name") or "").strip().lower() for f in fac_idx if f.get("name"))
    unique_names = []
    for f in fac_idx:
        nm = (f.get("name") or "").strip()
        if nm and name_counts[nm.lower()] == 1 and len(nm.split()) >= 2:
            unique_names.append(nm)
        if len(unique_names) >= 13:
            break

    ambig_tok = next(
        (tok for tok, fl in gc._faculty_by_token.items() if len(tok) >= 4 and len(fl) >= 3),
        None,
    )
    assert len(unique_names) >= 12, "Expected at least 12 unique faculty names in live graph"
    assert ambig_tok is not None, "Expected at least one ambiguous surname in live graph"
    return unique_names, ambig_tok


def _pick_live_course():
    gc = get_graph_client()
    if gc.is_connected and gc.driver:
        rows = gc.query_read("MATCH (c:Course) WHERE c.code IS NOT NULL AND c.name IS NOT NULL RETURN c.code AS code, c.name AS name LIMIT 1", timeout=10.0)
        if rows:
            return rows[0]["code"], rows[0]["name"]
    c0 = next(iter(gc._course_by_code.values()))
    return c0["code"], c0["name"]


def test_item2_strict_small_talk_zero_qwen_calls_and_fallthrough():
    get_rate_limiter().reset()
    cfg = load_matching_config()["small_talk"]
    templates = cfg["templates"]
    agent = GovernedCampusAgent()

    # Pure greetings, thanks, and how-are-you must use config templates and NEVER call Ollama
    with patch("campus_knowledge_server.agent.qwen_agent.requests.post") as mock_post:
        for mode in ("hybrid", "llm_intent"):
            for query, expected_tmpl in [
                ("hello", templates["greeting"]),
                ("thank you!", templates["thanks"]),
                ("how are you doing?", templates["how_are_you"]),
            ]:
                res = agent.execute_query(query, use_llm_synthesis=True, routing_mode=mode)
                assert res["status"] == "INTERACTIVE_GREETING"
                assert res["answer"] == expected_tmpl
                assert res["stage_timings_ms"]["generation_ms"] == 0.0
        assert mock_post.call_count == 0, "Small talk must make ZERO Qwen/Ollama HTTP calls"

    # Greeting + extra content words/entity MUST fall through to normal routing (not small talk!)
    code, _ = _pick_live_course()
    res_fall = agent.execute_query(f"hello tell me about {code}", use_llm_synthesis=False)
    assert res_fall["status"] == "SUCCESS"
    assert res_fall["tool"] == "lookup_course"


def test_item3_write_requests_refused_with_distinct_status_never_greeting():
    get_rate_limiter().reset()
    cfg_w = load_matching_config()["write_requests"]
    expected_msg = cfg_w["refusal_message"]
    expected_status = cfg_w["status"]
    unique_names, _ = _pick_live_faculty_names()
    agent = GovernedCampusAgent()

    write_queries = [
        f"delete {unique_names[0]} and replace it with {unique_names[1]}",
        "delete evrything",
        "add a new faculty record",
        f"change {unique_names[0]} email to test@example.com",
    ]
    with patch("campus_knowledge_server.agent.qwen_agent.requests.post") as mock_post:
        for mode in ("hybrid", "llm_intent"):
            for q in write_queries:
                res = agent.execute_query(q, use_llm_synthesis=False, routing_mode=mode)
                assert res["status"] == expected_status, f"Expected {expected_status} on {q!r} ({mode}), got {res['status']}"
                assert res["answer"] == expected_msg
                assert res["status"] != "INTERACTIVE_GREETING"
                assert res["stage_timings_ms"]["generation_ms"] == 0.0
        assert mock_post.call_count == 0, "Write refusal must happen before any Qwen call"


def test_item4_semantic_search_low_relevance_threshold_and_metadata():
    get_rate_limiter().reset()
    sem_cfg = load_matching_config()["semantic_search"]
    min_sim = float(sem_cfg["min_similarity_score"])
    no_match_msg = sem_cfg["no_match_message"]

    # Off-topic query falls below threshold
    weak = CampusKnowledgeTools.search_courses_semantic(
        SemanticSearchRequest(query="best recipe for tomato soup", top_k=5),
        caller="test",
    )
    assert weak["below_threshold"] is True
    assert weak["courses"] == []
    assert weak["status"] == "NO_RELEVANT_MATCH"
    assert "top_score" in weak and "min_similarity_score" in weak

    # End-to-end synthesis on weak result uses configured no-match wording and never "official courses covering"
    agent = GovernedCampusAgent()
    synth_weak = agent._synthesize_grounded_answer("best recipe for tomato soup", "search_courses_semantic", weak)
    assert no_match_msg in synth_weak
    assert "official courses covering" not in synth_weak.lower()

    # Genuine course topic from live graph passes above threshold and exposes relevance_score
    _, course_name = _pick_live_course()
    strong = agent.execute_query(f"courses about {course_name}", use_llm_synthesis=False)
    assert strong["tool"] == "search_courses_semantic"
    assert "relevance_score" in strong
    assert strong["relevance_score"]["min_similarity_score"] == min_sim
    assert strong["relevance_score"]["top_score"] >= min_sim
    assert "official courses covering" not in strong["answer"].lower()


def test_item5_multiple_names_in_one_question_via_execute_tool():
    get_rate_limiter().reset()
    max_names = int(load_matching_config()["faculty_matching"]["max_names_per_query"])
    unique_names, ambig_tok = _pick_live_faculty_names()
    agent = GovernedCampusAgent()

    # 1. Leading greeting + two unique names separated by 'and' -> strips greeting, calls execute_tool per name
    q_and = f"hey can u find {unique_names[0]} and {unique_names[1]}"
    res_and = agent.execute_query(q_and, use_llm_synthesis=False)
    assert res_and["status"] == "SUCCESS"
    assert res_and["tool"] == "lookup_faculty_profile"
    assert len(res_and["tool_result"]["per_name_results"]) == 2
    assert unique_names[0].split()[-1].lower() in res_and["answer"].lower()
    assert unique_names[1].split()[-1].lower() in res_and["answer"].lower()

    # 2. 6+ names in one query (supported up to config max_names_per_query=10)
    six_names = ", ".join(unique_names[:6])
    res_six = agent.execute_query(f"details about {six_names}", use_llm_synthesis=False)
    assert res_six["status"] == "SUCCESS"
    assert len(res_six["tool_result"]["per_name_results"]) == 6

    # 3. Mixed unique + ambiguous surname separated by ',' and '&' -> answers each and emits disambiguation options
    q_mix = f"profiles for {unique_names[0]}, {unique_names[1]} & Dr. {ambig_tok.capitalize()}"
    res_mix = agent.execute_query(q_mix, use_llm_synthesis=False)
    assert res_mix["status"] == "CLARIFICATION_NEEDED"
    assert len(res_mix["tool_result"]["per_name_results"]) == 3
    assert len(res_mix["options"]) >= 2

    # 4. Exceeding max_names_per_query is capped cleanly to config limit
    many = ", ".join(unique_names[: max_names + 2])
    res_cap = agent.execute_query(f"details about {many}", use_llm_synthesis=False)
    assert len(res_cap["tool_result"]["per_name_results"]) == max_names


def test_item6_stage_timings_on_ask_and_stream():
    get_rate_limiter().reset()
    code, _ = _pick_live_course()

    r_ask = client.post("/agent/ask", json={"query": f"Course details for {code}", "use_qwen": False})
    assert r_ask.status_code == 200
    body = r_ask.json()
    st = body.get("stage_timings_ms")
    assert isinstance(st, dict)
    for k in ("routing_ms", "tool_ms", "generation_ms"):
        assert k in st and isinstance(st[k], (int, float)) and st[k] >= 0

    r_stream = client.post("/agent/ask/stream", json={"query": "hello", "use_qwen": False})
    assert r_stream.status_code == 200
    done_ev = None
    for block in r_stream.text.split("\n\n"):
        lines = [l[5:].strip() for l in block.splitlines() if l.startswith("data:")]
        if lines:
            ev = json.loads("\n".join(lines))
            if ev.get("event") == "done":
                done_ev = ev
    assert done_ev is not None
    assert done_ev["stage_timings_ms"]["generation_ms"] == 0.0
