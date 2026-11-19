# SRMIST Campus Knowledge Assistant

A zero-trust governed local AI assistant and Neo4j property graph system for SRM Institute of Science and Technology (SRMIST). Powered by local Qwen 2.5 (via Ollama), Neo4j Community Property Graph with native vector indexes (`nomic-embed-text`), Pydantic schema validation, RBAC (`policy.yaml`), an AST Security Validator, and a SHA-256 tamper-evident audit ledger.

---

## 1. System Architecture

The project is structured into three decoupled layers:

```
courses/
├── DataPreparation/                   # Stage 1: Extraction & Ingestion Pipeline
│   ├── raw-sources/                   # Official Regulations 2021 curriculum & syllabus PDFs
│   ├── blueprints/                    # Property graph schema & entity definitions
│   ├── scrape-programs.py             # Scraper for university admissions portal
│   ├── extract-courses.py             # PyMuPDF syllabus extractor (L-T-P-C, descriptions)
│   ├── extract-curriculum.py          # Semester 1-8 curriculum map extractor
│   ├── build-admissions.py            # Eligibility rules and fee structure builder
│   ├── build-unified-graph.py         # Assembles entities into Neo4j graph format
│   └── run-pipeline.py                # Master extraction pipeline runner
│
├── Datasets/                          # Stage 2: Clean Datasets & Graph Blueprint
│   ├── courses.json / courses.csv     # 668 source courses (669 in Neo4j incl. 190 detailed Reg-2021 syllabi)
│   ├── prerequisites.csv              # 30 official Reg-2021 prerequisite edges (from 31 source rows; synthetic CSE201->CSE101 removed)
│   ├── curriculum.json                # 55 Reg-2021 programs & 3,498 semester course allocations
│   ├── faculty.csv                    # 2,367 scraped faculty directory records
│   ├── faculty-cabins.csv             # 2,501 faculty records with cabins, normalized departments & public directory phones
│   ├── admissions.json                # Program cutoffs, entrance exams, and fees (429 canonical admission programs)
│   ├── programs.json                  # Master academic program catalog
│   └── graph-blueprint.json           # Assembled property graph blueprint for Neo4j
│
├── campus_knowledge_server/           # Stage 3: Runtime Backend Engine
│   ├── agent/                         # Qwen 2.5 hybrid router, claim-level grounding guard, prompts, normalizer
│   ├── config/                        # Frozen policy.yaml (RBAC & redaction) + matching_config.yaml
│   ├── database/                      # Read-only Neo4j Bolt pool, Cypher queries & vector search
│   ├── eval/                          # Development benchmark dataset & runner-generated JSON reports
│   ├── security/                      # JWT auth, AST validator, sliding-window rate limiter, SHA-256 audit ledger
│   ├── tools/                         # 13 governed campus tools (12 exposed via MCP)
│   ├── server/                        # FastAPI REST/SSE API (port 8000) & FastMCP server
│   └── tests/                         # Automated test suite (pytest)
│
├── campus_assistant.html              # Interactive web interface
├── scripts/make_demo_tokens.py        # Offline CLI helper to mint demo student/admin JWTs
├── seed.py                            # Populates local Neo4j from Datasets/
└── cli.py                             # Interactive terminal interface
```

---

## 2. Data Provenance & Live Graph Inventory

| Graph Entity / Relationship | Live Neo4j Count | Provenance |
| :--- | ---: | :--- |
| `:Course` (`course_embeddings` ONLINE 100%) | 669 | Official SRMIST Regulations-2021 curriculum & syllabus PDFs (`common-courses-syllabus-2021.pdf`, 190 detailed syllabi) |
| `:FacultyMember` | 2,501 | Public SRMIST web directory (`faculty-cabins.csv`), normalized to 90 canonical departments |
| `:Program` (`program_embeddings` ONLINE 100%) | 437 | 429 canonical admissions programs (after merging duplicate MBBS `PROG-429` into `PROG-423`) + 8 Reg-2021 curriculum-only programs |
| `OFFERS_IN_SEMESTER` | 3,498 | Official SRMIST Regulations-2021 semester curriculum (`Datasets/curriculum.json`, 55 programs) |
| `REQUIRES_PREREQUISITE` | 30 | **The source has only 31 prerequisite rows** from Regulations-2021; 30 official course prerequisite links remain after removing the synthetic junk row `CSE201 -> CSE101` |
| `:Department` | 208 | 121 raw faculty strings + 87 academic/course department nodes |
| `:Building` (`building_embeddings` ONLINE 100%) | 20 | 9 named campus buildings in `graph-blueprint.json` (including `BEL = Basic Engineering Lab`) + 11 auxiliary building codes from faculty cabins/rooms |
| `:Room` & `OCCUPIES` sessions | 264 rooms / 1,336 sessions | **Project-defined / synthetic** (7 real timetable slots: `08:45–15:30`, no `16:30` slot) |

> **Synthetic & Project-Defined Data Notice:** Building names, room types, room capacities, and class timetables/occupancy schedules are **project-defined or synthetic** for scheduling demonstration. Course catalog records, semester curricula, the 31 source prerequisites (30 official links retained), admission requirements, and faculty directory entries are sourced from official SRMIST Regulations-2021 PDFs and public SRMIST web pages.

