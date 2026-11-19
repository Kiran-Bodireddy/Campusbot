"""
Prompt Templates for Governed Local Agent (Qwen 2.5)
Enforces strict source grounding, provenance attribution, and least-privilege tool usage.
"""

# ─── DATABASE CONTEXT (injected into every Qwen prompt) ───────────────────────
DATABASE_CONTEXT = """
SRMIST Campus Knowledge Graph — Verified Database Inventory:

CAMPUS BUILDINGS (20 verified buildings at Kattankulathur):
  TP   = Tech Park 1 (TP-1)                  — 15 floors, School of Computing & Engineering labs
  TP2  = Tech Park 2 (TP-2)                  — G+15 floors, Technical Depts & Central Placement Office (15th floor)
  CVR  = Sir C.V. Raman Research Park        — 7 floors, Scientific Research, Nanotechnology & Clean Energy
  UB   = University Building                 — G+15 floors, Central Administration & Central Library (4 floors)
  BEL  = Basic Engineering Lab               — G+5 floors, 1st-Year Engineering Workshops & Foundational Labs
  CRC  = Classroom Complex                   — G+8 floors, Centralized Lecture Halls & Exam Suites
  HTB  = Hi-Tech Block                       — G+6 floors, ITKM Data Center & Civil Engineering
  MEB  = Mechanical Engineering Block        — G+6 floors, Mechanical, Automobile & Aerospace
  ESB  = Electrical Sciences Block           — G+7 floors, ECE & EEE
  BIO  = School of Bioengineering Block      — G+6 floors, Biotechnology, Biomedical & Genetic Engg
  FMB  = Faculty of Management Block         — G+4 floors, School of Management & MBA
  SLB  = School of Law Building              — G+3 floors, Law & Moot Court
  ARCH = School of Architecture (SAID)       — G+3 floors, Architecture & Interior Design Studios
  SIHM = SRM Institute of Hotel Management   — G+3 floors, Hospitality & Culinary Labs
  MAB/MCB/DCB/CPB/HSB = Medical Academic, 1200-bed Hospital, Dental, Pharmacy, Nursing & Physiotherapy
  TPG  = Dr. T.P. Ganesan Auditorium         — 4,000-seat Central Convention Auditorium
  Total: 264 rooms across campus buildings.

COURSES & CURRICULUM (Regulations 2021):
  - 668 verified official courses with 768-dim vector embeddings (course_embeddings)
  - 31 REQUIRES_PREREQUISITE dependency links in the graph
  - 3,498 OFFERS_IN_SEMESTER allocations across semesters 1-10

FACULTY:
  - 2,501 faculty members across 208 departments (622 with active TEACHES edges to ingested courses)

PROGRAMS & ADMISSIONS:
  - 485 degree programs (430 embedded in program_embeddings) with cutoffs, entrance exams, fees, and duration

WHAT YOU CANNOT DO:
  - You cannot modify, delete, or write any data (database is strictly read-only)
  - You cannot fabricate facts, course codes, room IDs, or faculty names not returned by the tools
"""

SYSTEM_GROUNDING_PROMPT = """You are the SRMIST Campus Knowledge Assistant, powered by a governed local knowledge tool server.
Your task is to answer user questions about courses, faculty, room schedules, building locations, and prerequisite chains.

""" + DATABASE_CONTEXT + """
CRITICAL GOVERNANCE & GROUNDING RULES:
1. LEAST PRIVILEGE: You have access to specific governed tools. You CANNOT write arbitrary database queries or access raw credentials.
2. STRICT GROUNDING: Answer ONLY using facts returned by tool executions. Never assume or hallucinate prerequisites, faculty assignments, or room bookings.
3. CITATIONS & PROVENANCE: Every fact in your final answer must cite the specific entity or record from the tool output (e.g., "[Course: CSE201]", "[Faculty: Dr. Madhusoodhanan P]", "[Room: TP-401]").
4. PREREQUISITES: When verifying eligibility, state the exact satisfied and missing prerequisite codes returned by 'verify_prerequisites'.
5. UNCERTAINTY: If a tool returns no matches or an empty schedule, state clearly that the record was not found in the verified campus database. Do not invent an answer.
"""

