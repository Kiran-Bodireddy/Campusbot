"""
Model Context Protocol (MCP) Server for Campus Knowledge Graph
Allows local agents (Qwen, Claude, Cursor, Antigravity) to call governed tools
via the standard Model Context Protocol over stdio or SSE.
Enforces least-privilege student principal on all MCP calls (P2).
"""

from typing import List, Optional, Dict, Any
from fastmcp import FastMCP

from campus_knowledge_server.security.auth import Principal
from campus_knowledge_server.tools.governed_executor import execute_tool

mcp = FastMCP("CampusKnowledgeToolServer")
MCP_PRINCIPAL = Principal(user_id="mcp_stdio_client", role="student", caller_type="mcp")

@mcp.tool(name="lookup_course", description="Search and lookup SRMIST academic courses by course code (e.g. 21CSC201J) or title.")
def lookup_course(query: str) -> Dict[str, Any]:
    return execute_tool("lookup_course", {"query": query}, principal=MCP_PRINCIPAL)

@mcp.tool(name="get_prerequisite_tree", description="Recursively retrieves the prerequisite dependency tree for a target course code up to depth 4.")
def get_prerequisite_tree(course_code: str, max_depth: int = 3) -> Dict[str, Any]:
    return execute_tool("get_prerequisite_tree", {"course_code": course_code, "max_depth": max_depth}, principal=MCP_PRINCIPAL)

@mcp.tool(name="verify_prerequisites", description="Verifies if completed courses satisfy all prerequisites to enroll in a target course.")
def verify_prerequisites(completed_courses: List[str], target_course: str) -> Dict[str, Any]:
    return execute_tool("verify_prerequisites", {"completed_courses": completed_courses, "target_course": target_course}, principal=MCP_PRINCIPAL)

@mcp.tool(name="find_faculty_for_course", description="Finds verified professors and instructors teaching a specific course code.")
def find_faculty_for_course(course_code: str) -> Dict[str, Any]:
    return execute_tool("find_faculty_for_course", {"course_code": course_code}, principal=MCP_PRINCIPAL)

@mcp.tool(name="lookup_faculty_profile", description="Looks up a faculty member's department, designation, qualifications, and research.")
def lookup_faculty_profile(faculty_name: str) -> Dict[str, Any]:
    return execute_tool("lookup_faculty_profile", {"faculty_name": faculty_name}, principal=MCP_PRINCIPAL)

@mcp.tool(name="find_room_schedule", description="Retrieves the timetable and occupancy for a specific campus classroom (e.g. TP-101, UB-202).")
def find_room_schedule(room_id: str, day_of_week: Optional[str] = None) -> Dict[str, Any]:
    return execute_tool("find_room_schedule", {"room_id": room_id, "day_of_week": day_of_week}, principal=MCP_PRINCIPAL)

@mcp.tool(name="find_available_rooms", description="Finds unoccupied rooms in a building (e.g. TP, UB, BEL) for a specific day and timeslot.")
def find_available_rooms(building_code: str, min_capacity: int = 30, day: str = "Monday", slot: str = "08:45-09:35") -> Dict[str, Any]:
    return execute_tool("find_available_rooms", {"building_code": building_code, "min_capacity": min_capacity, "day": day, "slot": slot}, principal=MCP_PRINCIPAL)

@mcp.tool(name="search_courses_semantic", description="Discovers courses by natural language topic, domain, or career keyword via Neo4j vector index.")
def search_courses_semantic(query: str, top_k: int = 5) -> Dict[str, Any]:
    return execute_tool("search_courses_semantic", {"query": query, "top_k": top_k}, principal=MCP_PRINCIPAL)

@mcp.tool(name="check_admission_eligibility", description="Checks official SRMIST admission eligibility requirements, minimum percentage, required stream/subjects, and entrance exams.")
def check_admission_eligibility(program_query: str, candidate_percentage: Optional[float] = None, is_reserved_category: bool = False, candidate_stream: Optional[str] = None) -> Dict[str, Any]:
    return execute_tool("check_admission_eligibility", {
        "program_query": program_query,
        "candidate_percentage": candidate_percentage,
        "is_reserved_category": is_reserved_category,
        "candidate_stream": candidate_stream
    }, principal=MCP_PRINCIPAL)

@mcp.tool(name="get_campus_statistics", description="Returns aggregate campus knowledge graph statistics across courses, faculty, rooms, and departments.")
def get_campus_statistics(category: str = "all") -> Dict[str, Any]:
    return execute_tool("get_campus_statistics", {"category": category}, principal=MCP_PRINCIPAL)

@mcp.tool(name="get_semester_curriculum", description="Retrieves semester curriculum implementation plans and course breakdowns.")
def get_semester_curriculum(program_query: str, semester: Optional[int] = None) -> Dict[str, Any]:
    return execute_tool("get_semester_curriculum", {"program_query": program_query, "semester": semester}, principal=MCP_PRINCIPAL)

@mcp.tool(name="lookup_building", description="Retrieves verified campus building descriptions, floors, departments housed, key facilities, and rooms.")
def lookup_building(query: str) -> Dict[str, Any]:
    return execute_tool("lookup_building", {"query": query}, principal=MCP_PRINCIPAL)

@mcp.tool(name="find_course_schedule", description="Retrieves classroom allocations and weekly timetable slots for a given course code.")
def find_course_schedule(course_code: str, day_of_week: Optional[str] = None) -> Dict[str, Any]:
    return execute_tool("find_course_schedule", {"course_code": course_code, "day_of_week": day_of_week}, principal=MCP_PRINCIPAL)

if __name__ == "__main__":
    mcp.run()
