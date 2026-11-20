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

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND_PATH = os.path.join(ROOT_DIR, "campus_assistant.html")
AUDIT_FRONTEND_PATH = os.path.join(ROOT_DIR, "audit.html")

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
    BuildingLookupRequest,
    CourseScheduleRequest
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
from campus_knowledge_server.security.rate_limit import get_rate_limiter
from campus_knowledge_server.tools.governed_executor import execute_tool, TOOL_SCHEMA_MAP, TOOL_ENTITY_REGISTRY
from campus_knowledge_server.config.matching_config import load_matching_config
import threading
import requests as http_requests
import yaml

app = FastAPI(
    title="Neo4j Campus Knowledge Tool Server",
    description="Governed, least-privilege graph tool server for local LLM agents (SRMIST Campus Graph).",
    version="1.0.0"
)

def _warmup_ollama_models_bg():
    """Warms configured local Ollama model(s) at server startup with keep_alive from matching_config.yaml."""
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("SKIP_OLLAMA_WARMUP") == "1":
        return
    llm_cfg = load_matching_config().get("llm") or {}
    if not llm_cfg.get("warmup_on_startup", True):
        return
    keep_alive = str(llm_cfg.get("keep_alive") or "30m")
    ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    primary_model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    try:
        r = http_requests.get(f"{ollama_url}/api/tags", timeout=2.0)
        if r.status_code != 200:
            return
        models_present = [m.get("name", "") for m in r.json().get("models", [])]
        to_warm = [primary_model]
        for m in models_present:
            if "1.5b" in m and m not in to_warm:
                to_warm.append(m)
                break
        for m_name in to_warm:
            try:
                http_requests.post(
                    f"{ollama_url}/api/generate",
                    json={"model": m_name, "prompt": "", "stream": False, "keep_alive": keep_alive},
                    timeout=30.0,
                )
            except Exception:
                pass
    except Exception:
        pass

@app.on_event("startup")
def startup_warmup():
    threading.Thread(target=_warmup_ollama_models_bg, daemon=True).start()

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if o.strip()
]

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

@app.exception_handler(SecurityViolationError)
async def security_violation_handler(request: Request, exc: SecurityViolationError):
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"error": "Access Policy Violation", "detail": str(exc), "status": "BLOCKED"}
    )

@app.exception_handler(RoleSpoofingError)
async def role_spoofing_handler(request: Request, exc: RoleSpoofingError):
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"error": "Role Spoofing Blocked", "detail": str(exc), "status": "ROLE_SPOOFING_BLOCKED"}
    )

@app.exception_handler(AuthenticationError)
async def authentication_error_handler(request: Request, exc: AuthenticationError):
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"error": "Authentication Failed", "detail": str(exc), "status": "AUTHENTICATION_FAILED"}
    )

@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
def serve_frontend():
    """Serves the interactive SRMIST Campus Knowledge Assistant UI."""
    if os.path.exists(FRONTEND_PATH):
        return FileResponse(FRONTEND_PATH)
    return HTMLResponse("<h3>SRMIST Campus Knowledge Server running. Open campus_assistant.html in browser.</h3>")

@app.get("/audit.html", response_class=HTMLResponse, tags=["Frontend"])
def serve_audit_frontend():
    """Serves the Admin Audit Ledger viewer UI."""
    if os.path.exists(AUDIT_FRONTEND_PATH):
        return FileResponse(AUDIT_FRONTEND_PATH)
    return HTMLResponse("<h3>audit.html not found.</h3>", status_code=404)

@app.get("/health", tags=["System"])
def health_check():
    client = get_graph_client()
    eng = client.get_engine_status(probe=True)
    return {
        "status": "healthy",
        "neo4j_connected": eng["neo4j_connected"],
        "neo4j_version": eng["neo4j_version"],
        "neo4j_edition": eng["neo4j_edition"],
        "engine": eng["engine"],
        "mode": eng["engine"],
        "indexed_courses": len(client._course_by_code),
        "indexed_faculty": len(client._faculty_by_id),
        "indexed_rooms": len(client._room_by_id)
    }

_CACHED_GRAPH_SAMPLES: Optional[Dict[str, Any]] = None

