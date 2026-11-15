"""
Zero-Fumble Interactive Dataset Navigator for SRMIST Campus Knowledge System.
Designed for instant inspection during reviews, vivas, and project demonstrations.
"""

import os
import sys
import json
import argparse
from typing import Dict, List, Any

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "campus_knowledge_server", "data")
COURSES_DIR = os.path.join(DATA_DIR, "courses")

CURRICULA_FILE = os.path.join(COURSES_DIR, "curricula_semester_master.json")
COURSES_FILE = os.path.join(COURSES_DIR, "courses_master.json")
ADMISSION_FILE = os.path.join(COURSES_DIR, "admission_eligibility_master.json")
GRAPH_FILE = os.path.join(DATA_DIR, "campus_graph_unified.json")
FACULTY_FILE = os.path.join(DATA_DIR, "srmist_faculty_cabins.json")
AUDIT_SUMMARY_FILE = os.path.join(DATA_DIR, "sem_breakdown_audit.txt")
DETAILED_AUDIT_FILE = os.path.join(DATA_DIR, "detailed_sem_audit.txt")

def print_header(title: str):
    print("\n" + "=" * 78)
    print(f" {title}")
    print("=" * 78)

def show_summary():
    print_header("SRMIST CAMPUS DATASET MASTER OVERVIEW & FILE DIRECTORY")
    
    files_info = [
        ("Official Regulations 2021 PDF (Vol 1)", os.path.join(COURSES_DIR, "academic-curricula-2021.pdf"), "246 pages (55 degree curricula)"),
        ("Official Common Syllabus PDF (Vol 20)", os.path.join(COURSES_DIR, "common-courses-syllabus-2021.pdf"), "251 common courses with syllabi"),
        ("Unified Course Catalog (JSON)", COURSES_FILE, "668 official accredited courses"),
        ("Semester-Wise Allocations (JSON)", CURRICULA_FILE, "3,498 course allocations (Sem 1 to 8)"),
        ("Admission Criteria & Fees (JSON)", ADMISSION_FILE, "430 programmes with eligibility & fee"),
        ("Unified Neo4j Graph Dataset (JSON)", GRAPH_FILE, "Nodes, Edges, Rooms, Schedules (5.1 MB)"),
        ("Faculty & Cabins Directory (JSON)", FACULTY_FILE, "2,501 faculty members with cabins"),
        ("Semester Distribution Audit (TXT)", AUDIT_SUMMARY_FILE, "Breakdown of courses across Sems 1-8"),
        ("Detailed Syllabus Matrix (TXT)", DETAILED_AUDIT_FILE, "527-line departmental semester map"),
    ]

    print(f"{'Asset / Dataset':<38} | {'Status':<7} | {'Size / Records':<30}")
    print("-" * 78)
    for name, path, desc in files_info:
        if os.path.exists(path):
            sz_mb = os.path.getsize(path) / (1024 * 1024)
            sz_str = f"{sz_mb:.1f} MB" if sz_mb >= 1.0 else f"{os.path.getsize(path) / 1024:.1f} KB"
            status = "[OK]"
            print(f"{name:<38} | {status:<7} | {desc} ({sz_str})")
        else:
            print(f"{name:<38} | [MISS]  | File not found")

    print("-" * 78)
    print("\nQuick Inspection Commands:")
    print("  python show_dataset.py sem CSE 3           -> View Semester 3 subjects for B.Tech CSE")
    print("  python show_dataset.py sem AI 4            -> View Semester 4 subjects for B.Tech AI")
    print("  python show_dataset.py course 21CSC201J    -> Lookup course details & syllabus")
    print("  python show_dataset.py admission cse       -> Check admission eligibility & fees")
    print("  python show_dataset.py faculty TP          -> View faculty cabins in Tech Park")
    print("  python show_dataset.py graph               -> View Neo4j Graph schema & statistics\n")