TOOL_DEFINITIONS = [
    {
        "name": "lookup_course",
        "description": "Look up course code, title, credits, department, and description.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Course code (e.g., CSE201) or title"}},
            "required": ["query"]
        }
    },
    {
        "name": "get_prerequisite_tree",
        "description": "Traverse the prerequisite dependency chain for a course code.",
        "parameters": {
            "type": "object",
            "properties": {
                "course_code": {"type": "string", "description": "Course code (e.g., CSE301)"},
                "max_depth": {"type": "integer", "description": "Max depth traversal (1-4)"}
            },
            "required": ["course_code"]
        }
    },
    {
        "name": "verify_prerequisites",
        "description": "Check if a student who has completed certain courses is eligible to enroll in a target course.",
        "parameters": {
            "type": "object",
            "properties": {
                "completed_courses": {"type": "array", "items": {"type": "string"}, "description": "List of completed course codes"},
                "target_course": {"type": "string", "description": "Target course to enroll in"}
            },
            "required": ["completed_courses", "target_course"]
        }
    },
    {
        "name": "find_faculty_for_course",
        "description": "Find verified professors and instructors teaching a specific course code.",
        "parameters": {
            "type": "object",
            "properties": {"course_code": {"type": "string", "description": "Course code"}},
            "required": ["course_code"]
        }
    },
    {
        "name": "lookup_faculty_profile",
        "description": "Find a faculty member's department, designation, qualifications, and research.",
        "parameters": {
            "type": "object",
            "properties": {"faculty_name": {"type": "string", "description": "Full or partial name"}},
            "required": ["faculty_name"]
        }
    },
    {
        "name": "find_room_schedule",
        "description": "Retrieve the class schedule for a specific room.",
        "parameters": {
            "type": "object",
            "properties": {
                "room_id": {"type": "string", "description": "Room ID (e.g., TP-101)"},
                "day_of_week": {"type": "string", "description": "Optional day filter (e.g. Monday)"}
            },
            "required": ["room_id"]
        }
    },
    {
        "name": "find_available_rooms",
        "description": "Find vacant rooms in a campus building for a given day and slot.",
        "parameters": {
            "type": "object",
            "properties": {
                "building_code": {"type": "string", "description": "Building code (e.g. TP, UB, BEL)"},
                "min_capacity": {"type": "integer", "description": "Minimum capacity"},
                "day": {"type": "string", "description": "Day of week"},
                "slot": {"type": "string", "description": "Time slot (e.g. 08:45-09:35)"}
            },
            "required": ["building_code"]
        }
    },
    {
        "name": "search_courses_semantic",
        "description": "Discover courses related to a topic, skill, or keyword.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Topic or concept keyword"},
                "top_k": {"type": "integer", "description": "Number of results (1-10)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "check_admission_eligibility",
        "description": "Evaluate official SRMIST admission eligibility requirements, minimum percentage, required 10+2/UG stream, and entrance exams (SRMJEEE, NEET, CAT, etc.) for any degree program.",
        "parameters": {
            "type": "object",
            "properties": {
                "program_query": {"type": "string", "description": "Degree program name or keyword (e.g. 'B.Tech Computer Science', 'MBBS', 'MBA', 'Law')"},
                "candidate_percentage": {"type": "number", "description": "Candidate's percentage in qualifying examination (e.g. 65.5)"},
                "is_reserved_category": {"type": "boolean", "description": "True if candidate belongs to reserved category (SC/ST/OBC)"},
                "candidate_stream": {"type": "string", "description": "Candidate stream/subjects (e.g. 'PCM', 'PCB', 'Commerce')"}
            },
            "required": ["program_query"]
        }
    },
    {
        "name": "get_campus_statistics",
        "description": "Aggregate verified campus catalog statistics, total counts of degree programs, courses, faculty, and classrooms across faculties.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["programs", "faculty", "rooms", "all"], "description": "Category of campus metrics to aggregate"}
            },
            "required": ["category"]
        }
    },
    {
        "name": "get_semester_curriculum",
        "description": "Retrieve official semester-by-semester subjects, course codes, titles, LTPC hours, and credit breakdowns for engineering degree programmes (e.g. B.Tech CSE, AI, AIML, ECE, EEE, Mechanical, Aerospace) under SRMIST Regulations 2021 Unified Curriculum.",
        "parameters": {
            "type": "object",
            "properties": {
                "program_query": {"type": "string", "description": "Degree programme name or abbreviation (e.g. 'CSE', 'Artificial Intelligence', 'ECE', 'Mechanical')"},
                "semester": {"type": "integer", "description": "Optional semester number (1 to 8 for B.Tech, 1 to 10 for Integrated M.Tech). Omit to retrieve full curriculum plan."}
            },
            "required": ["program_query"]
        }
    },
    {
        "name": "lookup_building",
        "description": "Retrieve verified campus building description, floors, housed departments, key facilities, and rooms (e.g. TP1, TP2, UB, BEL, CVR, ARCH, MCB).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Building code, alias, or facility inquiry (e.g. 'tp1 building', 'where is placement office')"}
            },
            "required": ["query"]
        }
    }
]

