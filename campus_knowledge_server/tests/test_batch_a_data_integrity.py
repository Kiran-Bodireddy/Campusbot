"""
Generic, live-graph-driven tests for Batch A data & graph integrity fixes:
  - BEL building name & alias mapping (no 'bio' -> BEL)
  - Normalized department follow-up narrowing (two spellings -> exact same set)
  - find_faculty_for_course returns id, department, cabin
  - Official directory phone & code-generated phone_note (unique / shared / empty)
  - Junk prerequisite CSE201 -> CSE101 removed
  - Shared course title name lookup returns all matching courses
  - Timetable integer slots 1-7 match real slots; slot 8 rejected
"""
import pytest
from pydantic import ValidationError

from campus_knowledge_server.database.neo4j_client import get_graph_client
from campus_knowledge_server.config.matching_config import load_matching_config, get_slot_number_map
from campus_knowledge_server.tools.campus_tools import (
    CampusKnowledgeTools,
    CourseLookupRequest,
    FacultyCourseRequest,
    FacultyProfileRequest,
    AvailableRoomsRequest,
)
from campus_knowledge_server.agent.normalizer import normalize_user_query
from campus_knowledge_server.agent.qwen_agent import ConversationMemory, GovernedCampusAgent


def test_bel_building_name_and_router_aliases():
    client = get_graph_client()
    bmap = client.get_building_code_map()
    assert bmap.get("BEL") == "Basic Engineering Lab"
    aliases = client.get_building_alias_map()
    assert aliases.get("bel") == "BEL"
    assert aliases.get("basic engineering lab") == "BEL"
    # 'bio' must NOT map to BEL
    assert aliases.get("bio") != "BEL"
    _, meta_bel = normalize_user_query("Find available rooms in Basic Engineering Lab")
    assert meta_bel["detected_building"] == "BEL"
    _, meta_bio = normalize_user_query("Find available rooms in bio block")
    assert meta_bio["detected_building"] != "BEL"


def test_two_department_spellings_return_same_followup_set():
    client = get_graph_client()
    assert client.is_connected and client.driver
    # Pick a canonical normalized_department that has >= 2 distinct aliases in config
    aliases = load_matching_config()["department_normalization"]["aliases"]
    by_canon = {}
    for al, canon in aliases.items():
        by_canon.setdefault(canon, []).append(al)
    # Find a department with >= 2 faculty in live Neo4j and >= 2 configured spellings
    chosen_canon, sp1, sp2 = None, None, None
    for canon, al_list in by_canon.items():
        if len(al_list) < 2:
            continue
        rows = client.query_read(
            "MATCH (f:FacultyMember) WHERE f.normalized_department = $d "
            "RETURN f.id AS id, f.name AS name, f.department AS department, "
            "f.normalized_department AS normalized_department, f.college AS college LIMIT 20",
            {"d": canon},
        )
        if len(rows) >= 2:
            chosen_canon = canon
            sp1, sp2 = sorted(al_list, key=len)[0], sorted(al_list, key=len)[-1]
            candidates = rows
            break
    assert chosen_canon is not None, "Need a department with >=2 aliases and >=2 faculty in live graph"

    # Add distractor faculty from a different normalized_department
    others = client.query_read(
        "MATCH (f:FacultyMember) WHERE f.normalized_department <> $d "
        "RETURN f.id AS id, f.name AS name, f.department AS department, "
        "f.normalized_department AS normalized_department, f.college AS college LIMIT 10",
        {"d": chosen_canon},
    )
    pool = candidates + others
    sid = "test_dept_norm_parity"
    ConversationMemory.clear_session(sid)
    ConversationMemory.set_pending_faculty(sid, pool, "test", len(pool))
    r1 = ConversationMemory.filter_pending_faculty(sid, sp1)
    r2 = ConversationMemory.filter_pending_faculty(sid, sp2)
    ConversationMemory.clear_session(sid)

    ids1 = {x["id"] for x in r1["matched"]}
    ids2 = {x["id"] for x in r2["matched"]}
    assert ids1 == ids2
    assert ids1 == {x["id"] for x in candidates}


