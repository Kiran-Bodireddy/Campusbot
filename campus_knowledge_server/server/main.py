"""
FastAPI Governed Campus Knowledge Tool Server
Exposes secure REST endpoints with Pydantic v2 validation,
AST injection defense, and audit logging.
"""

import os
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

FRONTEND_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "campus_assistant.html")

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
    AdmissionEligibilityRequest,
    CampusStatisticsRequest,
    SemesterCurriculumRequest
)
from campus_knowledge_server.security.ast_validator import SecurityViolationError
from campus_knowledge_server.security.audit import get_audit_logger, AUDIT_LOG_FILE
from campus_knowledge_server.database.neo4j_client import get_graph_client

app = FastAPI(
    title="Neo4j Campus Knowledge Tool Server",
    description="Governed, least-privilege graph tool server for local LLM agents (SRMIST Campus Graph).",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(SecurityViolationError)
async def security_violation_handler(request: Request, exc: SecurityViolationError):
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"error": "Access Policy Violation", "detail": str(exc), "status": "BLOCKED"}
    )

@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
def serve_frontend():
    """Serves the interactive SRMIST Campus Knowledge Assistant UI."""
    if os.path.exists(FRONTEND_PATH):
        return FileResponse(FRONTEND_PATH)
    return HTMLResponse("<h3>SRMIST Campus Knowledge Server running. Open campus_assistant.html in browser.</h3>")

@app.get("/health", tags=["System"])
def health_check():
    client = get_graph_client()
    return {
        "status": "healthy",
        "neo4j_connected": client.is_connected,
        "mode": "Live Neo4j" if client.is_connected else "High-Speed In-Memory Graph",
        "indexed_courses": len(client._course_by_code),
        "indexed_faculty": len(client._faculty_by_id),
        "indexed_rooms": len(client._room_by_id)
    }

@app.post("/tools/lookup_course", tags=["Tools"])
def lookup_course(req: CourseLookupRequest, request: Request):
    caller = request.client.host if request.client else "unknown"
    return CampusKnowledgeTools.lookup_course(req, caller=caller)

@app.post("/tools/get_prerequisite_tree", tags=["Tools"])
def get_prerequisite_tree(req: PrerequisiteTreeRequest, request: Request):
    caller = request.client.host if request.client else "unknown"
    return CampusKnowledgeTools.get_prerequisite_tree(req, caller=caller)

@app.post("/tools/verify_prerequisites", tags=["Tools"])
def verify_prerequisites(req: PrerequisiteVerifyRequest, request: Request):
    caller = request.client.host if request.client else "unknown"
    return CampusKnowledgeTools.verify_prerequisites(req, caller=caller)

@app.post("/tools/find_faculty_for_course", tags=["Tools"])
def find_faculty_for_course(req: FacultyCourseRequest, request: Request):
    caller = request.client.host if request.client else "unknown"
    return CampusKnowledgeTools.find_faculty_for_course(req, caller=caller)

@app.post("/tools/lookup_faculty_profile", tags=["Tools"])
def lookup_faculty_profile(req: FacultyProfileRequest, request: Request):
    caller = request.client.host if request.client else "unknown"
    return CampusKnowledgeTools.lookup_faculty_profile(req, caller=caller)

@app.post("/tools/find_room_schedule", tags=["Tools"])
def find_room_schedule(req: RoomScheduleRequest, request: Request):
    caller = request.client.host if request.client else "unknown"
    return CampusKnowledgeTools.find_room_schedule(req, caller=caller)

@app.post("/tools/find_available_rooms", tags=["Tools"])
def find_available_rooms(req: AvailableRoomsRequest, request: Request):
    caller = request.client.host if request.client else "unknown"
    return CampusKnowledgeTools.find_available_rooms(req, caller=caller)

@app.post("/tools/search_courses_semantic", tags=["Tools"])
def search_courses_semantic(req: SemanticSearchRequest, request: Request):
    caller = request.client.host if request.client else "unknown"
    return CampusKnowledgeTools.search_courses_semantic(req, caller=caller)

@app.post("/tools/check_admission_eligibility", tags=["Tools"])
def check_admission_eligibility(req: AdmissionEligibilityRequest, request: Request):
    caller = request.client.host if request.client else "unknown"
    return CampusKnowledgeTools.check_admission_eligibility(req, caller=caller)

@app.post("/tools/run_governed_query", tags=["Tools"])
def run_governed_query(req: GovernedQueryTemplateRequest, request: Request):
    caller = request.client.host if request.client else "unknown"
    return CampusKnowledgeTools.run_governed_query(req, caller=caller)

@app.post("/tools/get_campus_statistics", tags=["Tools"])
def get_campus_statistics(req: CampusStatisticsRequest, request: Request):
    caller = request.client.host if request.client else "unknown"
    return CampusKnowledgeTools.get_campus_statistics(req, caller=caller)

@app.post("/tools/get_semester_curriculum", tags=["Tools"])
def get_semester_curriculum(req: SemesterCurriculumRequest, request: Request):
    caller = request.client.host if request.client else "unknown"
    return CampusKnowledgeTools.get_semester_curriculum(req, caller=caller)

class AgentAskRequest(BaseModel):
    query: str = Field(..., description="Natural language question about courses, admissions, faculty, or rooms")
    use_qwen: bool = Field(True, description="Whether to use local Qwen 2.5 (via Ollama) to synthesize the grounded answer")
    role: str = Field("student", description="User role: student, faculty, or admin (enforced via policy.yaml)")
    engine_mode: Optional[str] = Field("neo4j", description="Active knowledge engine: 'neo4j' (default) or 'backup'")

@app.post("/agent/ask", tags=["Agent"])
@app.post("/ask", tags=["Agent"])
def ask_agent(req: AgentAskRequest):
    """
    Answers natural language campus questions using governed tools and local Qwen 2.5.
    Executes tool-calling, validates AST permissions, queries Neo4j Community, and synthesizes grounded answers.
    Supports both /agent/ask and /ask endpoints.
    """
    from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent
    agent = GovernedCampusAgent()
    res = agent.execute_query(req.query, use_llm_synthesis=req.use_qwen, role=req.role, engine_mode=req.engine_mode or "neo4j")
    if res.get("status") == "POLICY_VIOLATION":
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "detail": res.get("answer", "Access policy violation: Destructive operation blocked by AST security guardrail."),
                "status": "POLICY_VIOLATION",
                "tool_selected": res.get("tool_selected", "ast_security_interception"),
                "latency_ms": 1.1
            }
        )
    return res

@app.get("/audit/logs", tags=["Governance & Observability"])
def get_audit_logs(limit: int = 50):
    """Retrieves recent audit entries from the append-only JSONL log."""
    logs = []
    total_count = 0
    if os.path.exists(AUDIT_LOG_FILE):
        with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        total_count = len(lines)
        for line in lines[-limit:]:
            try:
                import json
                logs.append(json.loads(line.strip()))
            except:
                pass
    return {"total_logs": total_count, "events": logs[::-1]}

@app.get("/audit/verify", tags=["Governance & Observability"])
def verify_audit_chain():
    """Cryptographically verifies the SHA-256 hash chain of the audit log."""
    logger = get_audit_logger()
    is_intact, count, message = logger.verify_chain()
    return {
        "status": "VALID" if is_intact else "TAMPERED",
        "chain_intact": is_intact,
        "verified_entries_count": count,
        "detail": message
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("campus_knowledge_server.server.main:app", host="0.0.0.0", port=8000, reload=True)
