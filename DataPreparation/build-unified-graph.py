"""
Campus Knowledge Graph Data Builder
Combines SRMIST Academic Programs Master, Kattankulathur Faculty Master,
Campus Infrastructure (Buildings/Rooms), and Prerequisite DAGs.
"""

import os
import json
import csv
import re
import random
from typing import Dict, List, Any

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COURSES_ROOT = os.path.dirname(BASE_DIR)

LOCAL_PROGRAMS_PATH = os.path.join(BASE_DIR, "data", "courses", "srmist_programs_master.json")
PROGRAMS_JSON_PATH = LOCAL_PROGRAMS_PATH if os.path.exists(LOCAL_PROGRAMS_PATH) else os.path.join(COURSES_ROOT, "srmist_programs_master.json")
FACULTY_CSV_PATH = os.path.join(BASE_DIR, "data", "faculty_master.csv")
OUTPUT_GRAPH_JSON = os.path.join(BASE_DIR, "data", "campus_graph_unified.json")
OUTPUT_CYPHER_SCRIPT = os.path.join(BASE_DIR, "data", "seed_campus_graph.cyp")

# Seed random for repeatable graph generation
random.seed(42)

BUILDINGS = [
    {"code": "TP", "name": "Tech Park", "floors": 15, "campus": "Kattankulathur (KTR)", "focus": "Engineering & Computing"},
    {"code": "TP2", "name": "Tech Park 2 (TP-2)", "floors": 12, "campus": "Kattankulathur (KTR)", "focus": "Faculty Research Wings & Specialized Labs"},
    {"code": "UB", "name": "University Building", "floors": 14, "campus": "Kattankulathur (KTR)", "focus": "Administration & Sciences"},
    {"code": "BEL", "name": "Bioengineering Block", "floors": 8, "campus": "Kattankulathur (KTR)", "focus": "Biotechnology & Genetic Engg"},
    {"code": "MEB", "name": "Mechanical Engineering Block", "floors": 6, "campus": "Kattankulathur (KTR)", "focus": "Mechanical & Automobile"},
    {"code": "ESB", "name": "Electrical Sciences Block", "floors": 7, "campus": "Kattankulathur (KTR)", "focus": "ECE & EEE"},
    {"code": "FMB", "name": "Faculty of Management Block", "floors": 5, "campus": "Kattankulathur (KTR)", "focus": "Management & MBA"},
    {"code": "SLB", "name": "School of Law Building", "floors": 4, "campus": "Kattankulathur (KTR)", "focus": "Law"},
    {"code": "MCB", "name": "Medical College Hospital Block", "floors": 10, "campus": "Kattankulathur (KTR)", "focus": "Medicine & Health Sciences"},
]

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
SLOTS = [
    "08:45-09:35",
    "09:45-10:35",
    "10:45-11:35",
    "11:45-12:35",
    "13:30-14:20",
    "14:30-15:20",
    "15:30-16:20"
]

def generate_rooms() -> List[Dict[str, Any]]:
    rooms = []
    room_types = [("Lecture Hall", 60), ("Auditorium Hall", 120), ("Smart Classroom", 45), ("Computer Lab", 50), ("Research Lab", 30)]
    for b in BUILDINGS:
        b_code = b["code"]
        for floor in range(1, min(b["floors"] + 1, 6)):
            for r_num in range(1, 7):
                room_id = f"{b_code}-{floor}{r_num:02d}"
                r_type, base_cap = room_types[(floor + r_num) % len(room_types)]
                rooms.append({
                    "id": room_id,
                    "room_number": room_id,
                    "building_code": b_code,
                    "floor": floor,
                    "type": r_type,
                    "capacity": base_cap + (r_num * 5)
                })
    return rooms