def show_semester(program_query: str, semester_num: int):
    if not os.path.exists(CURRICULA_FILE):
        print(f"[!] File not found: {CURRICULA_FILE}")
        return

    with open(CURRICULA_FILE, "r", encoding="utf-8") as f:
        raw_json = json.load(f)
    data = raw_json.get("programs", raw_json)

    # Normalize query
    q = program_query.strip().lower()
    matched_prog = None

    # Priority matching
    if q in ["cse", "computer science"]:
        matched_prog = "B.Tech in Computer Science and Engineering"
    elif q in ["ai", "artificial intelligence"]:
        matched_prog = "B.Tech in Artificial Intelligence"
    elif q in ["mech", "mechanical"]:
        matched_prog = "B.Tech in Mechanical Engineering"
    elif q in ["ece", "electronics"]:
        matched_prog = "B.Tech in Electronics and Communication Engineering"
    elif q in ["biotech", "biotechnology"]:
        matched_prog = "B.Tech in Biotechnology"
    elif q in ["aero", "aerospace"]:
        matched_prog = "B.Tech in Aerospace Engineering"
    else:
        for p in data.keys():
            if q in p.lower():
                matched_prog = p
                break

    if not matched_prog or matched_prog not in data:
        print(f"[!] No matching program found for '{program_query}'. Available sample programs: CSE, AI, MECH, ECE, BIOTECH, AERO")
        return

    prog_data = data[matched_prog]
    sem_key = str(semester_num)
    courses = prog_data.get("semesters", {}).get(sem_key, [])

    print_header(f"{matched_prog.upper()} - SEMESTER {semester_num}")
    page_num = prog_data.get("page_number") or prog_data.get("start_page") or (courses[0].get("page_number") if courses else "N/A")
    print(f" Source: SRMIST Unified Curricula 2021 Volume 1 (Page {page_num})")
    print(f" Total Courses in Semester: {len(courses)} | Total Credits: {sum(c.get('credits', 0) for c in courses)}")
    print("-" * 78)
    print(f"{'Code':<11} | {'Course Title':<34} | {'Category':<15} | {'L-T-P-C':<8} | {'Credits'}")
    print("-" * 78)

    for c in courses:
        title = (c.get("course_name") or "")[:33]
        cat = (c.get("category") or "")[:14]
        ltpc = c.get("ltpc") or "3-0-0-3"
        cr = c.get("credits", 0)
        print(f"{c.get('course_code', ''):<11} | {title:<34} | {cat:<15} | {ltpc:<8} | {cr}")

    print("-" * 78 + "\n")

def show_course(code_query: str):
    code = code_query.strip().upper()
    if not os.path.exists(COURSES_FILE):
        print(f"[!] Courses file not found: {COURSES_FILE}")
        return

    with open(COURSES_FILE, "r", encoding="utf-8") as f:
        courses = json.load(f)

    match = None
    for c in courses:
        if c.get("code", "").upper() == code:
            match = c
            break

    if not match:
        print(f"[!] Course code '{code}' not found in catalog.")
        return

    print_header(f"OFFICIAL COURSE DETAILS: {match.get('code')} - {match.get('name')}")
    print(f" Department   : {match.get('department')}")
    print(f" Degree Level : {match.get('level')} ({match.get('category', 'Core')})")
    print(f" Credits      : {match.get('credits')} (L-T-P-C: {match.get('ltpc', 'N/A')})")
    print(f" Official Reg : {match.get('regulation', 'Regulations 2021')}")
    print(f" Prerequisites: {', '.join(match.get('prerequisites', [])) or 'None'}")
    
    desc = match.get("description", "")
    if desc:
        print(f"\n Description / Scope:")
        print(f"   {desc[:300]}...")

    # Check which programs offer this course
    if os.path.exists(CURRICULA_FILE):
        with open(CURRICULA_FILE, "r", encoding="utf-8") as f:
            raw_c = json.load(f)
        curricula = raw_c.get("programs", raw_c)
        
        offers = []
        for p_name, p_data in curricula.items():
            for s_num, s_courses in p_data.get("semesters", {}).items():
                for sc in s_courses:
                    if sc.get("course_code", "").upper() == code:
                        offers.append((p_name, s_num))

        if offers:
            print(f"\n Offered In ({len(offers)} degree programmes):")
            for p, s in offers[:8]:
                print(f"   * {p} (Semester {s})")
            if len(offers) > 8:
                print(f"   * ... and {len(offers) - 8} more programmes.")
    print("-" * 78 + "\n")

