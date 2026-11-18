"""
Unit & Functional Test Suite for Governed Campus Tools
Tests each tool function across courses, faculty, rooms, prerequisites, and schedules.
"""

import pytest
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
    SemesterCurriculumRequest
)

def test_lookup_course():
    req = CourseLookupRequest(query="CSE201")
    res = CampusKnowledgeTools.lookup_course(req, caller="test_runner")
    assert res["match_count"] >= 1
    assert any(c["code"] == "CSE201" for c in res["courses"])

def _pick_real_prereq_pair():
    from campus_knowledge_server.database.neo4j_client import get_graph_client
    client = get_graph_client()
    if client.is_connected and client.driver:
        rows = client.query_read(
            "MATCH (t:Course)-[:REQUIRES_PREREQUISITE]->(p:Course) "
            "RETURN t.code AS target, p.code AS prereq LIMIT 1"
        )
        if rows:
            return rows[0]["target"], rows[0]["prereq"]
    for tgt, plist in client._prereqs_by_target.items():
        if plist:
            return tgt, plist[0]["prerequisite_course_code"]
    raise AssertionError("No prerequisite edges found in graph")

def test_prerequisite_tree():
    target, prereq = _pick_real_prereq_pair()
    req = PrerequisiteTreeRequest(course_code=target, max_depth=3)
    res = CampusKnowledgeTools.get_prerequisite_tree(req, caller="test_runner")
    assert "prerequisites" in res
    assert res["target_course"] == target
    assert any(p["prerequisite_code"] == prereq for p in res["prerequisites"])

def test_verify_prerequisites_satisfied():
    target, prereq = _pick_real_prereq_pair()
    req = PrerequisiteVerifyRequest(completed_courses=[prereq], target_course=target)
    res = CampusKnowledgeTools.verify_prerequisites(req, caller="test_runner")
    assert res["eligible"] is True
    assert len(res["missing_prerequisites"]) == 0

def test_verify_prerequisites_missing():
    target, prereq = _pick_real_prereq_pair()
    req = PrerequisiteVerifyRequest(completed_courses=[], target_course=target)
    res = CampusKnowledgeTools.verify_prerequisites(req, caller="test_runner")
    assert res["eligible"] is False
    assert prereq in res["missing_prerequisites"]

def test_find_faculty_for_course():
    req = FacultyCourseRequest(course_code="CSE101")
    res = CampusKnowledgeTools.find_faculty_for_course(req, caller="test_runner")
    assert res["instructor_count"] >= 1
    assert "instructors" in res

def test_lookup_faculty_profile():
    req = FacultyProfileRequest(faculty_name="Madhusoodhanan")
    res = CampusKnowledgeTools.lookup_faculty_profile(req, caller="test_runner")
    assert res["match_count"] >= 1
    assert "Madhusoodhanan" in res["faculty"][0]["name"]

def test_find_room_schedule():
    req = RoomScheduleRequest(room_id="TP-101")
    res = CampusKnowledgeTools.find_room_schedule(req, caller="test_runner")
    assert res["room_id"] == "TP-101"
    assert "schedules" in res

def test_find_available_rooms():
    req = AvailableRoomsRequest(building_code="TP", min_capacity=40, day="Monday", slot="08:45-09:35")
    res = CampusKnowledgeTools.find_available_rooms(req, caller="test_runner")
    assert res["building_code"] == "TP"
    assert res["available_count"] >= 1

def test_search_courses_semantic():
    req = SemanticSearchRequest(query="Artificial Intelligence Computing", top_k=5)
    res = CampusKnowledgeTools.search_courses_semantic(req, caller="test_runner")
    assert res["results_found"] >= 1

def test_check_admission_eligibility_criteria_retrieval():
    req = AdmissionEligibilityRequest(program_query="B.Tech Computer Science and Engineering")
    res = CampusKnowledgeTools.check_admission_eligibility(req, caller="test_runner")
    assert res["match_count"] >= 1
    prog = res["programs"][0]
    assert "Computer Science" in prog["program_name"]
    assert prog["min_percentage_general"] == 60.0
    assert "SRMJEEE" in prog["required_entrance_exam"]
    assert "10+2" in prog["min_education"]

def test_check_admission_eligibility_evaluation_eligible():
    req = AdmissionEligibilityRequest(
        program_query="B.Tech Computer Science",
        candidate_percentage=75.0,
        is_reserved_category=False
    )
    res = CampusKnowledgeTools.check_admission_eligibility(req, caller="test_runner")
    assert res["match_count"] >= 1
    eval_res = res["programs"][0]
    assert eval_res["eligibility_verdict"] == "ACADEMICALLY_ELIGIBLE_ENTRANCE_REQUIRED"
    assert "SRMJEEE" in eval_res["verdict_reason"]

