# Codebase Navigation & Quick Explanation Guide

Click any file link below to jump directly into the code. Every file has a simple, 1-sentence explanation of what it does and exactly what to say if an examiner asks you about it.

---

## The Whole Project in 30 Seconds

```
[User asks question in campus_assistant.html]
                  │
                  ▼
[FastAPI server receives it in main.py]
                  │
                  ▼
[qwen_agent.py picks the right tool & checks policy.yaml]
                  │
                  ▼
[campus_tools.py runs Cypher query via neo4j_client.py]
                  │
                  ▼
[audit.py logs the query with SHA-256 hash in audit_telemetry.jsonl]
                  │
                  ▼
[Grounded, verified answer is returned to the user]
```

---

## 1. The Dataset Files (Where the data comes from)

### 📄 [academic-curricula-2021.pdf](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/academic-curricula-2021.pdf)
* **What it is:** The official 246-page SRMIST Regulations 2021 Volume 1 syllabus book.
* **What it does:** Contains the official degree structures and semester subjects for 55 engineering branches.
* **Say this to examiner:** *"This is the official university regulation PDF from which we extracted all B.Tech course structures."*

### 📄 [common-courses-syllabus-2021.pdf](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/common-courses-syllabus-2021.pdf)
* **What it is:** The official 251-course common syllabus book (Volume 20).
* **What it does:** Contains detailed course outlines, credits, and syllabus topics for all shared subjects.
* **Say this to examiner:** *"This is the official common syllabus PDF used to extract exact course names and credit hours."*

### 📄 [extract_all_semester_curricula.py](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/extract_all_semester_curricula.py)
* **What it is:** The Python script that reads the PDFs and extracts data into JSON.
* **What it does:** Uses `pdfplumber` and regex to automatically parse tables across all 246 pages into structured data.
* **Say this to examiner:** *"This script automates PDF parsing so we don't have to manually copy-paste course tables."*

### 📊 [courses_master.json](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/courses_master.json)
* **What it is:** The master catalog of **668 accredited courses**.
* **What it does:** Stores course codes (e.g. `21CSC206T`), full titles, credits, and departments.
* **Say this to examiner:** *"This is our master course database containing 668 verified courses."*

### 📊 [curricula_semester_master.json](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/curricula_semester_master.json)
* **What it is:** The master list of **3,498 semester allocations**.
* **What it does:** Maps which courses belong to which branch and which semester (Semester 1 to 8).
* **Say this to examiner:** *"This file holds the 3,498 curriculum mappings that power the `OFFERS_IN_SEMESTER` relationships in Neo4j."*

### 📊 [admission_eligibility_master.json](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/courses/admission_eligibility_master.json)
* **What it is:** Admission rules, cutoffs, and fees for **430 degree programs**.
* **What it does:** Stores 12th standard cutoffs, required entrance exams (SRMJEEE, NEET, CAT), and tuition fees.
* **Say this to examiner:** *"This file contains official admission criteria and fees across all 430 degree programs."*

### 📊 [srmist_faculty_cabins.json](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/srmist_faculty_cabins.json)
* **What it is:** Directory of **2,501 faculty members**.
* **What it does:** Stores professor names, departments, cabin room numbers (e.g. TP-603), and emails.
* **Say this to examiner:** *"This powers staff lookups so students can locate professors and their cabins in Tech Park or UB."*

### 📊 [campus_graph_unified.json](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/data/campus_graph_unified.json)
* **What it is:** The complete combined graph file ready to be loaded into Neo4j.
* **What it does:** Merges courses, programs, faculty, 264 classrooms, and 500 timetable sessions into one graph blueprint.
* **Say this to examiner:** *"This is the complete export of all graph nodes and edges used to seed Neo4j."*

---

## 2. The Neo4j Database Files (How the graph works)