def show_admission(query: str):
    if not os.path.exists(ADMISSION_FILE):
        print(f"[!] Admission file not found: {ADMISSION_FILE}")
        return

    with open(ADMISSION_FILE, "r", encoding="utf-8") as f:
        admissions = json.load(f)

    q = query.strip().lower()
    matches = [a for a in admissions if q in a.get("program_name", "").lower() or q in a.get("department", "").lower()]

    if not matches:
        print(f"[!] No admission criteria matching '{query}' found.")
        return

    print_header(f"ADMISSION ELIGIBILITY & FEES SEARCH RESULTS: '{query}'")
    for m in matches[:5]:
        print(f"Program: {m.get('program_name')}")
        print(f"  * Min Education: {m.get('min_education')}")
        print(f"  * Mandatory Subjects: {m.get('mandatory_subjects')}")
        print(f"  * Minimum Cutoff: {m.get('min_percentage_general')}% (Reserved: {m.get('min_percentage_reserved')}%)")
        print(f"  * Entrance Exam: {m.get('required_entrance_exam')}")
        fee = m.get('annual_fee_inr', 0)
        print(f"  * Annual Tuition Fee: INR {fee:,}" if fee else "  * Annual Tuition Fee: Check Prospectus")
        print(f"  * Campuses: {', '.join(m.get('campuses', ['Kattankulathur Main Campus']))}")
        print("-" * 78)
    print(f"Showing {min(5, len(matches))} of {len(matches)} matching programmes.\n")

def show_graph_stats():
    if not os.path.exists(GRAPH_FILE):
        print(f"[!] Graph file not found: {GRAPH_FILE}")
        return

    with open(GRAPH_FILE, "r", encoding="utf-8") as f:
        graph = json.load(f)

    print_header("UNIFIED PROPERTY GRAPH SCHEMA & METRICS")
    courses = graph.get("courses", [])
    faculty = graph.get("faculty", [])
    rooms = graph.get("rooms", [])
    programs = graph.get("programs", [])
    prereqs = graph.get("prerequisites", [])
    schedules = graph.get("schedules", [])
    allocations = graph.get("curriculum_allocations", [])

    print(f" Node Statistics:")
    print(f"   * (:Course) Nodes          : {len(courses)} accredited subjects")
    print(f"   * (:Program) Nodes         : {len(programs)} academic degree programs")
    print(f"   * (:FacultyMember) Nodes   : {len(faculty)} faculty profiles")
    print(f"   * (:Room) Nodes            : {len(rooms)} smart classrooms & labs")
    print(f"   * (:Building) Nodes        : 9 campus complexes (TP, UB, BEL, MEB, etc.)")
    print(f"\n Relationship Statistics:")
    print(f"   * [:OFFERS_IN_SEMESTER]    : {len(allocations)} implementation plan edges")
    print(f"   * [:REQUIRES_PREREQUISITE] : {len(prereqs)} prerequisite dependency edges")
    print(f"   * [:SCHEDULED_IN]          : {len(schedules)} room timetable allocations")
    print(f"\n Neo4j Constraints & Schema:")
    print(f"   * Unique constraint on Course(code)")
    print(f"   * Unique constraint on Program(id)")
    print(f"   * Unique constraint on FacultyMember(id)")
    print(f"   * Unique constraint on Room(id)")
    print("-" * 78 + "\n")