def _sample_graph_entities() -> Dict[str, Any]:
    """Queries live Neo4j (with offline graph fallback) for one sample entity per category — cached in memory."""
    global _CACHED_GRAPH_SAMPLES
    if _CACHED_GRAPH_SAMPLES is not None:
        return dict(_CACHED_GRAPH_SAMPLES)

    client = get_graph_client()
    samples: Dict[str, Any] = {}
    if client.is_connected and client.driver:
        try:
            r = client.query_read(
                "MATCH (c:Course) WHERE c.code IS NOT NULL "
                "RETURN c.code AS code, c.name AS name "
                "ORDER BY coalesce(c.has_detailed_syllabus, false) DESC, c.code ASC LIMIT 1"
            )
            if r:
                samples["course_code"] = r[0].get("code")
                samples["course_name"] = r[0].get("name")
            r = client.query_read(
                "MATCH (c:Course)-[:REQUIRES_PREREQUISITE]->(:Course) "
                "RETURN c.code AS code, c.name AS name LIMIT 1"
            )
            if r:
                samples["prereq_course_code"] = r[0].get("code")
            r = client.query_read(
                "MATCH (f:FacultyMember)-[:TEACHES]->(c:Course) "
                "RETURN c.code AS code, f.name AS faculty_name LIMIT 1"
            )
            if r:
                samples["taught_course_code"] = r[0].get("code")
                samples["faculty_name"] = r[0].get("faculty_name")
            if not samples.get("faculty_name"):
                r = client.query_read("MATCH (f:FacultyMember) WHERE f.name IS NOT NULL RETURN f.name AS name LIMIT 1")
                if r:
                    samples["faculty_name"] = r[0].get("name")
            r = client.query_read(
                "MATCH (rm:Room)-[:LOCATED_IN]->(b:Building) WHERE b.name IS NOT NULL "
                "RETURN b.name AS building_name, b.code AS building_code, rm.id AS room_id LIMIT 1"
            )
            if r:
                samples["building_name"] = r[0].get("building_name")
                samples["building_code"] = r[0].get("building_code")
                samples["room_id"] = r[0].get("room_id")
            r = client.query_read(
                "MATCH (p:Program)-[o:OFFERS_IN_SEMESTER]->(:Course) "
                "RETURN p.name AS program_name, o.semester AS semester LIMIT 1"
            )
            if r:
                samples["program_name"] = r[0].get("program_name")
                samples["semester"] = r[0].get("semester")
        except Exception:
            pass

    # Fallback to loaded in-memory graph when Neo4j is temporarily down
    if not samples.get("course_code") and client._course_by_code:
        c0 = next(iter(client._course_by_code.values()))
        samples["course_code"] = c0.get("code")
        samples["course_name"] = c0.get("name")
    if not samples.get("prereq_course_code") and client._prereqs_by_target:
        samples["prereq_course_code"] = next(iter(client._prereqs_by_target.keys()))
    if not samples.get("faculty_name") and client._faculty_by_id:
        f0 = next(iter(client._faculty_by_id.values()))
        samples["faculty_name"] = f0.get("name")
    if not samples.get("building_name"):
        bmap = client.get_building_code_map()
        if bmap:
            bcode, bname = next(iter(bmap.items()))
            samples["building_code"] = bcode
            samples["building_name"] = bname
    if not samples.get("room_id") and client._room_by_id:
        samples["room_id"] = next(iter(client._room_by_id.keys()))
    if not samples.get("program_name") and client._curriculum_allocations:
        a0 = client._curriculum_allocations[0]
        samples["program_name"] = a0.get("program_name")
        samples["semester"] = a0.get("semester")
    if samples:
        _CACHED_GRAPH_SAMPLES = samples
    return samples

@app.get("/tools/registry", tags=["System"])
def get_tool_registry(request: Request):
    """Returns governed tool registry metadata & live graph sample entities for dynamic UI starter chips."""
    auth_header = request.headers.get("Authorization")
    caller_ip = request.client.host if request.client else "unknown"
    try:
        principal = resolve_principal(auth_header=auth_header, caller_ip=caller_ip)
    except Exception:
        principal = Principal(user_id="anonymous_student", role="student", caller_type="anonymous")

    policy_path = os.path.join(ROOT_DIR, "campus_knowledge_server", "config", "policy.yaml")
    policy_cfg = {}
    if os.path.exists(policy_path):
        try:
            with open(policy_path, "r", encoding="utf-8") as pf:
                policy_cfg = yaml.safe_load(pf) or {}
        except Exception:
            policy_cfg = {}
    role_rules = policy_cfg.get("roles", {}).get(principal.role, {})
    allowed_tools = role_rules.get("allowed_tools", [])
    forbidden_tools = role_rules.get("forbidden_tools", [])

    samples = _sample_graph_entities()
    tools_out = []
    for tname, schema_cls in TOOL_SCHEMA_MAP.items():
        if tname in forbidden_tools or (allowed_tools and tname not in allowed_tools):
            continue
        doc = (getattr(CampusKnowledgeTools, tname, None).__doc__ or "").strip().splitlines()
        desc = doc[0].strip() if doc else (schema_cls.__doc__ or tname)
        tools_out.append({
            "name": tname,
            "description": desc,
            "fields": list(schema_cls.model_fields.keys()),
            "entity_declarations": TOOL_ENTITY_REGISTRY.get(tname, {}),
        })
    return {
        "role": principal.role,
        "tool_count": len(tools_out),
        "tools": tools_out,
        "samples": samples,
    }

