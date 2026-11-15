# 🏛️ SRMIST Campus Knowledge Assistant & Master Catalog

> An enterprise-grade, zero-trust governed AI assistant and knowledge graph for SRM Institute of Science and Technology (SRMIST). Powered by **Local Qwen 2.5 (Ollama)**, **Neo4j Property Graph**, **ChromaDB Vector Store**, and **AST Security Governance**.

---

## 🌟 Executive Summary

This repository delivers an end-to-end autonomous campus knowledge platform:
1. **Master Program & Curriculum Catalog**: 429 degree programs, 1,284 curriculum courses, and 2,501 verified faculty members across 6 campuses (Kattankulathur, Ramapuram, Vadapalani, Delhi-NCR, Tiruchirappalli, Baburayanpettai).
2. **Governed Agent & Least-Privilege Architecture**: Local Qwen 2.5 interacts exclusively through parameterized tools with zero direct Cypher database write access.
3. **AST Security Guardrail**: Intercepts prompt injections, destructive clauses (`DROP`, `DELETE`, `MERGE`, `ALTER`), unauthorized procedures (`CALL apoc.system.*`), and statement chaining (` ; `).
4. **Dual Response Modes**: 
   - **Instant Governed Mode (~20ms)**: Deterministic, zero-hallucination, formatted fact retrieval.
   - **Qwen Generative Mode**: Natural language synthesis with strict ground-truth attribution citations (`[Course: ...]`, `[Faculty: ...]`, `[Room: ...]`).

---

## 📊 Evaluation Scorecard (100% Across All Benchmarks)

Evaluated via [`campus_knowledge_server/eval/run_eval.py`](campus_knowledge_server/eval/run_eval.py) across 24 ground-truth queries and adversarial injection attempts:

| Evaluation Metric | Benchmark Target | Measured Result | Status |
| :--- | :---: | :---: | :---: |
| **Tool-Selection Accuracy** | $\ge 92.0\%$ | **100.0%** | Passed |
| **Cypher Execution Accuracy** | $100.0\%$ | **100.0%** | Passed |
| **Invalid-Query Rate** | $< 2.0\%$ | **0.0%** | Passed |
| **Grounded-Answer Score** | $\ge 90.0\%$ | **100.0%** | Passed |
| **Access-Policy Violations Blocked** | $100.0\%$ | **100.0%** | Passed |

*Unit Test Suite: **42 passed, 0 failures** across API, security governance, fuzzy resilience, and tools.*

---

## 🛠️ The 9 Authorized Governed Tools

| # | Tool Name | Description & Parameters |
| :-: | :--- | :--- |
| **1** | `check_admission_eligibility` | Evaluates cutoffs, subject criteria (PCM/PCB), and entrance exams (SRMJEEE, NEET, etc.) for any degree. |
| **2** | `lookup_faculty_profile` | Retrieves professor designation, cabin number, email, department, and research specialization. |
| **3** | `find_faculty_for_course` | Discovers professors actively assigned to instruct a specific course code (e.g. `CSE101`, `AIML201`). |
| **4** | `verify_prerequisites` | Validates whether a student meets course prerequisites based on completed courses. |
| **5** | `get_prerequisite_tree` | Recursively traverses curriculum prerequisites up to $N$ dependency levels. |
| **6** | `lookup_course` | Retrieves credits, course descriptions, departments, and offering college for course codes. |
| **7** | `find_available_rooms` | Identifies vacant classrooms and seminar halls across campus buildings (TP, UB, BEL, etc.). |
| **8** | `find_room_schedule` | Fetches daily class timetables and occupancy for any campus room (e.g. `TP-101`, `UB-202`). |
| **9** | `search_courses_semantic` | ChromaDB vector search discovering courses matching conceptual queries (e.g. "deep learning", "cyber forensics"). |

---

## 🚀 Quickstart & How to Run

### Option A: One-Click Master Launcher (Recommended)
Double-click [`start_all.bat`](start_all.bat). This script automatically:
1. Starts Ollama in the background (if not already running).
2. Starts the FastAPI server on port 8000.
3. Opens the Web UI in your browser (`http://localhost:8000/`).
4. Launches the interactive Governed Terminal CLI.

### Option B: Terminal CLI
Double-click [`start_cli.bat`](start_cli.bat) or execute:
```bash
python cli.py
```
- Type any question naturally: `eligibility for btech`, `who is Shivam`, `Dr. Priya S`, `vacant rooms in TP`.
- Type `mode` to switch between Instant Governed Mode (<30ms) and Qwen Generative Mode.
- Type `tools` to list tools, `status` for live connections, or `audit` for security logs.