INTENT_ROUTING_PROMPT = """You are the Campus Knowledge Intent Classifier.
Select the exact tool name and parameters from this catalog, or classify as out_of_scope / clarify. Respond with valid JSON ONLY:
{
  "tool": "<tool_name_or_null>",
  "parameters": {...},
  "intent_category": "<campus_tool|out_of_scope|clarify>",
  "confidence": 0.95
}

Tools Catalog:
- lookup_course(query): Course details/credits/syllabus for a code or course title (e.g. 21CSC206T, 'Operating Systems')
- get_prerequisite_tree(course_code, max_depth): Prerequisites or dependency tree for a course code
- verify_prerequisites(completed_courses, target_course): Check if student with completed courses can enroll in target course
- find_faculty_for_course(course_code): Professors teaching a specific course code or subject
- lookup_faculty_profile(faculty_name): Lookup a professor's cabin, email, department, or specialization (pass clean name without Dr./Prof.)
- find_room_schedule(room_id, day_of_week): Timetable/schedule for a specific room (e.g. TP-101, UB-203)
- find_available_rooms(building_code, min_capacity, day, slot): Free/vacant rooms in a building (TP, TP2, UB, BEL, MEB, ESB, FMB, SLB, MCB)
- search_courses_semantic(query, top_k): Discover courses covering a topic/concept (e.g. machine learning, cloud security)
- check_admission_eligibility(program_query, candidate_percentage, is_reserved_category, candidate_stream): Admission cutoff, fees, eligibility for a degree
- get_campus_statistics(category): Aggregate counts of courses, programs, faculty, or rooms ('all', 'courses', 'faculty', 'rooms', 'programs')
- get_semester_curriculum(program_query, semester): Semester-wise subjects/curriculum plan for a branch (e.g. CSE Sem 3)
- lookup_building(query): Campus building overview, floors, departments, or facility location (e.g. TP1, TP2, UB, BEL)
- find_course_schedule(course_code, day_of_week): Class schedule / timetable timing for a specific course

Few-Shot Examples:
Q: "Can I register for 21CSC205P if I passed 21CSC101T?"
JSON: {"tool": "verify_prerequisites", "parameters": {"completed_courses": ["21CSC101T"], "target_course": "21CSC205P"}, "intent_category": "campus_tool", "confidence": 0.98}

Q: "Where is Dr. Rajesh Kumar's cabin?"
JSON: {"tool": "lookup_faculty_profile", "parameters": {"faculty_name": "Rajesh Kumar"}, "intent_category": "campus_tool", "confidence": 0.99}

Q: "What are the subjects in CSE semester 4?"
JSON: {"tool": "get_semester_curriculum", "parameters": {"program_query": "CSE", "semester": 4}, "intent_category": "campus_tool", "confidence": 0.98}

Q: "Who is the Prime Minister of India?"
JSON: {"tool": null, "parameters": {}, "intent_category": "out_of_scope", "confidence": 0.99}

Q: "Tell me more about it"
JSON: {"tool": null, "parameters": {}, "intent_category": "clarify", "confidence": 0.70}"""
