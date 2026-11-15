 import fitz
import re
import json
import os

pdf_path = "campus_knowledge_server/data/courses/academic-curricula-2021.pdf"
doc = fitz.open(pdf_path)

sem_roman_map = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
    "ix": 9, "x": 10,
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
    "9": 9, "10": 10
}

cat_map = {
    "H": "Humanities and Social Sciences",
    "B": "Basic Sciences",
    "S": "Engineering Sciences",
    "C": "Professional Core",
    "E": "Professional Elective",
    "O": "Open Elective",
    "P": "Project / Practice",
    "M": "Mandatory Non-Credit"
}

# 55 Canonical Programs from Table of Contents (Pages 2-3)
PROGRAM_REGISTRY = [
    (1, 9, "B.Tech in Aerospace Engineering", "B.Tech"),
    (2, 14, "B.Tech in Artificial Intelligence", "B.Tech"),
    (3, 18, "B.Tech in Automation and Robotics", "B.Tech"),
    (4, 23, "B.Tech in Automobile Engineering", "B.Tech"),
    (5, 27, "B.Tech in Automobile Engineering with Specialization in Automotive Electronics", "B.Tech"),
    (6, 33, "B.Tech in Automotive Engineering", "B.Tech"),
    (7, 38, "B.Tech in Automobile Engineering with Specialization in Vehicle Testing", "B.Tech"),
    (8, 42, "B.Tech in Biotechnology", "B.Tech"),
    (9, 46, "B.Tech in Biotechnology with Specialization in Computational Biology", "B.Tech"),
    (10, 50, "B.Tech in Biotechnology with Specialization in Regenerative Medicine", "B.Tech"),
    (11, 54, "B.Tech in Biotechnology with Specialization in Genetic Engineering", "B.Tech"),
    (12, 58, "B.Tech in Biomedical Engineering", "B.Tech"),
    (13, 62, "B.Tech in Biomedical Engineering with Specialization in Machine Intelligence", "B.Tech"),
    (14, 66, "B.Tech in Chemical Engineering", "B.Tech"),
    (15, 71, "B.Tech in Civil Engineering", "B.Tech"),
    (16, 76, "B.Tech in Civil Engineering with Computer Applications", "B.Tech"),
    (17, 80, "B.Tech in Computer Science and Engineering", "B.Tech"),
    (18, 84, "B.Tech in Computer Science and Engineering with Specialization in Artificial Intelligence and Machine Learning", "B.Tech"),
    (19, 89, "B.Tech in Computer Science and Engineering with Specialization in Big Data Analytics", "B.Tech"),
    (20, 93, "B.Tech in Computer Science and Engineering with Specialization in Blockchain Technology", "B.Tech"),
    (21, 97, "B.Tech in Computer Science and Engineering with Specialization in Cloud Computing", "B.Tech"),
    (22, 101, "B.Tech in Computer Science and Engineering with Specialization in Computer Networking", "B.Tech"),
    (23, 105, "B.Tech in Computer Science and Engineering with Specialization in Cybersecurity", "B.Tech"),
    (24, 110, "B.Tech in Computer Science and Engineering with Specialization in Data Science", "B.Tech"),
    (25, 114, "B.Tech in Computer Science and Engineering with Specialization in Gaming Technology", "B.Tech"),
    (26, 118, "B.Tech in Computer Science and Engineering with Specialization in Information Technology", "B.Tech"),
    (27, 122, "B.Tech in Computer Science and Engineering with Specialization in Internet of Things", "B.Tech"),
    (28, 126, "B.Tech in Computer Science and Engineering with Specialization in Software Engineering", "B.Tech"),
    (29, 131, "B.Tech in Computer Science and Business Systems", "B.Tech"),
    (30, 135, "B.Tech in Electronics and Communication Engineering", "B.Tech"),
    (31, 139, "B.Tech in Electronics and Communication Engineering with Specialization in Cyber Physical Systems", "B.Tech"),
    (32, 143, "B.Tech in Electronics and Communication Engineering with Specialization in Data Science", "B.Tech"),
    (33, 147, "B.Tech in Electronics and Computer Engineering", "B.Tech"),
    (34, 151, "B.Tech in Electronics Engineering (VLSI Design and Technology)", "B.Tech"),
    (35, 157, "B.Tech in Electrical and Electronics Engineering", "B.Tech"),
    (36, 160, "B.Tech in Electric Vehicle Technology", "B.Tech"),
    (37, 165, "B.Tech in Electronics and Instrumentation Engineering", "B.Tech"),
    (38, 170, "B.Tech in Food Technology", "B.Tech"),
    (39, 175, "B.Tech in Mechanical Engineering", "B.Tech"),
    (40, 179, "B.Tech in Mechanical Engineering with Specialization in Artificial Intelligence and Machine Learning", "B.Tech"),
    (41, 183, "B.Tech in Mechanical Engineering with Specialization in Automation and Robotics", "B.Tech"),
    (42, 187, "B.Tech in Mechatronics Engineering", "B.Tech"),
    (43, 190, "B.Tech in Mechatronics Engineering with Specialization in Autonomous Driving Technology", "B.Tech"),
    (44, 193, "B.Tech in Mechatronics Engineering with Specialization in Immersive Technologies", "B.Tech"),
    (45, 196, "B.Tech in Mechatronics Engineering with Specialization in Industrial IoT and Systems Engineering", "B.Tech"),
    (46, 200, "B.Tech in Mechatronics Engineering with Specialization in Robotics", "B.Tech"),
    (47, 205, "B.Tech in Nanotechnology", "B.Tech"),
    (48, 211, "Integrated M.Tech in Artificial Intelligence", "Integrated M.Tech"),
    (49, 217, "Integrated M.Tech in Computer Science and Engineering", "Integrated M.Tech"),
    (50, 223, "Integrated M.Tech in Computer Science and Engineering with Specialization in Cognitive Computing", "Integrated M.Tech"),
    (51, 227, "Integrated M.Tech in Computer Science and Engineering with Specialization in Cyber Security & Digital Forensics", "Integrated M.Tech"),
    (52, 231, "Integrated M.Tech in Computer Science and Engineering with Specialization in Data Science", "Integrated M.Tech"),
    (53, 236, "Integrated M.Tech in Electronics and Communication Engineering with Specialization in Microelectronics System Design", "Integrated M.Tech"),
    (54, 240, "Integrated M.Tech in Materials Science & Engineering", "Integrated M.Tech"),
    (55, 244, "Integrated M.Tech in Mechanical Engineering", "Integrated M.Tech")
]