### Option C: FastAPI REST API & Web UI
```bash
uvicorn campus_knowledge_server.server.main:app --host 0.0.0.0 --port 8000
```
- **Web UI**: Navigate to [http://localhost:8000/](http://localhost:8000/)
- **Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check**: [http://localhost:8000/health](http://localhost:8000/health)
- **Security Audit Logs**: [http://localhost:8000/audit/logs](http://localhost:8000/audit/logs)

### Option D: Run Automated Tests & Evaluations
```bash
# Run 42 unit and security tests
python -m pytest campus_knowledge_server/tests -v

# Run the 24-query benchmark evaluation scorecard
python campus_knowledge_server/eval/run_eval.py
```

---

## 📁 Repository Structure

```text
courses/
├── start_all.bat                     # Master one-click launcher (Ollama + FastAPI + Browser + CLI)
├── start_cli.bat                     # Dedicated terminal CLI launcher
├── cli.py                            # Interactive Terminal CLI with dual-mode toggle
├── campus_assistant.html             # Full-featured Glassmorphic Web Assistant UI
├── index.html                        # Program explorer and static search portal
├── scrape_srmist.py                  # Web scraper for official SRMIST curriculum & offerings
├── srmist_programs_master.csv        # Master academic programs dataset (429 programs)
├── srmist_programs_master.xlsx       # Multi-tab program master spreadsheet
│
└── campus_knowledge_server/
    ├── agent/
    │   ├── normalizer.py             # Fuzzy typo correction, degree & building acronym expansion
    │   ├── prompts.py                # Grounding system prompt & tool definitions
    │   └── qwen_agent.py             # Governed agent loop, 8ms fuzzy router & zero-hallucination guardrail
    ├── database/
    │   └── neo4j_client.py           # Neo4j property graph client with in-memory graph fallback
    ├── security/
    │   ├── ast_validator.py          # Zero-trust Cypher AST sanitizer & injection blocker
    │   └── audit.py                  # Append-only JSONL security telemetry logger
    ├── tools/
    │   └── campus_tools.py           # 9 Pydantic-governed campus knowledge tools
    ├── server/
    │   ├── main.py                   # FastAPI REST API serving web UI and /agent/ask
    │   └── mcp_server.py             # FastMCP server for Claude Desktop / Cursor / Antigravity
    ├── eval/
    │   ├── benchmark_dataset.json    # 24 ground-truth queries + adversarial attacks
    │   ├── eval_report.json          # Machine-readable evaluation report
    │   └── run_eval.py               # Automated scorecard evaluation runner
    └── tests/
        ├── test_security_governance.py # 12 adversarial injection tests
        ├── test_fuzzy_resilience.py  # 15 typo tolerance & normalization tests
        ├── test_tools.py             # 9 tool functional tests
        └── test_api_server.py        # 6 FastAPI REST integration tests
```

---

## 🛡️ Security Governance Architecture

```text
User Question / API Request
           │
           ▼
┌──────────────────────────────────────────────┐
│  AST Security Validator & Input Sanitizer    │
│  - Blocks DELETE, DROP, SET, CREATE, MERGE   │
│  - Blocks APOC system & RCE procedures       │
│  - Prevents statement chaining (';')         │
│  - Enforces mandatory LIMIT 50 bounds        │
└──────────────────────┬───────────────────────┘
                       │ Safe
                       ▼
┌──────────────────────────────────────────────┐
│  Hybrid Robust Router                        │
│  - Sub-ms exact code matching (CSE101, TP101)│
│  - 8ms Normalized Fuzzy Typo Router          │
│  - Qwen 2.5 JSON-mode fallback for complex   │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│  Authorized Least-Privilege Tools (Pydantic) │
│  - Neo4j Knowledge Graph (2,501 Faculty)     │
│  - ChromaDB Vector Store (Curriculum Embed)  │
│  - Admission Eligibility Rule Engine         │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│  Grounding & Zero-Hallucination Guardrail    │
│  - Returns grounded citations                │
│  - Rejects empty DB results without LLM hall.│
│  - Multi-match profile disambiguation        │
└──────────────────────────────────────────────┘
```

---

## 📄 License & Provenance
Developed for academic, research, and campus administrative automation at SRM Institute of Science and Technology. All data indexed from verified SRMIST catalogs, faculty directories, and curriculum handbooks.