def test_find_faculty_for_course_returns_id_department_cabin():
    client = get_graph_client()
    assert client.is_connected and client.driver
    rows = client.query_read(
        "MATCH (f:FacultyMember)-[:TEACHES]->(c:Course) RETURN c.code AS code LIMIT 1"
    )
    assert rows
    code = rows[0]["code"]
    res = CampusKnowledgeTools.find_faculty_for_course(FacultyCourseRequest(course_code=code), caller="test")
    assert res["instructor_count"] >= 1
    for inst in res["instructors"]:
        assert inst.get("id")
        assert inst.get("department")
        assert "cabin" in inst

    agent = GovernedCampusAgent()
    answer = agent._synthesize_grounded_answer(f"who teaches {code}", "find_faculty_for_course", res)
    assert res["instructors"][0]["id"] in answer


def test_faculty_phone_and_phone_note_all_three_cases():
    client = get_graph_client()
    assert client.is_connected and client.driver

    unique_row = client.query_read(
        "MATCH (f:FacultyMember) WHERE f.phone_shared_count = 1 AND f.phone <> '' "
        "RETURN f.name AS name, f.id AS id, f.phone AS phone LIMIT 1"
    )
    shared_row = client.query_read(
        "MATCH (f:FacultyMember) WHERE f.phone_shared_count > 1 AND f.phone <> '' "
        "RETURN f.name AS name, f.id AS id, f.phone AS phone, f.phone_shared_count AS n LIMIT 1"
    )
    empty_row = client.query_read(
        "MATCH (f:FacultyMember) WHERE coalesce(f.phone, '') = '' "
        "RETURN f.name AS name, f.id AS id LIMIT 1"
    )
    assert unique_row and shared_row and empty_row

    res_u = CampusKnowledgeTools.lookup_faculty_profile(FacultyProfileRequest(faculty_name=unique_row[0]["name"]), caller="test")
    match_u = next(f for f in res_u["faculty"] if f["id"] == unique_row[0]["id"])
    assert match_u["phone"] == unique_row[0]["phone"]
    assert match_u["phone_note"] is None

    res_s = CampusKnowledgeTools.lookup_faculty_profile(FacultyProfileRequest(faculty_name=shared_row[0]["name"]), caller="test")
    match_s = next(f for f in res_s["faculty"] if f["id"] == shared_row[0]["id"])
    assert match_s["phone"] == shared_row[0]["phone"]
    assert match_s["phone_note"] == f"shared by {shared_row[0]['n']} faculty (department/office line)"

    res_e = CampusKnowledgeTools.lookup_faculty_profile(FacultyProfileRequest(faculty_name=empty_row[0]["name"]), caller="test")
    match_e = next(f for f in res_e["faculty"] if f["id"] == empty_row[0]["id"])
    assert match_e["phone"] == ""
    assert match_e["phone_note"] == "not listed in the directory"


def test_junk_prerequisite_removed():
    client = get_graph_client()
    assert client.is_connected and client.driver
    junk = client.query_read(
        "MATCH (a:Course {code: 'CSE201'})-[r:REQUIRES_PREREQUISITE]->(b:Course {code: 'CSE101'}) RETURN count(r) AS n"
    )
    assert junk[0]["n"] == 0
    total = client.query_read("MATCH ()-[r:REQUIRES_PREREQUISITE]->() RETURN count(r) AS n")
    assert total[0]["n"] == 30


def test_shared_course_title_returns_all_matching_courses():
    client = get_graph_client()
    assert client.is_connected and client.driver
    dup = client.query_read(
        "MATCH (c:Course) WITH toLower(trim(c.name)) AS t, collect(c.code) AS codes, head(collect(c.name)) AS sample_name "
        "WHERE size(codes) >= 2 RETURN sample_name AS name, codes ORDER BY size(codes) DESC LIMIT 1"
    )
    assert dup
    title = dup[0]["name"]
    expected_codes = set(dup[0]["codes"])
    res = CampusKnowledgeTools.lookup_course(CourseLookupRequest(query=title), caller="test")
    returned_codes = {c["code"] for c in res["courses"]}
    assert expected_codes.issubset(returned_codes)


def test_integer_slot_mapping_matches_seven_real_slots():
    client = get_graph_client()
    assert client.is_connected and client.driver
    real_slots = [
        r["slot"]
        for r in client.query_read("MATCH ()-[r:OCCUPIES]->() RETURN DISTINCT r.slot AS slot ORDER BY slot")
    ]
    slot_map = get_slot_number_map()
    assert len(slot_map) == 7
    assert [slot_map[i] for i in range(1, 8)] == real_slots
    assert all("16:30" not in s for s in slot_map.values())
    with pytest.raises(ValidationError):
        AvailableRoomsRequest(building_code="TP", slot=8)