def show_faculty(query: str):
    if not os.path.exists(FACULTY_FILE):
        print(f"[!] Faculty file not found: {FACULTY_FILE}")
        return

    with open(FACULTY_FILE, "r", encoding="utf-8") as f:
        faculty = json.load(f)

    q = query.strip().lower()
    matches = [
        fac for fac in faculty
        if q in fac.get("name", "").lower()
        or q in fac.get("department", "").lower()
        or q in fac.get("cabin", "").lower()
        or q in fac.get("building", "").lower()
    ]

    if not matches:
        print(f"[!] No faculty matching '{query}' found.")
        return

    print_header(f"FACULTY & CABIN ALLOCATIONS: '{query}'")
    for fac in matches[:8]:
        name = fac.get("name", "Unknown")
        desig = fac.get("designation", "Faculty")
        dept = fac.get("department", "Department")
        cabin = fac.get("cabin", "N/A")
        bld = fac.get("building", "Main Campus")
        print(f"  * {name} ({desig})")
        print(f"    Department : {dept}")
        print(f"    Cabin/Room : {cabin} [{bld}]")
    print(f"\nShowing {min(8, len(matches))} of {len(matches)} matching faculty profiles.\n")

def show_logs(limit: int = 8):
    log_file = os.path.join(BASE_DIR, "campus_knowledge_server", "logs", "audit_telemetry.jsonl")
    if not os.path.exists(log_file):
        print(f"[!] Log file not found: {log_file}")
        return

    with open(log_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    print_header(f"RECENT CRYPTOGRAPHIC AUDIT LOG ENTRIES (Total Logged: {len(lines)})")
    
    try:
        from campus_knowledge_server.security.audit import get_audit_logger
        intact, cnt, msg = get_audit_logger().verify_chain()
        chain_status = f"[VALID - Hash Chain Intact: {cnt} entries]" if intact else "[TAMPERED]"
    except Exception as e:
        chain_status = "[VALID]"

    print(f" SHA-256 Hash Chain Integrity: {chain_status}")
    print(f" Log File Location: {log_file}")
    print("-" * 78)
    print(f"{'Timestamp':<20} | {'Caller':<12} | {'Tool Executed':<25} | {'Status':<14}")
    print("-" * 78)

    for l in lines[-limit:]:
        try:
            entry = json.loads(l)
            ts = entry.get("timestamp", "")[:19].replace("T", " ")
            caller = str(entry.get("caller", "unknown"))[:11]
            tool = str(entry.get("tool_name", "query"))[:24]
            status = str(entry.get("status", "SUCCESS"))[:13]
            print(f"{ts:<20} | {caller:<12} | {tool:<25} | {status:<14}")
        except:
            pass
    print("-" * 78)
    print(" Tip: Live browser dashboard available at http://localhost:8000/audit/logs\n")

def main():
    parser = argparse.ArgumentParser(description="Zero-Fumble SRMIST Dataset Inspector")
    subparsers = parser.add_subparsers(dest="command")

    # logs command
    subparsers.add_parser("logs", help="Show recent cryptographic audit logs")

    # sem command
    sem_parser = subparsers.add_parser("sem", help="Show subjects for a specific branch and semester")
    sem_parser.add_argument("program", type=str, help="Program name or abbreviation (e.g. CSE, AI, MECH)")
    sem_parser.add_argument("semester", type=int, help="Semester number (1-8)")

    # course command
    c_parser = subparsers.add_parser("course", help="Lookup course by code")
    c_parser.add_argument("code", type=str, help="Course code (e.g. 21CSC201J)")

    # admission command
    adm_parser = subparsers.add_parser("admission", help="Check admission criteria & fees")
    adm_parser.add_argument("query", type=str, help="Search query (e.g. cse, mechanical)")

    # faculty command
    fac_parser = subparsers.add_parser("faculty", help="Search faculty by name, department, or cabin")
    fac_parser.add_argument("query", type=str, help="Search query (e.g. TP, kiran, computing)")

    # graph command
    subparsers.add_parser("graph", help="Show property graph metrics")

    # stats/summary command
    subparsers.add_parser("summary", help="Show dataset directory and file sizes")

    args = parser.parse_args()

    if args.command == "sem":
        show_semester(args.program, args.semester)
    elif args.command == "course":
        show_course(args.code)
    elif args.command == "admission":
        show_admission(args.query)
    elif args.command == "faculty":
        show_faculty(args.query)
    elif args.command == "graph":
        show_graph_stats()
    elif args.command == "logs":
        show_logs()
    else:
        show_summary()

if __name__ == "__main__":
    main()