---

## 3. Evaluation Results — Development Set (Agent-Written)

Evaluated via `scripts/run_part_c_dev_benchmark.py` on the **90-question development set (agent-written)** (80 legitimate queries + 10 adversarial queries; `qwen2.5:1.5b` run on the 80 legitimate queries) against live read-only Neo4j Community `2026.10.2`:

| Mode (Development Set — Agent-Written) | Legit N | Tool Accuracy | Gold-Match Accuracy | Legit Invalid-Query Rate | Median Latency | Adversarial Blocked (Post-Patch) | Access-Policy Violations |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Hybrid (`qwen2.5:3b`, Router ON)** | 80 | 73/80 (91.25%) | 75/80 (93.75%) | 0/80 (0.0%) | **63.6 ms** *(routing plus tool time, excluding answer generation)* | 10/10 (100.0%) | 0 |
| **Router-Off (`qwen2.5:3b`)** | 80 | 70/80 (87.5%) | 64/80 (80.0%) | 9/80 (11.25%) | 12,312.6 ms *(LLM tool selection plus tool time, excluding answer generation)* | 10/10 (100.0%) | 0 |
| **Router-Off (`qwen2.5:1.5b`)** | 80 | 68/80 (85.0%) | 63/80 (78.75%) | 9/80 (11.25%) | 8,463.1 ms *(LLM tool selection plus tool time, excluding answer generation)* | N/A (80 legit only) | N/A |

- **Claim-Level Grounding Guard (80 legitimate queries, `qwen2.5:3b`):** 76/80 (95.0%) grounded before guard; 4 substitutions (2 LLM CPU timeouts, 2 real invented faculty names caught and substituted); 80/80 (100.0%) grounded after guard.
- **Adversarial audit history:** First pass pre-patch blocked 6/10 (60.0%); post-patch blocks **10/10 (100.0%)** with **0** access-policy violations and **0/20** false positives on natural queries containing `"select"`, `"from"`, `"delete"`, and `"create"`.

---

## 4. The 14 Governed Campus Tools (13 via MCP)

All database access is constrained to least-privilege, Pydantic-validated, parameterized tools. The FastAPI REST server (`campus_knowledge_server/server/main.py`) exposes **14 tools** under `/tools/*`; the FastMCP server (`campus_knowledge_server/server/mcp_server.py`) exposes **13 tools** (omitting the admin-only `run_governed_query`):

| # | Tool Name | Exposed via REST | Exposed via MCP | Purpose |
| :-: | :--- | :---: | :---: | :--- |
| 1 | `lookup_course` | Yes | Yes | Retrieves credits, L-T-P-C, category, clean summary, detailed Reg-2021 syllabus, prerequisites, and offering programs (returns all courses sharing a title). |
| 2 | `get_prerequisite_tree` | Yes | Yes | Traverses curriculum prerequisite dependency DAGs up to 4 levels deep. |
| 3 | `verify_prerequisites` | Yes | Yes | Validates whether a student meets a target course's prerequisites given completed courses. |
| 4 | `find_faculty_for_course` | Yes | Yes | Lists instructors assigned to a course code with faculty ID, normalized department, and cabin. |
| 5 | `lookup_faculty_profile` | Yes | Yes | Retrieves faculty designation, normalized department, cabin, email, specialization, official directory phone, and code-generated `phone_note`. |
| 6 | `find_room_schedule` | Yes | Yes | Fetches daily class timetables and occupancy for a campus room (e.g., `TP-101`). |
| 7 | `find_available_rooms` | Yes | Yes | Finds vacant classrooms/labs for a validated Neo4j building code, day, and slot (`1..7`, `08:45–15:30`); enforces role row caps (25 for students, uncapped for admin). |
| 8 | `search_courses_semantic` | Yes | Yes | Semantic vector search (`course_embeddings`) over course titles and syllabi. |
| 9 | `check_admission_eligibility` | Yes | Yes | Evaluates program cutoffs, subject criteria (PCM/PCB), entrance exams (SRMJEEE, NEET, CAT), and fees. |
| 10 | `get_campus_statistics` | Yes | Yes | Returns live aggregate Neo4j graph counts across programs, courses, faculty, rooms, buildings, and prerequisites. |
| 11 | `get_semester_curriculum` | Yes | Yes | Retrieves official Regulations-2021 semester-by-semester subjects and credits for a program. |
| 12 | `lookup_building` | Yes | Yes | Looks up campus building metadata, aliases (e.g., `BEL` / `Basic Engineering Lab`), and room counts from live Neo4j. |
| 13 | `find_course_schedule` | Yes | Yes | Retrieves weekly classroom allocations and timetable slots for a canonical course code. |
| 14 | `run_governed_query` | **Yes (Admin only)** | **No** | AST-validated read-only Cypher query execution restricted strictly to authenticated `admin` principals. |

---

## 5. Security, Access Control & Governance

### Routing Order & Chat Modes

