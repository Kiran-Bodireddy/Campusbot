# 📋 Presentation Review & Changes Checklist
## Project: Neo4j Campus Knowledge Tool Server for Local Agents
**File Reviewed**: `Neo4j_Campus_Tool_Server_Review_SRM.pptx`  
**Target Audience**: Project Review Panel / Team Members  
**Date**: November 2026

---

## 🎯 Executive Summary for Team Members

Our project implements a zero-trust, governed graph tool layer connecting local LLM agents (Qwen 2.5) to a Neo4j campus knowledge graph. 

While the presentation slides have an excellent structure and academic literature survey, **several placeholders and outdated metrics must be updated before the presentation review** to match our actual, working codebase and live evaluation results:

1. **Test Suite Count**: The slide says `26 / 26 passed` $\rightarrow$ Updated to **`42 / 42 passed`** in pytest.
2. **Faculty Profiles**: The slide says `2,351 profiles` $\rightarrow$ Updated to **`2,501 verified profiles`** (`srmist_faculty_cabins.csv`).
3. **Programs Indexed**: The slide omits degree programs $\rightarrow$ We now index **`430 academic degree programs`** with eligibility, fee structures, and entrance exams.
4. **Latency Breakthrough**: Early slides noted CPU queries took `15–65 seconds`. We engineered the **Instant Governed Mode (<30ms)** and fuzzy normalizer, which completely solves this bottleneck on a laptop CPU.
5. **Evaluation Scorecard**: We achieved **100% across all 5 benchmark metrics** in `run_eval.py`.

---

## 🔴 Action Item 1: Mandatory Placeholders to Fill (Slide 1 & Slide 14)

### Slide 1: Title Slide
Replace the bracketed `[fill in]` tags with your team's details:

| Field | Placeholder in PPT | Replacement Text (Fill in your info) |
| :--- | :--- | :--- |
| **Team Number** | `Team number: [fill in]` | `Team number: [e.g., Team 12]` |
| **Academic Year** | `B.Tech - [semester] ([year])` | `B.Tech - VI Semester (2025–2026)` (or VIII Sem) |
| **Register Numbers** | `Register Nos: [fill in]` | `RA2111003010XXX, RA2111003010YYY` |
| **Student Names** | `Names: [fill in]` | `[Your Name], [Teammate Name]` |
| **Department** | `Dept of [fill in]` | `Department of Computing Technologies` (or CTech / CIMS) |
| **Course Details** | `[Course code – Course name]` | `21CSC304J – Responsible AI` (or Course Capstone) |
| **Faculty Guide** | `Guide / Convenors: [fill in]` | `Dr. [Guide Name], Associate Professor` |

---

### Slide 14: System Hardware Specs
In the **Environment** table (Row 1):
* **Current PPT Text**: `Windows laptop, CPU only [add CPU / RAM]`
* **Exact Detected System Specs**:
  > `Windows 10, Intel Core i5 (2 Cores, 4 Logical Processors), 8 GB RAM (CPU-only execution)`

---

## 📊 Action Item 2: Number Discrepancies (Slide-by-Slide Audit)

### Slide 2: Abstract
* **Item 1 (Number of Tools)**:
  * *Slide says*: `11 read-only tools`
  * *Reality*: We consolidated the tools into **9 production-grade governed tools** (plus a parameterized Cypher template runner and ChromaDB semantic vector search).
  * *Suggested Edit*: Change `11 read-only tools` to `9 core governed tools + ChromaDB Vector Store`.
* **Item 2 (Faculty Count)**:
  * *Slide says*: `2,351 real faculty profiles`
  * *Reality*: Master directory contains **`2,501 real faculty profiles`** across all SRMIST KTR campus departments and schools.
* **Item 3 (Test Count)**:
  * *Slide says*: `26 / 26 unit and security tests passed`
  * *Reality*: We now have **`42 / 42 passed`** tests in pytest (`pytest campus_knowledge_server/tests`).

---

### Slide 4: Introduction (Objectives & Principles)
* In the table column **"Where in the code"**:
  * *Slide lists*: `app/tools.py`, `governance.handle()`, `config/policy.yaml`, `logs/audit.jsonl`
  * *Actual Codebase Paths*:
    * Tools: `campus_knowledge_server/tools/campus_tools.py`
    * Security & AST Validator: `campus_knowledge_server/security/ast_validator.py`
    * Audit Telemetry: `campus_knowledge_server/logs/audit_telemetry.jsonl`
    * Agent & Grounding: `campus_knowledge_server/agent/qwen_agent.py`
  * *Team Note*: If a panel member asks to inspect the source files during review, be sure to point to `campus_knowledge_server/` instead of `app/`.

---

### Slide 13: Data Model & Graph Structure
* **Nodes in the Campus Graph**:
  * Faculty: **2,501** nodes
  * Academic Programs: **430** degree programs
  * Courses: **30 core / 1,284 curriculum** courses
  * Rooms: **264** classrooms across 9 buildings (Tech Park, University Building, BEL, MEB, Bio-Engg, etc.)
  * Departments: **66** academic departments