def test_check_admission_eligibility_evaluation_ineligible():
    req = AdmissionEligibilityRequest(
        program_query="B.Tech Computer Science",
        candidate_percentage=48.0,
        is_reserved_category=False
    )
    res = CampusKnowledgeTools.check_admission_eligibility(req, caller="test_runner")
    assert res["match_count"] >= 1
    eval_res = res["programs"][0]
    assert eval_res["eligibility_verdict"] == "NOT_ELIGIBLE"
    assert "below the mandatory minimum" in eval_res["verdict_reason"]

def test_check_admission_eligibility_mbbs():
    req = AdmissionEligibilityRequest(program_query="MBBS")
    res = CampusKnowledgeTools.check_admission_eligibility(req, caller="test_runner")
    assert res["match_count"] >= 1
    mbbs = next(p for p in res["programs"] if "MBBS" in p["program_name"])
    assert "NEET" in mbbs["required_entrance_exam"]
    assert mbbs["min_percentage_general"] == 50.0

def test_get_campus_statistics():
    req = CampusStatisticsRequest(category="programs")
    res = CampusKnowledgeTools.get_campus_statistics(req, caller="test_runner")
    assert "statistics" in res
    stats = res["statistics"]
    assert stats["total_programs"] >= 400
    assert stats["total_faculty"] >= 2000
    assert stats["total_classrooms"] >= 200
def test_official_srm_regulations_2021_course_lookup():
    req = CourseLookupRequest(query="21CSC206T")
    res = CampusKnowledgeTools.lookup_course(req, caller="test_runner")
    assert res["match_count"] >= 1
    ai_course = next(c for c in res["courses"] if c["code"] == "21CSC206T")
    assert "Artificial Intelligence" in ai_course["name"]
    assert ai_course["credits"] == 3
    assert ai_course["regulation"] == "2021"
    assert ai_course["is_official"] is True

def test_official_srm_regulations_2021_prerequisites():
    # 21CSO451T Deep Learning Foundation requires 21CSC206T Artificial Intelligence
    req = PrerequisiteVerifyRequest(completed_courses=["21CSC206T"], target_course="21CSO451T")
    res = CampusKnowledgeTools.verify_prerequisites(req, caller="test_runner")
    assert res["eligible"] is True
    assert len(res["missing_prerequisites"]) == 0

    req_fail = PrerequisiteVerifyRequest(completed_courses=[], target_course="21CSO451T")
    res_fail = CampusKnowledgeTools.verify_prerequisites(req_fail, caller="test_runner")
    assert res_fail["eligible"] is False
    assert "21CSC206T" in res_fail["missing_prerequisites"]

def test_get_semester_curriculum_specific_semester():
    req = SemesterCurriculumRequest(program_query="CSE", semester=3)
    res = CampusKnowledgeTools.get_semester_curriculum(req, caller="test_runner")
    assert "error" not in res
    assert "Computer Science and Engineering" in res["program_name"]
    assert res["semester"] == 3
    assert res["academic_year"] == 2
    assert res["course_count"] >= 5
    assert res["total_credits"] >= 15
    codes = [c["course_code"] for c in res["courses"]]
    # Data Structures & Algorithms (21CSC201J) and Operating Systems (21CSC202J) are core 3rd semester subjects
    assert "21CSC201J" in codes
    assert "21CSC202J" in codes

def test_get_semester_curriculum_full_plan():
    req = SemesterCurriculumRequest(program_query="Mechanical Engineering")
    res = CampusKnowledgeTools.get_semester_curriculum(req, caller="test_runner")
    assert "error" not in res
    assert "Mechanical" in res["program_name"]
    assert res["total_semesters"] == 8
    assert res["total_credits"] >= 140
    assert "Semester 1" in res["semesters"]
    assert "Semester 8" in res["semesters"]

def test_get_semester_curriculum_ai_program():
    req = SemesterCurriculumRequest(program_query="Artificial Intelligence", semester=4)
    res = CampusKnowledgeTools.get_semester_curriculum(req, caller="test_runner")
    assert "error" not in res
    assert "Artificial Intelligence" in res["program_name"]
    assert res["semester"] == 4
    assert res["course_count"] >= 5

if __name__ == "__main__":
    pytest.main(["-v", __file__])