1. **Default — Router-First (`routing_mode="hybrid"`):**
   1. **AST Security Guardrail** (`POLICY_VIOLATION`)
   2. **Write-Request Guard** (config-driven mutation verbs in `matching_config.yaml` → `WRITE_REQUEST_REFUSED`, zero LLM call)
   3. **Strict Small-Talk Template Guard** (pure greeting / thanks / "how are you" with no extra content words → config template reply, zero LLM call)
   4. **Conversation Memory Narrowing & Process 004 Follow-Up Projection**
   5. **Fast-Path & Normalized Heuristic Router** (including multi-name splitting on `and`, `&`, `,` up to `max_names_per_query`, executing `execute_tool` per name)
   6. **Qwen Tool-Selection Fallback** (only when heuristic routing returns nothing)
   7. **Clarification / No-Relevant-Match Reply** (including similarity floor `semantic_search.min_similarity_score` on `search_courses_semantic`)
2. **Optional — `LLM Intent (Experimental)` (`routing_mode="llm_intent"`):**
   - Runs Steps 1–4 first (so security blocks, write refusals, and pure small-talk templates never invoke Qwen), then asks local Qwen to classify intent before falling back to heuristic repair and clarification.
- FastAPI warms configured local Ollama models at startup with `keep_alive` from `matching_config.yaml`, and every response/stream final event reports per-stage timings (`routing_ms`, `tool_ms`, `generation_ms`) and semantic `relevance_score` in the Evidence Drawer.

### Anonymous Callers & JWT Roles
- **Anonymous callers are treated as least-privilege `student` principals** (`anonymous_student`, role `student`, 25-row output cap, private fields masked, admin/faculty tools forbidden).
- **No public HTTP endpoint issues `faculty` or `admin` tokens.** Interactive browser requests from `campus_assistant.html` send no token and execute under the `student` policy.
- For local demonstrations or admin audit inspection, mint short-lived tokens offline via CLI:
  ```powershell
  python scripts/make_demo_tokens.py
  ```
- **Rate limiting:** Sliding-window per-IP / per-session rate limit (20 requests / 60 seconds, configurable in `campus_knowledge_server/config/matching_config.yaml`) protects `/agent/ask`, `/ask`, `/agent/ask/stream`, `/ask/stream`, and `/tools/*`, returning HTTP `429` with `Retry-After` and `retry_after_seconds`.

### Official Directory Phone Policy (`policy.yaml`)
Official faculty office/department phone numbers from the SRMIST public web directory (`phone`) are visible to students and faculty because they are **public directory data**. Private fields (`personal_phone`, `mobile`, `contact_number`) remain masked by `policy.yaml`, and student responses retain the **25-row cap**. When a directory line is shared by multiple faculty (e.g., a university switchboard or department office line), `lookup_faculty_profile` attaches a code-generated `phone_note`:
- unique number: `None` (no note)
- shared by `N > 1` faculty: `"shared by N faculty (department/office line)"`
- empty / unlisted: `"not listed in the directory"`

### Neo4j Read-Only Serving Mode & Reload Toggle
In serving mode, Neo4j Community is locked read-only at the database server level in `<NEO4J_HOME>/conf/neo4j.conf`:
```ini
server.databases.default_to_read_only=true
```
Combined with `default_access_mode=READ_ACCESS` in `neo4j_client.py`, any write attempt (`CREATE`, `MERGE`, `SET`, `DELETE`) is rejected directly by the Neo4j server (`Neo.ClientError.General.WriteOnReadOnlyAccessDatabase`).

**Procedure to reload data or recompute vector embeddings (read-only reload toggle):**
1. Stop the running Neo4j Community instance.
2. In `<NEO4J_HOME>/conf/neo4j.conf`, temporarily toggle:
   ```ini
   server.databases.default_to_read_only=false
   ```
3. Start Neo4j and run the ingestion/embedding scripts (`seed.py`, `seed_vector_index.py`, `seed_program_vector_index.py`, `scripts/update_buildings_and_embeddings.py`, or `scripts/run_batch_a_data_and_graph.py`).
4. Verify all three vector indexes (`building_embeddings`, `course_embeddings`, `program_embeddings`) report `ONLINE` (`100.0%`) via `SHOW VECTOR INDEXES`.
5. Stop Neo4j and restore read-only serving mode:
   ```ini
   server.databases.default_to_read_only=true
   ```
6. Restart Neo4j for read-only serving and verify a `WRITE_ACCESS` `CREATE` probe raises `WriteOnReadOnlyAccessDatabase`.

---

## 6. Quickstart & Testing

```powershell
# 1. Start local Ollama inference
ollama serve

# 2. Start Neo4j Community (with server.databases.default_to_read_only=true for serving)
#    (Run python seed.py only when toggling read-only off for a reload)

# 3. Start FastAPI server
python -m uvicorn campus_knowledge_server.server.main:app --host 0.0.0.0 --port 8000

# 4. Open web interface
# Visit http://localhost:8000/

# 5. Run full automated test suite
python -m pytest campus_knowledge_server/tests -q
```
