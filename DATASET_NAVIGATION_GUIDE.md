# SRMIST Campus Knowledge Assistant — Master Dataset & File Navigation Guide

> **Purpose**: This guide is your single-page cheat sheet for project reviews, vivas, and examiner demonstrations. Use it to instantly locate any dataset, open the exact file, or recite ground-truth figures without fumbling.

---

## 1. Quick-Lookup Table ("If the Reviewer Asks...")

| If the Reviewer Asks... | Exact File to Open / Show | Quick Answer / Recite | Instant CLI Command |
| :--- | :--- | :--- | :--- |
| **"Where is the raw university syllabus?"** | [`campus_knowledge_server/data/courses/academic-curricula-2021.pdf`](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/academic-curricula-2021.pdf) | *"Volume 1 (246 pages) containing all 55 degree programmes from SRMIST Regulations 2021."* | `python show_dataset.py summary` |
| **"Show me the courses for CSE Semester 3"** | [`campus_knowledge_server/data/detailed_sem_audit.txt`](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/detailed_sem_audit.txt) (Lines 39-48) | *"8 courses, 23 credits: Transforms (21MAB201T), Design Thinking (21DCS201P), COA (21CSS201T), DSA (21CSC201J), OS (21CSC202J), APP (21CSC203P), Ethics (21LEM201T), Verbal Reasoning (21PDM201L)."* | `python show_dataset.py sem CSE 3` |
| **"Show me the courses for AI Semester 4"** | [`campus_knowledge_server/data/detailed_sem_audit.txt`](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/detailed_sem_audit.txt) (Lines 130-139) | *"8 courses, 23 credits: Applied Stats (21MAB304T), DAA (21CSC204J), AI Foundations (21AIS201J), Neural Networks & ML (21AIC202J), OS (21CSC202J)."* | `python show_dataset.py sem AI 4` |
| **"Where is the complete course catalog?"** | [`campus_knowledge_server/data/courses/courses_master.json`](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/courses_master.json) | *"668 official accredited SRMIST courses with L-T-P-C, credits, categories, and syllabus scope."* | `python show_dataset.py course 21CSC201J` |
| **"Where are the semester implementation plans?"** | [`campus_knowledge_server/data/courses/curricula_semester_master.json`](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/curricula_semester_master.json) | *"3,498 course-semester allocations across Semesters 1 through 8 for all 55 academic programmes."* | `python show_dataset.py sem MECH 1` |
| **"Where is the synthesized Neo4j property graph?"** | [`campus_knowledge_server/data/campus_graph_unified.json`](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/campus_graph_unified.json) | *"5.1 MB unified graph containing Course, Program, Faculty, Room, and Schedule nodes with all relationships."* | `python show_dataset.py graph` |
| **"Where is the Cypher seed script for Neo4j?"** | [`campus_knowledge_server/data/seed_campus_graph.cyp`](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/seed_campus_graph.cyp) | *"Declarative Cypher statements creating constraints, buildings, classrooms, courses, and OFFERS_IN_SEMESTER edges."* | `python seed_neo4j_live.py` |
| **"Where are admission eligibility criteria and fees?"** | [`campus_knowledge_server/data/courses/admission_eligibility_master.json`](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/admission_eligibility_master.json) | *"430 academic degree programmes with 10+2 PCM cutoffs, SRMJEEE exam requirements, annual fees, and campuses."* | `python show_dataset.py admission "computer science"` |
| **"Where are faculty members and cabin locations?"** | [`campus_knowledge_server/data/srmist_faculty_cabins.json`](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/srmist_faculty_cabins.json) | *"2,501 faculty members with designations, departments, college, and cabin room allocations across Tech Park, UB, BEL, etc."* | `python show_dataset.py faculty TP` |
| **"How do you prove the data is verified?"** | [`campus_knowledge_server/data/system_verification_summary.txt`](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/system_verification_summary.txt) | *"49/49 automated pytest tests passing (100%), SHA-256 hash-chained audit logs, and 7 end-to-end live intent tests passed."* | `python verify_full_system.py` |

---

## 2. The 5 Core Dataset Pillars