### 🔌 [neo4j_client.py](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/database/neo4j_client.py)
* **What it is:** The Python file that connects directly to the Neo4j database on port `7687`.
* **What it does:** 
  1. Opens the connection to Neo4j using the Bolt protocol.
  2. Runs Cypher queries and returns the results as Python dictionaries.
  3. Has the `seed_live_neo4j()` function that loads all 668 courses and 3,498 edges into both `neo4j` and `rai` databases.
* **Say this to examiner:** *"This is our database driver. It handles the live Bolt connection to Neo4j and executes all Cypher queries."*

### 🛡️ [policy.yaml](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/config/policy.yaml)
* **What it is:** The security rules file (Role-Based Access Control).
* **What it does:** Defines what `student`, `faculty`, and `admin` are allowed to see. For students, it blocks database mutations, enforces a 50-row limit, and hides private phone numbers.
* **Say this to examiner:** *"This is our zero-trust security policy that ensures students can only run read-only queries with strict privacy limits."*

---

## 3. The FastAPI Server & Backend Tools (The engine)

### 🚀 [main.py](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/server/main.py)
* **What it is:** The main backend application file running on FastAPI (port `8000`).
* **What it does:** 
  - Listens for queries at `/agent/ask`.
  - Serves audit logs at `/audit/logs`.
  - Runs live hash verification at `/audit/verify`.
  - Serves the frontend web page when you open `http://localhost:8000/`.
* **Say this to examiner:** *"This is the FastAPI backend that connects the web portal to our agent and tools."*

### 🛠️ [campus_tools.py](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/tools/campus_tools.py)
* **What it is:** The 7 official tools that run the actual Cypher queries against Neo4j.
* **What it does:** Contains the code for:
  1. `get_semester_curriculum` &rarr; Gets subjects for a branch and semester.
  2. `lookup_course` &rarr; Looks up course details and syllabus.
  3. `get_prerequisite_tree` & `verify_prerequisites` &rarr; Checks prerequisite requirements.
  4. `check_admission_eligibility` &rarr; Checks 12th marks and fees.
  5. `lookup_faculty_profile` &rarr; Finds professor cabin and email.
  6. `find_available_rooms` &rarr; Finds vacant classrooms in Tech Park or UB.
  7. `get_campus_statistics` &rarr; Returns overall campus totals.
* **Say this to examiner:** *"These are the 7 governed tools. Instead of letting users write raw Cypher, the server only executes these 7 predefined, safe functions."*

### 🤖 [qwen_agent.py](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/agent/qwen_agent.py)
* **What it is:** The agent brain.
* **What it does:** 
  1. Reads what the user typed.
  2. Automatically picks which of the 7 tools to call in under 8 milliseconds.
  3. Runs the tool, gets the real records from Neo4j, and writes a grounded answer.
  4. Enforces zero-hallucination: if the database has 0 records, it never invents fake data.
* **Say this to examiner:** *"This is the governed agent. It routes the user's question to the correct tool and ensures zero hallucination by sticking strictly to database records."*

### 🔒 [ast_validator.py](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/security/ast_validator.py)
* **What it is:** The Cypher injection firewall.
* **What it does:** Inspects incoming queries before they reach Neo4j. If someone tries to inject `DROP TABLE`, `DELETE`, or `CREATE`, it blocks the query immediately.
* **Say this to examiner:** *"This is our AST security firewall that blocks injection attacks and ensures the database stays 100% read-only."*

### 🔗 [audit.py](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/security/audit.py)
* **What it is:** The tamper-evident cryptographic logger.
* **What it does:** Every time anyone asks a question, this file calculates a SHA-256 hash connecting to the previous entry (like a mini-blockchain). If anyone edits the log file, the chain breaks.
* **Say this to examiner:** *"This implements cryptographic SHA-256 hash chaining so our audit logs are tamper-evident and verifiable."*

