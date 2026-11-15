"""
Model Context Protocol (MCP) Server for Campus Knowledge Graph
Allows local agents (Qwen, Claude, Cursor, Antigravity) to call governed tools
via the standard Model Context Protocol over stdio or SSE.
"""

from typing import List, Optional, Dict, Any
from fastmcp import FastMCP

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
    GovernedQueryTemplateRequest,
    AdmissionEligibilityRequest
)

mcp = FastMCP("CampusKnowledgeToolServer")

@mcp.tool(name="lookup_course", description="Search and lookup SRMIST academic courses by course code (e.g. CSE201) or title.")
def lookup_course(query: str) -> Dict[str, Any]:
    req = CourseLookupRequest(query=query)
    return CampusKnowledgeTools.lookup_course(req, caller="mcp_agent")

@mcp.tool(name="get_prerequisite_tree", description="Recursively retrieves the prerequisite dependency tree for a target course code up to depth 4.")
def get_prerequisite_tree(course_code: str, max_depth: int = 3) -> Dict[str, Any]:
    req = PrerequisiteTreeRequest(course_code=course_code, max_depth=max_depth)
    return CampusKnowledgeTools.get_prerequisite_tree(req, caller="mcp_agent")

@mcp.tool(name="verify_prerequisites", description="Verifies if completed courses satisfy all prerequisites to enroll in a target course.")
def verify_prerequisites(completed_courses: List[str], target_course: str) -> Dict[str, Any]:
    req = PrerequisiteVerifyRequest(completed_courses=completed_courses, target_course=target_course)
    return CampusKnowledgeTools.verify_prerequisites(req, caller="mcp_agent")

@mcp.tool(name="find_faculty_for_course", description="Finds verified professors and instructors teaching a specific course code.")
def find_faculty_for_course(course_code: str) -> Dict[str, Any]:
    req = FacultyCourseRequest(course_code=course_code)
    return CampusKnowledgeTools.find_faculty_for_course(req, caller="mcp_agent")

@mcp.tool(name="lookup_faculty_profile", description="Looks up a faculty member's department, designation, qualifications, and research.")
def lookup_faculty_profile(faculty_name: str) -> Dict[str, Any]:
    req = FacultyProfileRequest(faculty_name=faculty_name)
    return CampusKnowledgeTools.lookup_faculty_profile(req, caller="mcp_agent")

@mcp.tool(name="find_room_schedule", description="Retrieves the timetable and occupancy for a specific campus classroom (e.g. TP-101, UB-202).")
def find_room_schedule(room_id: str, day_of_week: Optional[str] = None) -> Dict[str, Any]:
    req = RoomScheduleRequest(room_id=room_id, day_of_week=day_of_week)
    return CampusKnowledgeTools.find_room_schedule(req, caller="mcp_agent")

@mcp.tool(name="find_available_rooms", description="Finds unoccupied rooms in a building (e.g. TP, UB, BEL) for a specific day and timeslot.")
def find_available_rooms(building_code: str, min_capacity: int = 30, day: str = "Monday", slot: str = "08:45-09:35") -> Dict[str, Any]:
    req = AvailableRoomsRequest(building_code=building_code, min_capacity=min_capacity, day=day, slot=slot)
    return CampusKnowledgeTools.find_available_rooms(req, caller="mcp_agent")

@mcp.tool(name="search_courses_semantic", description="Discovers courses by natural language topic, domain, or career keyword.")
def search_courses_semantic(query: str, top_k: int = 5) -> Dict[str, Any]:
    req = SemanticSearchRequest(query=query, top_k=top_k)
    return CampusKnowledgeTools.search_courses_semantic(req, caller="mcp_agent")

@mcp.tool(name="check_admission_eligibility", description="Checks official SRMIST admission eligibility requirements, minimum percentage, required stream/subjects, and entrance exams (SRMJEEE, NEET, CAT, NATA, etc.) for any degree program.")
def check_admission_eligibility(program_query: str, candidate_percentage: Optional[float] = None, is_reserved_category: bool = False, candidate_stream: Optional[str] = None) -> Dict[str, Any]:
    req = AdmissionEligibilityRequest(
        program_query=program_query,
        candidate_percentage=candidate_percentage,
        is_reserved_category=is_reserved_category,
        candidate_stream=candidate_stream
    )
    return CampusKnowledgeTools.check_admission_eligibility(req, caller="mcp_agent")

if __name__ == "__main__":
    # Run in stdio mode for local MCP clients
    mcp.run()