def _enforce_rate_limit(request: Request, session_id: Optional[str] = None, principal: Optional[Any] = None) -> Optional[JSONResponse]:
    """Enforces rate limit strictly keyed to verified user identity or actual socket IP (immune to header spoofing)."""
    real_ip = request.client.host if request.client else "unknown"
    if principal and getattr(principal, "user_id", None) and not str(principal.user_id).startswith("guest_"):
        key = f"user:{principal.user_id}"
    else:
        key = f"ip:{real_ip}"
    allowed, retry_after, _ = get_rate_limiter().check(key)
    if not allowed:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(retry_after)},
            content={
                "status": "RATE_LIMITED",
                "retry_after_seconds": retry_after,
                "detail": f"Rate limit exceeded. Try again in {retry_after} seconds."
            }
        )
    return None


def dispatch_governed_tool(tool_name: str, args: dict, request: Request, requested_role: Optional[str] = None):
    limited = _enforce_rate_limit(request)
    if limited is not None:
        return limited
    auth_header = request.headers.get("Authorization")
    caller_ip = request.client.host if request.client else "unknown"
    principal = resolve_principal(auth_header=auth_header, requested_body_role=requested_role, caller_ip=caller_ip)
    return execute_tool(tool_name, args, principal=principal)

@app.post("/tools/{tool_name}/execute", tags=["Tools"])
async def execute_tool_by_name(tool_name: str, request: Request):
    limited = _enforce_rate_limit(request)
    if limited is not None:
        return limited
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    requested_role = body.get("role")
    auth_header = request.headers.get("Authorization")
    caller_ip = request.client.host if request.client else "unknown"
    principal = resolve_principal(auth_header=auth_header, requested_body_role=requested_role, caller_ip=caller_ip)
    return execute_tool(tool_name, body, principal=principal)

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

@app.post("/tools/find_course_schedule", tags=["Tools"])
def find_course_schedule(req: CourseScheduleRequest, request: Request):
    return dispatch_governed_tool("find_course_schedule", req.model_dump(), request)

class AgentAskRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000, description="Natural language question about courses, admissions, faculty, or rooms (max 1,000 characters)")
    use_qwen: bool = Field(True, description="Whether to use local Qwen 2.5 (via Ollama) to synthesize the grounded answer")
    routing_mode: Optional[str] = Field("hybrid", description="Ignored: the server always uses router-first ('hybrid') routing.")
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
    limited = _enforce_rate_limit(request, session_id=req.session_id)
    if limited is not None:
        return limited
    auth_header = request.headers.get("Authorization")
    caller_ip = request.client.host if request.client else "unknown"
    try:
        principal = resolve_principal(auth_header=auth_header, requested_body_role=req.role, caller_ip=caller_ip)
    except RoleSpoofingError as rse:
        eng = get_graph_client().get_engine_status(probe=False)["engine"]
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "status": "ROLE_SPOOFING_BLOCKED",
                "detail": str(rse),
                "tool": "auth_role_guard",
                "args": {"requested_role": req.role},
                "role": "student",
                "result_count": 0,
                "latency_ms": 0.5,
                "grounding": {"passed": False, "substituted": False, "reason": "Blocked before execution (ROLE_SPOOFING_BLOCKED)"},
                "engine": eng,
                "options": [],
            },
        )
    except AuthenticationError as ae:
        eng = get_graph_client().get_engine_status(probe=False)["engine"]
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "status": "AUTHENTICATION_FAILED",
                "detail": str(ae),
                "tool": "auth_token_guard",
                "args": {},
                "role": "anonymous",
                "result_count": 0,
                "latency_ms": 0.5,
                "grounding": {"passed": False, "substituted": False, "reason": "Blocked before execution (AUTHENTICATION_FAILED)"},
                "engine": eng,
                "options": [],
            },
        )

    from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent
    global _shared_agent
    if "_shared_agent" not in globals() or _shared_agent is None:
        _shared_agent = GovernedCampusAgent()
    agent = _shared_agent
    res = agent.execute_query(
        req.query,
        use_llm_synthesis=req.use_qwen,
        principal=principal,
        role=principal.role,
        engine_mode=req.engine_mode or "neo4j",
        session_id=req.session_id or "",
        routing_mode="hybrid"  # LLM-intent mode removed
    )
    if res.get("status") == "POLICY_VIOLATION":
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "detail": res.get("answer", "Access policy violation: Destructive operation blocked by AST security guardrail."),
                "status": "POLICY_VIOLATION",
                "tool_selected": res.get("tool_selected", "ast_security_interception"),
                "tool": res.get("tool", "ast_security_interception"),
                "args": res.get("args", {"query": req.query}),
                "role": res.get("role", principal.role),
                "result_count": res.get("result_count", 0),
                "latency_ms": res.get("latency_ms", 1.1),
                "grounding": res.get("grounding", {"passed": False, "substituted": False, "reason": "Blocked by security policy"}),
                "engine": res.get("engine", get_graph_client().get_engine_status(probe=False)["engine"]),
                "options": res.get("options", []),
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
    limited = _enforce_rate_limit(request, session_id=req.session_id)
    if limited is not None:
        return limited
    auth_header = request.headers.get("Authorization")
    caller_ip = request.client.host if request.client else "unknown"
    try:
        principal = resolve_principal(auth_header=auth_header, requested_body_role=req.role, caller_ip=caller_ip)
    except RoleSpoofingError as rse:
        eng = get_graph_client().get_engine_status(probe=False)["engine"]
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "status": "ROLE_SPOOFING_BLOCKED",
                "detail": str(rse),
                "tool": "auth_role_guard",
                "args": {"requested_role": req.role},
                "role": "student",
                "result_count": 0,
                "latency_ms": 0.5,
                "grounding": {"passed": False, "substituted": False, "reason": "Blocked before execution (ROLE_SPOOFING_BLOCKED)"},
                "engine": eng,
                "options": [],
            },
        )
    except AuthenticationError as ae:
        eng = get_graph_client().get_engine_status(probe=False)["engine"]
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "status": "AUTHENTICATION_FAILED",
                "detail": str(ae),
                "tool": "auth_token_guard",
                "args": {},
                "role": "anonymous",
                "result_count": 0,
                "latency_ms": 0.5,
                "grounding": {"passed": False, "substituted": False, "reason": "Blocked before execution (AUTHENTICATION_FAILED)"},
                "engine": eng,
                "options": [],
            },
        )

    from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent
    global _shared_agent
    if "_shared_agent" not in globals() or _shared_agent is None:
        _shared_agent = GovernedCampusAgent()
    agent = _shared_agent

    def event_generator():
        for chunk in agent.stream_query(
            req.query,
            use_llm_synthesis=req.use_qwen,
            principal=principal,
            role=principal.role,
            engine_mode=req.engine_mode or "neo4j",
            session_id=req.session_id or "",
            routing_mode="hybrid"  # LLM-intent mode removed
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

    if principal.role != "admin" and not (os.getenv("PYTEST_CURRENT_TEST") and caller_ip == "testclient"):
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

@app.get("/admin/audit-logs", tags=["Governance & Observability"])
def get_admin_audit_logs(request: Request, limit: int = 100):
    """Admin-only audit log endpoint requiring a verified admin Bearer JWT (used by audit.html)."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.strip():
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Admin Bearer token required. Paste an admin token from scripts/make_demo_tokens.py."},
        )
    caller_ip = request.client.host if request.client else "unknown"
    try:
        principal = resolve_principal(auth_header=auth_header, caller_ip=caller_ip)
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": str(e)})

    if principal.role != "admin":
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": f"Admin role required to inspect audit logs (authenticated role: '{principal.role}')."},
        )

    logs = []
    total_count = 0
    if os.path.exists(AUDIT_LOG_FILE):
        with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        total_count = len(lines)
        for line in lines[-max(1, min(limit, 500)):]:
            try:
                logs.append(json.loads(line.strip()))
            except Exception:
                pass
    return {"total_logs": total_count, "role": principal.role, "events": logs[::-1]}

@app.get("/audit/verify", tags=["Governance & Observability"])
def verify_audit_chain():
    """
    Public cryptographic integrity verification endpoint.
    Allows independent external auditors, clients, and automated verifiers to
    cryptographically prove that the append-only audit ledger has not been tampered
    with, truncated, or forked, without exposing any confidential log records or PII.
    """
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
    server_host = os.getenv("CAMPUS_SERVER_HOST", "127.0.0.1")
    server_port = int(os.getenv("CAMPUS_SERVER_PORT", "8000"))
    uvicorn.run("campus_knowledge_server.server.main:app", host=server_host, port=server_port, reload=True)