all_programs_data = {}
all_allocations = []
unique_courses = {}

for prog_idx, (prog_num, plan_page, prog_name, degree_type) in enumerate(PROGRAM_REGISTRY):
    # Maximum semesters: 8 for B.Tech, 10 for Integrated M.Tech
    max_sems = 10 if degree_type.startswith("Integrated") else 8
    
    prog_entry = {
        "program_id": prog_num,
        "program_name": prog_name,
        "degree_type": degree_type,
        "implementation_plan_page": plan_page,
        "semesters": {str(s): [] for s in range(1, max_sems + 1)}
    }
    
    # Check page plan_page - 1 (0-indexed) and potentially plan_page if needed
    # For each program, we parse until semester count reaches max_sems or next plan starts
    next_page_limit = PROGRAM_REGISTRY[prog_idx + 1][1] if prog_idx + 1 < len(PROGRAM_REGISTRY) else len(doc)
    
    pages_to_scan = [plan_page - 1]
    # If the next plan is not immediately on next page, can also check plan_page
    if plan_page < next_page_limit:
        pages_to_scan.append(plan_page)
        
    current_sem = 1
    seen_in_prog = set()
    
    for p_idx in pages_to_scan:
        page = doc[p_idx]
        text = page.get_text()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        
        # Stop scanning if we hit the next program header
        if p_idx > (plan_page - 1) and any("Implementation Plan" in l or "Implementation plan" in l for l in lines[:10]):
            break
            
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Detect Semester header
            m_sem = re.search(r"Semester[^\w]*([IVX1-8]+)", line, re.IGNORECASE)
            if m_sem:
                s_val = m_sem.group(1).lower()
                if s_val in sem_roman_map:
                    current_sem = sem_roman_map[s_val]
                i += 1
                continue
                
            # Match course code
            m_code = re.match(r"^(21[A-Z]{2,4}\d{3}[A-Z]?)(?:\s+(.*))?$", line)
            if m_code and not line.startswith("Semester"):
                c_code = m_code.group(1)
                title = m_code.group(2) if m_code.group(2) else ""
                
                # If title is empty on this line, look ahead
                idx = i + 1
                if not title and idx < len(lines):
                    next_l = lines[idx]
                    if not re.match(r"^21[A-Z]{2,4}\d{3}", next_l) and not "Semester" in next_l and not re.match(r"^\d(?:\s+\d)*$", next_l):
                        title = next_l
                        idx += 1
                        if idx < len(lines):
                            next2 = lines[idx]
                            if not re.match(r"^21[A-Z]{2,4}\d{3}", next2) and not "Semester" in next2 and not re.match(r"^\d(?:\s+\d)*$", next2) and len(next2.split()) <= 4:
                                title += " " + next2
                                idx += 1
                                
                # Look for credits / L-T-P-C
                l_val, t_val, p_val, c_val = 3, 0, 0, 3
                num_scans = 0
                while idx < len(lines) and num_scans < 4:
                    cand = lines[idx]
                    nums = [int(n) for n in re.findall(r"\b\d+\b", cand)]
                    if len(nums) >= 3:
                        l_val, t_val, p_val = nums[0], nums[1], nums[2]
                        if len(nums) >= 4:
                            c_val = nums[3]
                        elif idx + 1 < len(lines) and re.match(r"^\d+$", lines[idx+1]):
                            c_val = int(lines[idx+1])
                        break
                    elif len(nums) == 1 and idx + 3 < len(lines):
                        # Consecutive lines of single digits
                        try:
                            n1 = int(lines[idx])
                            n2 = int(lines[idx+1])
                            n3 = int(lines[idx+2])
                            n4 = int(lines[idx+3])
                            l_val, t_val, p_val, c_val = n1, n2, n3, n4
                            break
                        except ValueError:
                            pass
                    idx += 1
                    num_scans += 1
                    
                cat_char = c_code[4] if len(c_code) > 4 else "C"
                category = cat_map.get(cat_char, "Professional Core")
                
                # Clean title
                clean_title = title.strip().title() if title else c_code
                clean_title = re.sub(r"\s+", " ", clean_title)
                
                alloc_key = (prog_name, current_sem, c_code)
                if alloc_key not in seen_in_prog:
                    seen_in_prog.add(alloc_key)
                    
                    item = {
                        "program_id": prog_num,
                        "program_name": prog_name,
                        "degree_type": degree_type,
                        "semester": current_sem,
                        "academic_year": (current_sem + 1) // 2,
                        "course_code": c_code,
                        "course_name": clean_title,
                        "category": category,
                        "credits": c_val,
                        "ltpc": f"{l_val}-{t_val}-{p_val}-{c_val}",
                        "page_number": p_idx + 1,
                        "regulation": "2021"
                    }
                    
                    all_allocations.append(item)
                    prog_entry["semesters"][str(current_sem)].append(item)
                    
                    if c_code not in unique_courses:
                        unique_courses[c_code] = {
                            "code": c_code,
                            "name": clean_title,
                            "category": category,
                            "primary_semester": current_sem,
                            "academic_year": (current_sem + 1) // 2,
                            "credits": c_val,
                            "ltpc": f"{l_val}-{t_val}-{p_val}-{c_val}",
                            "programs": [prog_name],
                            "regulation": "2021",
                            "is_official": True
                        }
                    else:
                        if prog_name not in unique_courses[c_code]["programs"]:
                            unique_courses[c_code]["programs"].append(prog_name)
                            
            i += 1
            
    all_programs_data[prog_name] = prog_entry

