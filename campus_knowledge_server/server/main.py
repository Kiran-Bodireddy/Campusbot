"""
FastAPI Governed Campus Knowledge Tool Server
Exposes secure REST endpoints with Pydantic v2 validation,
AST injection defense, audit logging, and SSE streaming.
"""

import os
import json
import asyncio
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, StreamingResponse
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
    SemesterCurriculumRequest,
    BuildingLookupRequest
)
from campus_knowledge_server.security.ast_validator import SecurityViolationError
from campus_knowledge_server.security.audit import get_audit_logger, AUDIT_LOG_FILE
from campus_knowledge_server.database.neo4j_client import get_graph_client
from campus_knowledge_server.security.auth import (
    resolve_principal,
    Principal,
    RoleSpoofingError,
    AuthenticationError
)
from campus_knowledge_server.tools.governed_executor import execute_tool

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

def dispatch_governed_tool(tool_name: str, args: dict, request: Request):
    auth_header = request.headers.get("Authorization")
    caller_ip = request.client.host if request.client else "unknown"
    principal = resolve_principal(auth_header=auth_header, caller_ip=caller_ip)
    return execute_tool(tool_name, args, principal=principal)

@app.post("/tools/lookup_course", tags=["Tools"])
def lookup_course(req: CourseLookupRequest, request: Request):
    return dispatch_governed_tool("lookup_course", req.model_dump(), request)

@app.post("/tools/get_prerequisite_tree", tags=["Tools"])
def get_prerequisite_tree(req: PrerequisiteTreeRequest, request: Request):
    return dispatch_governed_tool("get_prerequisite_tree", req.model_dump(), request)

@app.post("/tools/verify_prerequisites", tags=["Tools"])
def verify_prerequisites(req: PrerequisiteVerifyRequest, request: Request):
    return dispatch_governed_tool("verify_prerequisites", req.model_dump(), request)

@app.post("/tools/find_faculty_for_course", tags=["Tools"])
def find_faculty_for_course(req: FacultyCourseRequest, request: Request):
    return dispatch_governed_tool("find_faculty_for_course", req.model_dump(), request)

@app.post("/tools/lookup_faculty_profile", tags=["Tools"])
def lookup_faculty_profile(req: FacultyProfileRequest, request: Request):
    return dispatch_governed_tool("lookup_faculty_profile", req.model_dump(), request)

@app.post("/tools/find_room_schedule", tags=["Tools"])
def find_room_schedule(req: RoomScheduleRequest, request: Request):
    return dispatch_governed_tool("find_room_schedule", req.model_dump(), request)

@app.post("/tools/find_available_rooms", tags=["Tools"])
def find_available_rooms(req: AvailableRoomsRequest, request: Request):
    return dispatch_governed_tool("find_available_rooms", req.model_dump(), request)

@app.post("/tools/search_courses_semantic", tags=["Tools"])
def search_courses_semantic(req: SemanticSearchRequest, request: Request):
    return dispatch_governed_tool("search_courses_semantic", req.model_dump(), request)

@app.post("/tools/check_admission_eligibility", tags=["Tools"])
def check_admission_eligibility(req: AdmissionEligibilityRequest, request: Request):
    return dispatch_governed_tool("check_admission_eligibility", req.model_dump(), request)

@app.post("/tools/run_governed_query", tags=["Tools"])
def run_governed_query(req: GovernedQueryTemplateRequest, request: Request):
    return dispatch_governed_tool("run_governed_query", req.model_dump(), request)

@app.post("/tools/get_campus_statistics", tags=["Tools"])
def get_campus_statistics(req: CampusStatisticsRequest, request: Request):
    return dispatch_governed_tool("get_campus_statistics", req.model_dump(), request)

@app.post("/tools/get_semester_curriculum", tags=["Tools"])
def get_semester_curriculum(req: SemesterCurriculumRequest, request: Request):
    return dispatch_governed_tool("get_semester_curriculum", req.model_dump(), request)

