# Neo4j Campus Knowledge Tool Server for Local Agents

> Governed, least-privilege tool server for local agents (Qwen 2.5) querying SRMIST courses, faculty, room schedules, and prerequisites without raw database access.

---

## 🏛️ System Overview

This system provides a zero-trust, governed graph tool layer between local LLM agents and the SRMIST Campus Knowledge Graph (Neo4j Community with in-memory graph fallback).

### Key Architectural Pillars
- **Tool Governance & Least Privilege**: The agent interacts exclusively through strict, parameterized tools (`lookup_course`, `get_prerequisite_tree`, `verify_prerequisites`, `find_faculty_for_course`, `lookup_faculty_profile`, `find_room_schedule`, `find_available_rooms`, `search_courses_semantic`).
- **AST Security Sanitizer**: Intercepts destructive keywords (`CREATE`, `MERGE`, `SET`, `DELETE`, `DROP`, `ALTER`, `LOAD CSV`, `CALL apoc.system.*`), blocks stacked statement injections, and enforces automatic `LIMIT 50` bounds.
- **Dual Interface**: Exposes tools over both **FastAPI REST API** and **FastMCP (Model Context Protocol)**.
- **Append-Only Audit Logging**: Every execution, caller identity, latency, and violation attempt is recorded in `logs/audit_telemetry.jsonl`.
- **Grounded Attribution**: Agent responses must cite exact entities (`[Course: ...]`, `[Faculty: ...]`, `[Room: ...]`) without hallucination.

---

## 📊 Final Evaluation Scorecard

Evaluated against the project benchmarks in `eval/run_eval.py`:

| Metric | Target Benchmark | Measured Result | Status |
| :--- | :---: | :---: | :---: |
| **Tool-Selection Accuracy** | $\ge 92\%$ | **100.0%** | Passed |
| **Cypher Execution Accuracy**| $100\%$ | **100.0%** | Passed |
| **Invalid-Query Rate** | $< 2\%$ | **0.0%** | Passed |
| **Grounded-Answer Score** | $\ge 90\%$ | **93.8%** | Passed |
| **Access-Policy Violations Blocked** | $100\%$ | **100.0%** | Passed |

---

## 🚀 Quickstart & Usage

### 1. Run Unit & Security Test Suites (27 Tests)
```bash
python -m pytest campus_knowledge_server\tests -v
```

### 2. Run the Benchmark Evaluation Suite
```bash
python campus_knowledge_server\eval\run_eval.py
```

### 3. Launch the FastAPI REST Tool Server
```bash
uvicorn campus_knowledge_server.server.main:app --host 0.0.0.0 --port 8000 --reload
```
- Interactive Swagger UI: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`
- Live Audit Log: `http://localhost:8000/audit/logs`

### 4. Run the FastMCP Server (for MCP Clients)
```bash
python campus_knowledge_server\server\mcp_server.py
```

To configure in your local MCP client (e.g., Claude Desktop, Antigravity, Cursor):
```json
{
  "mcpServers": {
    "campus-knowledge-server": {
      "command": "python",
      "args": ["-m", "campus_knowledge_server.server.mcp_server"],
      "cwd": "C:/Users/heyit/Downloads/courses"
    }
  }
}
```

---

## 📁 Repository Structure

```text
campus_knowledge_server/
├── data/
│   ├── faculty_master.csv          # Real Kattankulathur Campus faculty dataset (2,354 professors)
│   ├── build_campus_dataset.py     # Graph synthesis & Cypher generation engine
│   ├── campus_graph_unified.json   # Unified JSON property graph
│   └── seed_campus_graph.cyp       # Neo4j constraints & seed script
├── database/
│   └── neo4j_client.py             # Governed read-only Neo4j client + In-Memory fallback
├── security/
│   ├── ast_validator.py            # Cypher AST checker, deny-list, injection blocker
│   └── audit.py                    # Append-only JSONL audit logger
├── tools/
│   └── campus_tools.py             # 8 governed tools with Pydantic v2 validation
├── server/
│   ├── main.py                     # FastAPI REST API
│   └── mcp_server.py               # FastMCP stdio/SSE server
├── agent/
│   ├── prompts.py                  # Grounding prompts & function signatures
│   └── qwen_agent.py               # Local Qwen agent loop & heuristic router
├── tests/
│   ├── test_security_governance.py # Adversarial injection & policy tests (12 tests)
│   ├── test_tools.py               # Tool functional unit tests (9 tests)
│   └── test_api_server.py          # FastAPI REST integration tests (6 tests)
├── eval/
│   ├── benchmark_dataset.json      # 20 golden test queries + attack vectors
│   ├── run_eval.py                 # Automated benchmark evaluator
│   └── eval_report.json            # Final metrics report
└── logs/
    └── audit_telemetry.jsonl       # Immutable governance audit log
```
