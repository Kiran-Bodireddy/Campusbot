# SRMIST Campus Knowledge Assistant

A zero-trust governed local AI assistant and Neo4j property graph system for SRM Institute of Science and Technology (SRMIST). Powered by local Qwen 2.5 (via Ollama), Neo4j Property Graph, and an AST Security Validator.

---

## 1. System Architecture

The project is structured into three clean, decoupled layers:

```
courses/
├── DataPreparation/                   # Stage 1: Extraction & Ingestion Pipeline
│   ├── raw-sources/                   # Official Regulations 2021 curriculum & syllabus PDFs
│   ├── blueprints/                    # Property graph schema & entity definitions
│   ├── scrape-programs.py             # Web scraper for university admissions portal
│   ├── extract-courses.py             # PyMuPDF syllabus extractor (L-T-P-C, descriptions)
│   ├── extract-curriculum.py          # Semester 1-8 curriculum map extractor
│   ├── build-admissions.py            # Eligibility rules and fee structure builder
│   ├── build-unified-graph.py         # Assembles entities into Neo4j graph format
│   └── run-pipeline.py                # Master extraction pipeline runner
│
├── Datasets/                          # Stage 2: Authoritative Clean Datasets
│   ├── courses.json / courses.csv     # 264 verified courses (credits, L-T-P-C, departments)
│   ├── prerequisites.csv              # 19 prerequisite dependency links (DAG)
│   ├── curriculum.json                # Semester-by-semester course maps
│   ├── faculty.csv                    # 2,501 faculty members with designations & depts
│   ├── faculty-cabins.csv             # Cabin and staff room locations
│   ├── admissions.json                # Program cutoffs, entrance exams, and fees
│   ├── programs.json                  # Master academic program catalog
│   └── graph-blueprint.json           # Pre-assembled property graph for Neo4j
│
├── campus_knowledge_server/            # Stage 3: Runtime Backend Engine
│   ├── agent/                         # Qwen 2.5 ReAct reasoning, prompts, normalizer
│   ├── database/                      # Neo4j Bolt connection pool & Cypher traversal logic
│   ├── security/                      # Zero-Trust AST validator & SHA-256 audit ledger
│   ├── tools/                         # 11 parameterized campus tools
│   ├── server/                        # FastAPI REST API (port 8000)
│   └── tests/                         # 49 automated unit tests (100% pass)
│
├── assistant.html                     # Clean interactive web interface
├── seed.py                            # Populates local Neo4j from Datasets/
└── cli.py                             # Interactive terminal interface
```

---

## 2. Evaluation Scorecard (100% Across All Benchmarks)

Evaluated via `campus_knowledge_server/eval/run_eval.py` across 24 ground-truth queries and adversarial injection attempts:

| Evaluation Metric | Benchmark Target | Measured Result | Status |
| :--- | :---: | :---: | :---: |
| **Tool-Selection Accuracy** | >= 92.0% | **100.0%** | Passed |
| **Cypher Execution Accuracy** | 100.0% | **100.0%** | Passed |
| **Invalid-Query Rate** | < 2.0% | **0.0%** | Passed |
| **Grounded-Answer Score** | >= 90.0% | **100.0%** | Passed |
| **Access-Policy Violations Blocked** | 100.0% | **100.0%** | Passed |

*Automated Test Suite: **49 passed, 0 failures** (`python -m pytest -q`).*

---

## 3. The 11 Governed Campus Tools

All database access is constrained to least-privilege parameterized tools:

1. `check_admission_eligibility`: Evaluates program cutoffs, subject criteria (PCM/PCB), and entrance exams (SRMJEEE, NEET, CAT).
2. `lookup_faculty_profile`: Retrieves professor designation, cabin number, email, department, and research specialization.
3. `find_faculty_for_course`: Discovers professors assigned to instruct a specific course code (e.g., `21CSC206T`).
4. `verify_prerequisites`: Validates whether a student meets course prerequisites based on completed courses.
5. `get_prerequisite_tree`: Traverses curriculum prerequisite dependency DAGs up to 4 levels.
6. `lookup_course`: Retrieves credits, course descriptions, L-T-P-C breakdowns, and offering departments.
7. `find_available_rooms`: Identifies vacant classrooms and seminar halls across campus buildings (Tech Park, University Building, Bioengineering, etc.).
8. `find_room_schedule`: Fetches daily class timetables and occupancy for any campus room (e.g., `TP-101`).
9. `search_courses_semantic`: Discovers courses matching conceptual topics and descriptions.
10. `get_campus_statistics`: Provides high-level aggregate catalog statistics across programs, faculty, and rooms.
11. `get_semester_curriculum`: Retrieves official semester-by-semester subjects and credits for engineering branches under Regulations 2021.

---

## 4. Quickstart

### Master Launcher
Run `start_all.bat` or launch the components manually:

```powershell
# 1. Start local inference
ollama serve

# 2. Seed database (optional, pre-seeded)
python seed.py

# 3. Start FastAPI server
python -m uvicorn campus_knowledge_server.server.main:app --host 0.0.0.0 --port 8000

# 4. Open web interface
# Visit http://localhost:8000/ or open assistant.html
```

### Running Tests
```powershell
python -m pytest -q
```