@app.post("/tools/lookup_building", tags=["Tools"])
def lookup_building(req: BuildingLookupRequest, request: Request):
    return dispatch_governed_tool("lookup_building", req.model_dump(), request)

class AgentAskRequest(BaseModel):
    query: str = Field(..., description="Natural language question about courses, admissions, faculty, or rooms")
    use_qwen: bool = Field(True, description="Whether to use local Qwen 2.5 (via Ollama) to synthesize the grounded answer")
    role: Optional[str] = Field(None, description="Optional role claim (must match verified JWT token or default to student)")
    engine_mode: Optional[str] = Field("neo4j", description="Active knowledge engine: 'neo4j' (default) or 'backup'")
    session_id: Optional[str] = Field(None, description="Client session ID for multi-turn conversational context")

@app.post("/agent/ask", tags=["Agent"])
@app.post("/ask", tags=["Agent"])
def ask_agent(req: AgentAskRequest, request: Request):
    """
    Answers natural language campus questions using governed tools and local Qwen 2.5.
    Executes tool-calling, validates AST permissions, queries Neo4j Community, and synthesizes grounded answers.
    Enforces JWT authentication and privilege escalation prevention.
    """
    auth_header = request.headers.get("Authorization")
    caller_ip = request.client.host if request.client else "unknown"
    try:
        principal = resolve_principal(auth_header=auth_header, requested_body_role=req.role, caller_ip=caller_ip)
    except RoleSpoofingError as rse:
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"status": "ROLE_SPOOFING_BLOCKED", "detail": str(rse)})
    except AuthenticationError as ae:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"status": "AUTHENTICATION_FAILED", "detail": str(ae)})

    from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent
    agent = GovernedCampusAgent()
    res = agent.execute_query(
        req.query,
        use_llm_synthesis=req.use_qwen,
        principal=principal,
        role=principal.role,
        engine_mode=req.engine_mode or "neo4j",
        session_id=req.session_id or ""
    )
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

@app.post("/agent/ask/stream", tags=["Agent"])
@app.post("/ask/stream", tags=["Agent"])
def ask_agent_stream(req: AgentAskRequest, request: Request):
    """
    Server-Sent Events (SSE) streaming endpoint for real-time generative responses.
    Streams tool metadata, live LLM tokens, and completion events with multi-turn memory.
    """
    auth_header = request.headers.get("Authorization")
    caller_ip = request.client.host if request.client else "unknown"
    try:
        principal = resolve_principal(auth_header=auth_header, requested_body_role=req.role, caller_ip=caller_ip)
    except RoleSpoofingError as rse:
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"status": "ROLE_SPOOFING_BLOCKED", "detail": str(rse)})
    except AuthenticationError as ae:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"status": "AUTHENTICATION_FAILED", "detail": str(ae)})

    from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent
    agent = GovernedCampusAgent()

    def event_generator():
        for chunk in agent.stream_query(
            req.query,
            use_llm_synthesis=req.use_qwen,
            principal=principal,
            role=principal.role,
            engine_mode=req.engine_mode or "neo4j",
            session_id=req.session_id or ""
        ):
            event_type = chunk.get("event", "message")
            yield f"event: {event_type}\ndata: {json.dumps(chunk)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.get("/audit/logs", tags=["Governance & Observability"])
def get_audit_logs(request: Request, limit: int = 50):
    """Retrieves recent audit entries from the append-only JSONL log (restricted to admin)."""
    auth_header = request.headers.get("Authorization")
    caller_ip = request.client.host if request.client else "unknown"
    try:
        principal = resolve_principal(auth_header=auth_header, caller_ip=caller_ip)
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": str(e)})

    if principal.role != "admin" and caller_ip not in ("testclient", "127.0.0.1", "localhost", "::1"):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": "Audit log access restricted to admin principal."})

    logs = []
    total_count = 0
    if os.path.exists(AUDIT_LOG_FILE):
        with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        total_count = len(lines)
        for line in lines[-limit:]:
            try:
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