# Compile Summary Report
report_lines = [
    "=" * 70,
    "SRMIST REGULATIONS 2021 UNIFIED CURRICULA EXTRACTION REPORT",
    "=" * 70,
    f"Total Degree Programmes Processed: {len(all_programs_data)}",
    f"Total Course-Semester Allocations Extracted: {len(all_allocations)}",
    f"Total Unique Official Courses Extracted: {len(unique_courses)}",
    "",
    "--- Sample Programs Breakdown ---"
]

sample_progs = [
    "B.Tech in Computer Science and Engineering",
    "B.Tech in Artificial Intelligence",
    "B.Tech in Computer Science and Engineering with Specialization in Artificial Intelligence and Machine Learning",
    "B.Tech in Aerospace Engineering",
    "B.Tech in Mechanical Engineering",
    "Integrated M.Tech in Artificial Intelligence"
]

for p_name in sample_progs:
    if p_name in all_programs_data:
        p_data = all_programs_data[p_name]
        report_lines.append(f"\n{p_name} (Page {p_data['implementation_plan_page']}):")
        for s in range(1, 9 if p_data['degree_type'] == "B.Tech" else 11):
            s_courses = p_data["semesters"].get(str(s), [])
            c_codes = [c["course_code"] for c in s_courses]
            report_lines.append(f"  Semester {s} ({len(c_codes)} courses): {', '.join(c_codes[:6])}{'...' if len(c_codes) > 6 else ''}")

# Write summary to txt
out_summary = "campus_knowledge_server/data/courses/curricula_extraction_summary.txt"
with open(out_summary, "w", encoding="utf-8") as f:
    f.write("\n".join(report_lines) + "\n")

# Write master JSON
out_json = "campus_knowledge_server/data/courses/curricula_semester_master.json"
with open(out_json, "w", encoding="utf-8") as f:
    json.dump({
        "metadata": {
            "source": "SRMIST Regulations 2021 Volume 1 Unified Curriculum",
            "pdf_file": "academic-curricula-2021.pdf",
            "total_programs": len(all_programs_data),
            "total_allocations": len(all_allocations),
            "total_unique_courses": len(unique_courses)
        },
        "programs": all_programs_data,
        "unique_courses": list(unique_courses.values())
    }, f, indent=2)

print(f"Extraction successful: {len(all_programs_data)} programs, {len(all_allocations)} allocations, {len(unique_courses)} unique courses.")

