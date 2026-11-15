"""
Tests for Query Normalization, Typo Tolerance, and Heuristic Routing Resilience.
"""

import pytest
from campus_knowledge_server.agent.normalizer import (
    normalize_user_query,
    correct_intent_tokens,
    expand_acronyms
)
from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent
from campus_knowledge_server.tools.campus_tools import (
    CampusKnowledgeTools,
    FacultyProfileRequest,
    AdmissionEligibilityRequest,
    SemanticSearchRequest
)

@pytest.fixture(scope="module")
def agent():
    return GovernedCampusAgent()

# -------------------------------------------------------------
# 1. Normalizer Unit Tests
# -------------------------------------------------------------
def test_normalizer_typo_correction():
    corrected = correct_intent_tokens("eligibity for btech")
    assert "eligibility" in corrected

    corrected_cutoff = correct_intent_tokens("cuttoff for cse")
    assert "cutoff" in corrected_cutoff

    corrected_prof = correct_intent_tokens("who is prof godfry")
    # 'prof' maps to 'faculty' in INTENT_VOCABULARY
    assert "faculty" in corrected_prof

def test_normalizer_acronym_expansion():
    expanded, meta = expand_acronyms("eligibility for btech")
    assert "B.Tech" in expanded
    assert meta["detected_degree"] == "B.Tech"

    expanded_mtech, meta_m = expand_acronyms("fees for mtech")
    assert "M.Tech" in expanded_mtech
    assert meta_m["detected_degree"] == "M.Tech"

def test_full_query_normalization():
    norm1, meta1 = normalize_user_query("eligibity for btech")
    assert "eligibility" in norm1.lower()
    assert "b.tech" in norm1.lower()

    norm2, meta2 = normalize_user_query("who is prof godfry")
    assert "godfry" in norm2.lower()
    assert "faculty" in norm2.lower()

# -------------------------------------------------------------
# 2. Heuristic Routing Precision Tests
# -------------------------------------------------------------
def test_admission_routing_with_typo(agent):
    tool_name, args = agent._select_tool_heuristically("eligibity for btech")
    assert tool_name == "check_admission_eligibility"
    assert "B.Tech" in args.get("program_query", "")

def test_admission_routing_with_cutoff_typo(agent):
    tool_name, args = agent._select_tool_heuristically("cuttoff for cse")
    assert tool_name == "check_admission_eligibility"

def test_faculty_routing_with_typo(agent):
    tool_name, args = agent._select_tool_heuristically("who is prof godfry")
    assert tool_name == "lookup_faculty_profile"
    assert "godfry" in args.get("faculty_name", "").lower()

def test_available_room_routing(agent):
    tool_name, args = agent._select_tool_heuristically("vacant room in tech park")
    assert tool_name == "find_available_rooms"
    assert args.get("building_code") == "TP"

# -------------------------------------------------------------
# 3. Tool Execution & Data Completeness Tests
# -------------------------------------------------------------
def test_faculty_lookup_fuzzy_matching():
    # Fuzzy match 'godfry' should resolve to 'Dr. Godfrey Winster S'
    req = FacultyProfileRequest(faculty_name="godfry")
    result = CampusKnowledgeTools.lookup_faculty_profile(req, caller="test_runner")
    assert len(result.get("faculty", [])) > 0
    fac = result["faculty"][0]
    assert "Godfrey" in fac["name"]
    assert fac["cabin"] == "TP2-FR-1001"
    assert "Computing Technologies" in fac["department"]

def test_admission_eligibility_enrichment():
    req = AdmissionEligibilityRequest(program_query="B.Tech")
    result = CampusKnowledgeTools.check_admission_eligibility(req, caller="test_runner")
    progs = result.get("programs", [])
    assert len(progs) > 0
    first = progs[0]
    assert "min_percentage_general" in first
    assert "min_percentage_reserved" in first
    assert "required_entrance_exam" in first
    # Enriched fields
    assert "annual_fee_inr" in first
    assert "duration" in first
    assert "campuses" in first

def test_semantic_search_stop_word_guardrail():
    # Query with solely stop words should return empty, not all courses
    req = SemanticSearchRequest(query="for", limit=5)
    result = CampusKnowledgeTools.search_courses_semantic(req, caller="test_runner")
    assert len(result.get("courses", [])) == 0