### 📜 [audit_telemetry.jsonl](file:///c:/Users/heyit/Downloads/courses/campus_knowledge_server/logs/audit_telemetry.jsonl)
* **What it is:** The log file storing over **1,350+ past queries**.
* **What it does:** Stores timestamp, user role, tool executed, execution latency, and the SHA-256 hash for every request.
* **Say this to examiner:** *"This is the append-only ledger where all 1,350+ query events are recorded with sub-5ms latencies."*

---

## 4. What to Show the Reviewer (Frontends & Visuals)

### 🌐 [campus_assistant.html](file:///c:/Users/heyit/Downloads/courses/campus_assistant.html)
* **What it is:** The web application you open at `http://localhost:8000/`.
* **What it has:**
  - Fast search bar with real-time suggestion chips.
  - **`[● Architecture & Logs]`** button (top right) that opens the full live telemetry dashboard.
  - **`[View architecture trace]`** button on every answer showing the 6-step pipeline and the exact Cypher query.
* **Say this to examiner:** *"This is our offline portal. It runs entirely on localhost and features real-time architecture telemetry and Cypher traces."*

### 💻 [show_dataset.py](file:///c:/Users/heyit/Downloads/courses/show_dataset.py)
* **What it is:** The terminal CLI tool for instant demonstrations.
* **Quick commands you can run in terminal:**
  ```bash
  python show_dataset.py summary         # Shows all files & record counts
  python show_dataset.py sem CSE 3       # Shows CSE Semester 3 subjects
  python show_dataset.py course 21CSC206T# Shows course syllabus
  python show_dataset.py admission cse   # Shows B.Tech CSE eligibility & fee
  python show_dataset.py graph           # Shows Neo4j node and relationship count
  python show_dataset.py logs            # Verifies all 1,350 SHA-256 hashes live
  ```
* **Say this to examiner:** *"This CLI allows instant terminal inspection of our dataset and database without fumbling through folders."*

### 📋 [DATASET_NAVIGATION_GUIDE.md](file:///c:/Users/heyit/Downloads/courses/DATASET_NAVIGATION_GUIDE.md)
* **What it is:** A 1-page cheat sheet with answers to questions the reviewer might ask.
* **Say this to examiner:** *"This is our master navigation reference containing the complete breakdown of every file, campus, and curriculum."*

### 📐 [ARCHITECTURE_DIAGRAM.md](file:///c:/Users/heyit/Downloads/courses/ARCHITECTURE_DIAGRAM.md)
* **What it is:** The complete Mermaid architecture diagram.
* **How to use it:** Copy the code and paste it into [Excalidraw](https://excalidraw.com) (More Tools &rarr; Mermaid to Excalidraw) to get a hand-drawn whiteboard diagram.
* **Say this to examiner:** *"This is the formal 6-tier architecture specification for the entire system."*

### 📽️ [Neo4j_Campus_Tool_Server_Review_SRM.pptx](file:///c:/Users/heyit/Downloads/courses/Neo4j_Campus_Tool_Server_Review_SRM.pptx)
* **What it is:** The 19-slide presentation deck.
* **Note:** Slide 15 has been updated to cite official Regulations 2021 PDF extraction (668 courses, 3,498 allocations).

### 📐 [ARCHITECTURE_DIAGRAM.md](file:///c:/Users/heyit/Downloads/courses/ARCHITECTURE_DIAGRAM.md)
* **What it is:** The complete Mermaid architecture diagram.
* **How to use it:** Copy the code and paste it into [Excalidraw](https://excalidraw.com) (More Tools &rarr; Mermaid to Excalidraw) to get a hand-drawn whiteboard diagram.
* **Say this to examiner:** *"This is the formal 6-tier architecture specification for the entire system."*

### 📽️ [Neo4j_Campus_Tool_Server_Review_SRM.pptx](file:///c:/Users/heyit/Downloads/courses/Neo4j_Campus_Tool_Server_Review_SRM.pptx)
* **What it is:** The 19-slide presentation deck.
* **Note:** Slide 15 has been updated to cite official Regulations 2021 PDF extraction (668 courses, 3,498 allocations).