def load_faculty() -> List[Dict[str, Any]]:
    faculty_list = []
    cabin_csv = os.path.join(BASE_DIR, "data", "srmist_faculty_cabins.csv")
    csv_to_use = cabin_csv if os.path.exists(cabin_csv) else FACULTY_CSV_PATH

    if not os.path.exists(csv_to_use):
        print(f"Warning: Faculty CSV not found at {csv_to_use}")
        return []
    
    with open(csv_to_use, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            dept = (row.get("fullDepartment") or row.get("department") or "").strip()
            short_dept = (row.get("department") or "").strip()
            college = (row.get("college") or "").strip()
            designation = (row.get("designation") or "").strip()
            cabin = (row.get("staffRoom_cabin") or "").strip()
            spec = (row.get("specialization") or "").strip()
            email = (row.get("email") or "").strip()
            phone = (row.get("phone") or "").strip()
            exp = (row.get("experience") or "").strip()
            quals = (row.get("qualifications") or "").strip()
            
            faculty_list.append({
                "id": f"FAC-{i:04d}",
                "faculty_id_official": (row.get("facultyId") or "").strip(),
                "name": name,
                "college": college,
                "department": dept,
                "short_department": short_dept,
                "designation": designation,
                "cabin": cabin if cabin else "Staff Room (TBA)",
                "specialization": spec,
                "email": email,
                "phone": phone,
                "experience": exp,
                "qualifications": quals
            })
    return faculty_list

COURSES_MASTER_JSON_PATH = os.path.join(BASE_DIR, "data", "courses", "courses_master.json")

def load_programs_and_courses() -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    programs = []
    courses = []
    if not os.path.exists(PROGRAMS_JSON_PATH):
        print(f"Warning: Programs JSON not found at {PROGRAMS_JSON_PATH}")
        return [], []

    with open(PROGRAMS_JSON_PATH, mode="r", encoding="utf-8") as f:
        raw_programs = json.load(f)

    for p in raw_programs:
        prog_id = f"PROG-{p.get('program_id', len(programs)+1):03d}"
        programs.append({
            "id": prog_id,
            "name": p.get("program_name", ""),
            "faculty": p.get("faculty", ""),
            "department": p.get("department", ""),
            "degree_level": p.get("degree_level", ""),
            "duration": p.get("duration", "4 Years"),
            "annual_fee_inr": p.get("annual_fees_inr", 0),
            "eligibility": p.get("eligibility_criteria", ""),
            "about": p.get("about_program", ""),
            "campuses": p.get("campuses_available", "Kattankulathur (KTR)")
        })

    # Load authentic SRMIST official courses from courses_master.json
    if os.path.exists(COURSES_MASTER_JSON_PATH):
        with open(COURSES_MASTER_JSON_PATH, mode="r", encoding="utf-8") as f:
            raw_courses = json.load(f)

        # Build mapping from department to program_id
        prog_by_dept: Dict[str, str] = {}
        for p in programs:
            d_norm = p["department"].lower()
            if d_norm not in prog_by_dept:
                prog_by_dept[d_norm] = p["id"]

        for c in raw_courses:
            c_dept = c.get("department", "").lower()
            matched_prog_id = "PROG-001"
            for d_key, p_id in prog_by_dept.items():
                if d_key and (d_key in c_dept or c_dept in d_key):
                    matched_prog_id = p_id
                    break

            c_copy = dict(c)
            c_copy["program_id"] = matched_prog_id
            courses.append(c_copy)
    return programs, courses

CURRICULA_MASTER_JSON_PATH = os.path.join(BASE_DIR, "data", "courses", "curricula_semester_master.json")

def load_curriculum_allocations(programs: List[Dict[str, Any]], courses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    allocations = []
    if not os.path.exists(CURRICULA_MASTER_JSON_PATH):
        print(f"Warning: Curricula JSON not found at {CURRICULA_MASTER_JSON_PATH}")
        return allocations

    with open(CURRICULA_MASTER_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    prog_map = {p["name"].lower(): p["id"] for p in programs}

    for prog_name, p_info in data.get("programs", {}).items():
        prog_id = prog_map.get(prog_name.lower())
        if not prog_id:
            for p in programs:
                if prog_name.lower() in p["name"].lower() or p["name"].lower() in prog_name.lower():
                    prog_id = p["id"]
                    break
        if not prog_id:
            prog_id = f"PROG-{p_info.get('program_id', 999):03d}"

        for sem_str, c_list in p_info.get("semesters", {}).items():
            sem_num = int(sem_str)
            for c in c_list:
                allocations.append({
                    "program_id": prog_id,
                    "program_name": prog_name,
                    "degree_type": c.get("degree_type", "B.Tech"),
                    "semester": sem_num,
                    "academic_year": c.get("academic_year", (sem_num + 1) // 2),
                    "course_code": c["course_code"],
                    "course_name": c["course_name"],
                    "category": c["category"],
                    "credits": c["credits"],
                    "ltpc": c["ltpc"],
                    "page_number": c.get("page_number", 1)
                })
    return allocations

def build_prerequisite_graph(courses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Builds realistic prerequisite edges (:Course)-[:REQUIRES_PREREQUISITE]->(:Course)"""
    prereqs = []
    courses_by_code: Dict[str, Dict[str, Any]] = {c["code"].upper(): c for c in courses}

    for c in courses:
        target_code = c["code"]
        for req_code in c.get("prerequisites", []):
            req_norm = req_code.upper()
            if req_norm in courses_by_code:
                prereqs.append({
                    "target_course_code": target_code,
                    "prerequisite_course_code": req_norm,
                    "condition": "MANDATORY_MIN_GRADE_C",
                    "min_credits_required": courses_by_code[req_norm].get("credits", 3)
                })

    return prereqs

def schedule_courses(courses: List[Dict[str, Any]], rooms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Allocates courses into rooms and timeslots without collision."""
    schedule = []
    occupied_slots = set() # (room_id, day, slot)

    for c in courses: # Schedule all active official courses
        # Pick suitable building
        dept = c["department"]
        matching_rooms = [r for r in rooms]
        if "Computing" in dept or "Computer" in dept:
            matching_rooms = [r for r in rooms if r["building_code"] == "TP"]
        elif "Management" in c["faculty"]:
            matching_rooms = [r for r in rooms if r["building_code"] == "FMB"]
        elif "Medicine" in c["faculty"]:
            matching_rooms = [r for r in rooms if r["building_code"] == "MCB"]
        elif "Mechanical" in dept:
            matching_rooms = [r for r in rooms if r["building_code"] == "MEB"]
        elif "Bio" in dept:
            matching_rooms = [r for r in rooms if r["building_code"] == "BEL"]

        if not matching_rooms:
            matching_rooms = rooms

        # Allocate 2 weekly sessions
        assigned = 0
        for _ in range(20):
            if assigned >= 2:
                break
            r = random.choice(matching_rooms)
            d = random.choice(DAYS)
            s = random.choice(SLOTS)
            key = (r["id"], d, s)
            if key not in occupied_slots:
                occupied_slots.add(key)
                schedule.append({
                    "course_id": c["id"],
                    "course_code": c["code"],
                    "room_id": r["id"],
                    "building_code": r["building_code"],
                    "day": d,
                    "slot": s
                })
                assigned += 1

    return schedule

def link_faculty_teaching(faculty: List[Dict[str, Any]], courses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Assigns real faculty members to teach matching courses based on department."""
    assignments = []
    # Group faculty by department
    faculty_by_dept: Dict[str, List[Dict[str, Any]]] = {}
    for f in faculty:
        dept_norm = f["department"].lower()
        faculty_by_dept.setdefault(dept_norm, []).append(f)

    for c in courses:
        c_dept = (c.get("department") or "").lower()
        c_fac = (c.get("faculty") or "").lower()
        matched_faculty = []
        for d_key, fac_list in faculty_by_dept.items():
            if c_dept and (c_dept in d_key or d_key in c_dept):
                matched_faculty = fac_list
                break

        if not matched_faculty and faculty:
            # Fallback to college match
            matched_faculty = [f for f in faculty if c_fac and c_fac in (f.get("college") or "").lower()]
        if not matched_faculty:
            matched_faculty = faculty[:50]

        # Pick 1-2 instructors
        assigned = random.sample(matched_faculty, min(len(matched_faculty), random.choice([1, 2])))
        for prof in assigned:
            p_desig = str(prof.get("designation") or "")
            assignments.append({
                "faculty_id": prof["id"],
                "faculty_name": prof["name"],
                "faculty_email": prof["email"],
                "course_id": c["id"],
                "course_code": c["code"],
                "role": "Lead Instructor" if p_desig.startswith("Professor") or "HoD" in p_desig else "Course Instructor"
            })

    return assignments

def main():
    print("Step 1: Loading raw programs & faculty...")
    programs, courses = load_programs_and_courses()
    faculty = load_faculty()
    rooms = generate_rooms()

    print(f"Loaded: {len(programs)} Programs, {len(courses)} Courses, {len(faculty)} Faculty, {len(rooms)} Rooms in {len(BUILDINGS)} Buildings.")

    print("Step 2: Building prerequisite relationships...")
    prereqs = build_prerequisite_graph(courses)
    print(f"Generated: {len(prereqs)} Prerequisite relationships.")

    print("Step 3: Scheduling courses into rooms...")
    schedules = schedule_courses(courses, rooms)
    print(f"Generated: {len(schedules)} Scheduled lecture slots.")

    print("Step 4: Linking faculty teaching assignments...")
    teaching = link_faculty_teaching(faculty, courses)
    print(f"Generated: {len(teaching)} Teaching assignment relationships.")

    print("Step 5: Loading curriculum semester allocations...")
    curriculum_allocations = load_curriculum_allocations(programs, courses)
    print(f"Loaded: {len(curriculum_allocations)} Curriculum semester allocations.")

    dataset = {
        "metadata": {
            "version": "1.1.0",
            "institution": "SRM Institute of Science and Technology (SRMIST)",
            "primary_campus": "Kattankulathur (KTR)",
            "regulations": "2021",
            "curriculum_volumes": [
                "Volume 1: Unified Curricula (Implementation Plans for 55 Programmes)",
                "Volume 20: Common Courses Syllabus"
            ],
            "total_programs": len(programs),
            "total_courses": len(courses),
            "total_faculty": len(faculty),
            "total_rooms": len(rooms),
            "total_prerequisites": len(prereqs),
            "total_curriculum_allocations": len(curriculum_allocations)
        },
        "buildings": BUILDINGS,
        "rooms": rooms,
        "programs": programs,
        "courses": courses,
        "faculty": faculty,
        "prerequisites": prereqs,
        "schedules": schedules,
        "teaching_assignments": teaching,
        "curriculum_allocations": curriculum_allocations
    }

    with open(OUTPUT_GRAPH_JSON, mode="w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2)
    print(f"Saved unified JSON dataset to: {OUTPUT_GRAPH_JSON}")

    # Generate Cypher script
    print("Step 6: Generating Cypher seed script...")
    with open(OUTPUT_CYPHER_SCRIPT, mode="w", encoding="utf-8") as cyp:
        cyp.write("// SRMIST Campus Knowledge Graph Seed Script (Regulations 2021 Unified Curricula)\n")
        cyp.write("// Constraints\n")
        cyp.write("CREATE CONSTRAINT course_code_unique IF NOT EXISTS FOR (c:Course) REQUIRE c.code IS UNIQUE;\n")
        cyp.write("CREATE CONSTRAINT program_id_unique IF NOT EXISTS FOR (p:Program) REQUIRE p.id IS UNIQUE;\n")
        cyp.write("CREATE CONSTRAINT faculty_id_unique IF NOT EXISTS FOR (f:FacultyMember) REQUIRE f.id IS UNIQUE;\n")
        cyp.write("CREATE CONSTRAINT room_id_unique IF NOT EXISTS FOR (r:Room) REQUIRE r.id IS UNIQUE;\n")
        cyp.write("CREATE CONSTRAINT building_code_unique IF NOT EXISTS FOR (b:Building) REQUIRE b.code IS UNIQUE;\n\n")

        # Buildings
        cyp.write("// Buildings\n")
        for b in BUILDINGS:
            cyp.write(f"MERGE (b:Building {{code: '{b['code']}'}}) SET b.name = '{b['name']}', b.floors = {b['floors']}, b.campus = '{b['campus']}';\n")

        # Rooms
        cyp.write("\n// Sample Rooms\n")
        for r in rooms[:60]:
            cyp.write(f"MERGE (r:Room {{id: '{r['id']}'}}) SET r.room_number = '{r['room_number']}', r.type = '{r['type']}', r.capacity = {r['capacity']};\n")
            cyp.write(f"MATCH (r:Room {{id: '{r['id']}'}}), (b:Building {{code: '{r['building_code']}'}}) MERGE (r)-[:LOCATED_IN]->(b);\n")

        # Sample Course Nodes with Semester Metadata
        cyp.write("\n// Courses with Semester and LTPC Metadata\n")
        for c in courses[:50]:
            safe_name = c['name'].replace("'", "\\'")
            safe_dept = c['department'].replace("'", "\\'")
            cyp.write(f"MERGE (c:Course {{code: '{c['code']}'}}) SET c.name = '{safe_name}', c.credits = {c['credits']}, c.ltpc = '{c.get('ltpc', '3-0-0-3')}', c.category = '{c.get('category', '')}', c.semester = {c.get('primary_semester', 1)}, c.academic_year = {c.get('academic_year', 1)}, c.department = '{safe_dept}';\n")

        # Sample OFFERS_IN_SEMESTER relationships
        cyp.write("\n// Curriculum Implementation Plan Relationships: (:Program)-[:OFFERS_IN_SEMESTER]->(:Course)\n")
        for alloc in curriculum_allocations[:100]:
            safe_prog = alloc['program_name'].replace("'", "\\'")
            cyp.write(f"MERGE (p:Program {{name: '{safe_prog}'}});\n")
            cyp.write(f"MATCH (p:Program {{name: '{safe_prog}'}}), (c:Course {{code: '{alloc['course_code']}'}}) MERGE (p)-[:OFFERS_IN_SEMESTER {{semester: {alloc['semester']}, academic_year: {alloc['academic_year']}, credits: {alloc['credits']}, ltpc: '{alloc['ltpc']}', category: '{alloc['category']}'}}]->(c);\n")

    print(f"Generated Cypher constraints and base graph in {OUTPUT_CYPHER_SCRIPT}")
    print("Done! Data synthesis complete.")

if __name__ == "__main__":
    main()