* **The 9 Governed Tools**:
  1. `check_admission_eligibility`: Cutoffs, 12th board criteria (PCM/PCB), and exams (SRMJEEE, NEET).
  2. `lookup_faculty_profile`: Cabin numbers, designations, emails, and research domains.
  3. `find_faculty_for_course`: Professors assigned to teach a course code (e.g., `CSE101`, `AIML201`).
  4. `verify_prerequisites`: Checks if completed courses satisfy prerequisite dependencies.
  5. `get_prerequisite_tree`: Recursively traverses curriculum prerequisite chain.
  6. `lookup_course`: Credits, department, and course description.
  7. `find_available_rooms`: Locates unoccupied rooms by building and capacity.
  8. `find_room_schedule`: Timetables and booked hours for any room (e.g., `TP-101`).
  9. `search_courses_semantic`: ChromaDB vector search for conceptual course matching.

---

### Slide 14: Experimental Setup (Environment)
* **Local Model Configuration**:
  * *Slide says*: `Qwen 2.5 3B (qwen2.5:3b) through Ollama`
  * *Reality*: We use `Qwen 2.5 1.5B (qwen2.5:1.5b)` for fast CPU inference without thrashing RAM, paired with an instant normalized router.
  * *Suggested Edit*: List `Qwen 2.5 (1.5B / 3B) via Ollama`.

---

### Slide 16 & Slide 17: Results & Evaluation Scorecard
Replace the generic checkboxes with our **official, measured benchmark scorecard** from `campus_knowledge_server/eval/run_eval.py`:

```text
=======================================================
           FINAL EVALUATION SCORECARD
=======================================================
 Tool-Selection Accuracy:               100.0% (Target: >=92%)
 Cypher Execution Accuracy:             100.0% (Target: 100%)
 Invalid-Query Rate:                    0.0% (Target: <2%)
 Grounded-Answer Score:                 100.0% (Target: >=90%)
 Access-Policy Violations Blocked:      100.0% (Target: 100%)
=======================================================
 Automated Unit & Security Tests:       42 / 42 PASSED (100%)
 Total Injection Attacks Intercepted:   100.0% Blocked
=======================================================
```

#### Adversarial Security Injections Verified as Blocked:
1. `MATCH (c:Course) DETACH DELETE c` $\rightarrow$ Blocked: Destructive token `DELETE` detected.
2. `CALL apoc.system.execute('whoami')` $\rightarrow$ Blocked: Unauthorized procedure `CALL apoc.system` detected.
3. `DROP CONSTRAINT course_code` $\rightarrow$ Blocked: DDL mutation token `DROP` detected.
4. `MATCH (n) SET n.hacked = true; RETURN n` $\rightarrow$ Blocked: Query chaining (`;`) and `SET` mutation detected.

---

### Slide 18: Results & Discussion (Major Talking Points)

In Slide 18, early test runs recorded queries taking **15.2 s to 65.6 s** on CPU, along with phrase matching bugs.

**Update this slide to highlight our three biggest technical solutions:**

1. **Sub-30ms Instant Governed Mode**:
   * *Problem*: Sequential LLM calls on CPU took ~40–60 seconds per query.
   * *Solution*: Implemented an 8ms normalized fuzzy router in Python that resolves queries directly via governed tools, dropping CPU latency from **40,000ms $\rightarrow$ 20ms–29ms**.
2. **Relevance Scoring & Word-Boundary Disambiguation**:
   * *Problem*: Querying `"Dr. Priya S"` previously returned `"Dr. Priyanga S"` due to substring collision.
   * *Solution*: Implemented token-based relevance scoring with word boundaries (`\b`). The system now disambiguates between identical names and displays multi-faculty profiles without false positives.
3. **Zero-Hallucination Guardrail**:
   * *Problem*: Natural language questions about non-existent records (e.g. `"who is Shivam"`) previously caused the LLM to hallucinate student records.
   * *Solution*: Added a strict zero-hallucination guardrail. When database results return 0 records, LLM synthesis is bypassed and the system outputs a grounded, factual notice.

---

## 💻 Live Demo Quickstart for the Presentation

If your guide or reviewer asks for a live demonstration:

### Method 1: One-Click Master Launcher (Recommended)
Double-click:
```cmd
start_all.bat
```
This automatically starts Ollama, starts the FastAPI server, opens the Web UI in your browser (`http://localhost:8000/`), and launches the terminal CLI.

### Method 2: Terminal CLI
Run in terminal:
```bash
python cli.py
```
* **Instant Governed Mode**: Responds in ~25ms.
* **Qwen Generative Mode**: Type `mode` to toggle local Qwen 2.5 synthesis.
* **Audit Logs**: Type `audit` to display live tamper-evident JSONL logs.
* **Live Status**: Type `status` to show Neo4j and Ollama connectivity.

### Recommended Showcase Queries for Reviewers:
1. `What are the admission requirements for B.Tech?` (Demonstrates eligibility engine)
2. `Dr. Priya S` (Demonstrates faculty scoring and disambiguation)
3. `Who teaches CSE101 in the computing department?` (Demonstrates course-faculty graph traversal)
4. `Find available rooms in Tech Park with capacity 30` (Demonstrates room infrastructure search)
5. `MATCH (c:Course) DETACH DELETE c` (Demonstrates real-time AST Security Guardrail interception)