```
                                 SRMIST DATASET ARCHITECTURE
                                              |
    +-------------------+---------------------+--------------------+--------------------+
    |                   |                     |                    |                    |
[Pillar 1]          [Pillar 2]            [Pillar 3]           [Pillar 4]           [Pillar 5]
Official PDFs       Curricula Master      Admission Master     Faculty & Cabins     Property Graph
Volume 1 & 20       3,498 Allocations     430 Programmes       2,501 Faculty        campus_graph_
668 Courses         Semesters 1-8         Cutoffs & Fees       264 Classrooms       unified.json
```

### Pillar 1: Official University Curricula & Syllabi
- **Source File**: [academic-curricula-2021.pdf](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/academic-curricula-2021.pdf) (6.8 MB, 246 pages)
  - Official SRMIST Regulations 2021 Volume 1 containing all 55 degree programmes.
- **Syllabus File**: [common-courses-syllabus-2021.pdf](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/common-courses-syllabus-2021.pdf) (5.8 MB, 142 pages)
  - Official Volume 20 containing 251 common foundation subjects with unit-by-unit rationales, learning outcomes, and recommended textbooks.
- **Master Course Catalog**: [courses_master.json](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/courses_master.json) & [courses_master.csv](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/courses_master.csv)
  - **668 official distinct courses** with course code, title, credits, L-T-P-C, department, degree level, and category.

### Pillar 2: 8-Semester Implementation Plans
- **Master File**: [curricula_semester_master.json](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/curricula_semester_master.json) (2.3 MB)
  - Contains **3,498 course allocations** across Semesters 1 to 8 for all 55 programmes.
- **Audit Reports**:
  - [sem_breakdown_audit.txt](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/sem_breakdown_audit.txt): Summary counts for Semesters 1 through 8.
  - [detailed_sem_audit.txt](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/detailed_sem_audit.txt): 527-line departmental breakdown (CSE, AI, ECE, Mechanical, Biotechnology, Aerospace).

### Pillar 3: Academic Degrees & Admission Eligibility
- **Master Files**: [admission_eligibility_master.json](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/admission_eligibility_master.json) (463 KB) & [admission_eligibility_master.csv](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/admission_eligibility_master.csv) (330 KB)
  - **430 degree programmes** covering UG, PG, Ph.D., Diploma, and Fellowships.
  - Includes minimum education, mandatory 10+2 subjects (Physics, Chemistry, Maths/Biology), general percentage cutoff (e.g. 60%), reserved percentage cutoff (e.g. 50%), required entrance examination (SRMJEEE, NEET, GATE, TANCET), annual tuition fee in INR, and offering campuses.

### Pillar 4: Faculty & Classroom Infrastructure
- **Master Files**: [srmist_faculty_cabins.json](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/srmist_faculty_cabins.json) (1.5 MB) & [srmist_faculty_cabins.csv](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/srmist_faculty_cabins.csv) (888 KB)
  - **2,501 faculty members** with designations (Professor, Associate Professor, Assistant Professor), department, college, and assigned office cabins.
  - **264 rooms and labs** across 9 campus buildings (Tech Park, Tech Park 2, University Building, Bioengineering Block, Mechanical Engineering Block, Electrical Sciences Block, Management Block, Law School, Medical College).

### Pillar 5: Unified Neo4j Property Graph
- **Graph Dataset**: [campus_graph_unified.json](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/campus_graph_unified.json) (5.1 MB)
  - Integrates all entities into a property graph structure.
- **Cypher Seed Script**: [seed_campus_graph.cyp](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/seed_campus_graph.cyp) (54 KB)
  - Contains database schema constraints and node/relationship definitions.
- **Graph Relationship Schema**:
  - `(:Program)-[:OFFERS_IN_SEMESTER {semester, academic_year, credits, ltpc, category}]->(:Course)`
  - `(:Course)-[:REQUIRES_PREREQUISITE {condition, min_credits_required}]->(:Course)`
  - `(:FacultyMember)-[:TEACHES {section, semester}]->(:Course)`
  - `(:Course)-[:SCHEDULED_IN {day, timeslot}]->(:Room)`
  - `(:Room)-[:LOCATED_IN]->(:Building)`

---

## 3. Directory File Tree

```
c:\Users\heyit\Downloads\courses\
│
├── show_dataset.py                                  <-- Interactive zero-fumble dataset inspector CLI
├── seed_neo4j_live.py                               <-- One-click Live Neo4j database seeder
├── verify_full_system.py                            <-- Automated end-to-end verification script
├── cli.py                                           <-- Interactive terminal assistant CLI
├── start_all.bat                                    <-- Master one-click system launcher
├── start_cli.bat                                    <-- Quick CLI launcher
├── campus_assistant.html                            <-- Web UI with natural language chips & audit viewer
├── DATASET_NAVIGATION_GUIDE.md                      <-- THIS FILE (Your presentation cheat sheet)
├── PRESENTATION_MASTER_DECK.md                      <-- Complete slide scripts, diagrams, and Q&A
├── PROJECT_DEFENSE_AND_DEMO_GUIDE.md                <-- Defense questions & model answers
│
├── campus_knowledge_server/                         <-- Production Backend Package
│   ├── data/                                        <-- Master Datasets & Graph Store
│   │   ├── campus_graph_unified.json                <-- 5.1 MB Unified Property Graph
│   │   ├── seed_campus_graph.cyp                    <-- Cypher seed statements
│   │   ├── srmist_faculty_cabins.json / .csv        <-- 2,501 faculty members with cabins
│   │   ├── sem_breakdown_audit.txt                  <-- Sems 1-8 distribution summary
│   │   ├── detailed_sem_audit.txt                   <-- 527-line departmental course matrix
│   │   ├── system_verification_summary.txt          <-- Live verification proof
│   │   │
│   │   └── courses/                                 <-- Official SRMIST Course Assets
│   │       ├── academic-curricula-2021.pdf          <-- Official Vol 1 Curricula (246 pages)
│   │       ├── common-courses-syllabus-2021.pdf     <-- Official Vol 20 Syllabi (142 pages)
│   │       ├── courses_master.json / .csv           <-- 668 official accredited courses
│   │       ├── curricula_semester_master.json       <-- 3,498 course allocations (Sems 1-8)
│   │       ├── admission_eligibility_master.json    <-- 430 programmes with eligibility & fees
│   │       └── srmist_programs_master.json / .csv   <-- Program degree offerings
│   │
│   ├── agent/                                       <-- Qwen Agent, Prompts, Fuzzy Normalizers
│   ├── database/                                    <-- Neo4j Client (hybrid live + in-memory)
│   ├── security/                                    <-- Cypher AST Sanitizer & Hash Chain Audit
│   ├── server/                                      <-- FastAPI and MCP endpoints
│   ├── tools/                                       <-- Governed Campus Knowledge Tools
│   └── tests/                                       <-- Pytest test suite (49 automated tests)
│
└── chroma_srm_db/                                   <-- Vector index for dense semantic search
```

---

## 4. Key Numbers to Recite

Memorize these 7 figures for your review:

1. **668 Official Courses**: Cleanly merged from Volume 1 core departmental courses and Volume 20 foundational syllabi.
2. **3,498 Semester Allocations**: Full coverage across **Semesters 1 through 8** for **all 55 academic degree programmes**.
3. **55 Degree Programmes**: 47 B.Tech specializations + 8 Integrated M.Tech programmes.
4. **430 Admission Programmes**: Complete entry requirements, 10+2 cutoffs, entrance exams, and fee structures.
5. **2,501 Faculty Profiles**: Ingested with designations, departments, colleges, and cabin room allocations.
6. **264 Classrooms & Labs**: Spanning 9 major campus building complexes at Kattankulathur.
7. **49 / 49 Tests Passing (100%)**: Zero regressions across unit tests, AST security guards, fuzzy normalizers, and API endpoints.

---

## 5. Instant Demonstration Commands

Open PowerShell in the project directory and run any of these:

```powershell
# 1. Show the dataset master status table
python show_dataset.py summary

# 2. Show B.Tech CSE Semester 3 subjects on screen
python show_dataset.py sem CSE 3

# 3. Show B.Tech AI Semester 4 subjects on screen
python show_dataset.py sem AI 4

# 4. Lookup a specific course (e.g. Data Structures 21CSC201J)
python show_dataset.py course 21CSC201J

# 5. Check admission eligibility and fees
python show_dataset.py admission "computer science"

# 6. View Neo4j Graph metrics
python show_dataset.py graph

# 7. Run full system verification (health, audit hash chain, 7 live intents)
python verify_full_system.py
```

