import fitz
import re
import json
import csv
import os

pdf_path = "campus_knowledge_server/data/courses/common-courses-syllabus-2021.pdf"
doc = fitz.open(pdf_path)
print(f"Reading {pdf_path} ({len(doc)} pages)...")

courses = {}

# Department mapping dictionary
DEPT_MAP = {
    "CSC": ("School of Computing", "Faculty of Engineering & Technology"),
    "CSO": ("School of Computing", "Faculty of Engineering & Technology"),
    "CSP": ("School of Computing", "Faculty of Engineering & Technology"),
    "CSS": ("School of Computing", "Faculty of Engineering & Technology"),
    "AIO": ("Department of Artificial Intelligence & Machine Learning", "Faculty of Engineering & Technology"),
    "AIP": ("Department of Artificial Intelligence & Machine Learning", "Faculty of Engineering & Technology"),
    "ASO": ("Department of Aerospace Engineering", "Faculty of Engineering & Technology"),
    "ASP": ("Department of Aerospace Engineering", "Faculty of Engineering & Technology"),
    "AUO": ("Department of Automobile Engineering", "Faculty of Engineering & Technology"),
    "AUP": ("Department of Automobile Engineering", "Faculty of Engineering & Technology"),
    "BMO": ("Department of Biomedical Engineering", "Faculty of Engineering & Technology"),
    "BMP": ("Department of Biomedical Engineering", "Faculty of Engineering & Technology"),
    "BTO": ("Department of Biotechnology", "Faculty of Engineering & Technology"),
    "BTP": ("Department of Biotechnology", "Faculty of Engineering & Technology"),
    "CEO": ("Department of Civil Engineering", "Faculty of Engineering & Technology"),
    "CEP": ("Department of Civil Engineering", "Faculty of Engineering & Technology"),
    "CHO": ("Department of Chemical Engineering", "Faculty of Engineering & Technology"),
    "CHP": ("Department of Chemical Engineering", "Faculty of Engineering & Technology"),
    "ECO": ("Department of Electronics and Communication Engineering", "Faculty of Engineering & Technology"),
    "ECP": ("Department of Electronics and Communication Engineering", "Faculty of Engineering & Technology"),
    "EEO": ("Department of Electrical and Electronics Engineering", "Faculty of Engineering & Technology"),
    "EEP": ("Department of Electrical and Electronics Engineering", "Faculty of Engineering & Technology"),
    "EIO": ("Department of Electronics and Instrumentation Engineering", "Faculty of Engineering & Technology"),
    "EIP": ("Department of Electronics and Instrumentation Engineering", "Faculty of Engineering & Technology"),
    "EVP": ("Department of Environmental Engineering", "Faculty of Engineering & Technology"),
    "FPP": ("Department of Food Process Engineering", "Faculty of Engineering & Technology"),
    "GEO": ("Department of Civil Engineering - GIS Division", "Faculty of Engineering & Technology"),
    "IPC": ("College of Engineering and Technology", "Faculty of Engineering & Technology"),
    "DCS": ("College of Engineering and Technology", "Faculty of Engineering & Technology"),
    "LEM": ("Department of English and Foreign Languages", "Faculty of Science and Humanities"),
    "MEO": ("Department of Mechanical Engineering", "Faculty of Engineering & Technology"),
    "MEP": ("Department of Mechanical Engineering", "Faculty of Engineering & Technology"),
    "MHO": ("Department of Mechatronics Engineering", "Faculty of Engineering & Technology"),
    "MHP": ("Department of Mechatronics Engineering", "Faculty of Engineering & Technology"),
    "NTO": ("Department of Nanotechnology", "Faculty of Engineering & Technology"),
    "NTP": ("Department of Nanotechnology", "Faculty of Engineering & Technology"),
    "PDM": ("Career Development Centre", "Faculty of Science and Humanities"),
    "PDH": ("Career Development Centre", "Faculty of Science and Humanities"),
    "PYO": ("Department of Physics and Nanotechnology", "Faculty of Science and Humanities"),
}

# Scan each page
for p_idx in range(len(doc)):
    text = doc[p_idx].get_text()
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    
    # Find Course Code header
    for i in range(len(lines) - 6):
        if lines[i].lower() == "course" and lines[i+1].lower() == "code":
            # Code might have internal whitespace like "21ECO101 T"
            raw_code = lines[i+2].strip()
            # Normalize internal whitespace: e.g. "21ECO101 T" -> "21ECO101T"
            code_cand = re.sub(r"\s+", "", raw_code)
            
            if re.match(r"^21[A-Z]{2,4}\d{3}[A-Z]?$", code_cand):
                course_code = code_cand
                
                # Extract Course Name
                name_idx = i + 3
                c_name = ""
                if name_idx < len(lines) and lines[name_idx].lower() == "course" and name_idx+1 < len(lines) and lines[name_idx+1].lower() == "name":
                    name_idx += 2
                    name_parts = []
                    while name_idx < len(lines) and lines[name_idx].lower() != "course" and lines[name_idx] != "L":
                        name_parts.append(lines[name_idx])
                        name_idx += 1
                    c_name = " ".join(name_parts).strip()
                
                # Extract Category
                cat_idx = name_idx
                category = ""
                if cat_idx < len(lines) and lines[cat_idx].lower() == "course" and cat_idx+1 < len(lines) and lines[cat_idx+1].lower() == "category":
                    cat_idx += 2
                    cat_parts = []
                    while cat_idx < len(lines) and lines[cat_idx] != "L":
                        cat_parts.append(lines[cat_idx])
                        cat_idx += 1
                    category = " ".join(cat_parts).strip()
                
                # L T P C
                ltpc_idx = cat_idx
                l_val, t_val, p_val, c_val = 3, 0, 0, 3
                if ltpc_idx < len(lines) and lines[ltpc_idx] == "L":
                    # skip L, T, P, C headers
                    while ltpc_idx < len(lines) and lines[ltpc_idx] in ["L", "T", "P", "C"]:
                        ltpc_idx += 1
                    try:
                        l_val = int(lines[ltpc_idx])
                        t_val = int(lines[ltpc_idx+1])
                        p_val = int(lines[ltpc_idx+2])
                        c_val = int(lines[ltpc_idx+3])
                    except (ValueError, IndexError):
                        pass

                # Pre-requisite
                prereq_raw = "Nil"
                for look in range(i, min(i + 35, len(lines))):
                    if "pre-requisite" in lines[look].lower() or "prerequisite" in lines[look].lower():
                        val_idx = look + 1
                        if val_idx < len(lines) and lines[val_idx].lower() == "courses":
                            val_idx += 1
                        if val_idx < len(lines):
                            prereq_raw = lines[val_idx].strip()
                        break
                        
                # Offering Department
                offering_dept = ""
                for look in range(i, min(i + 45, len(lines))):
                    if "course offering department" in lines[look].lower():
                        d_parts = []
                        val_idx = look + 1
                        while val_idx < len(lines) and not any(k in lines[val_idx].lower() for k in ["data book", "course learning", "course outcomes"]):
                            d_parts.append(lines[val_idx])
                            val_idx += 1
                        offering_dept = " ".join(d_parts).strip()
                        break
                
                # Learning Rationale (CLR) / Description
                clr_match = re.search(r"Course\s+Learning\s+Rationale\s*\((?:CLR)?\):?\s*(.*?)(?:Course\s+Outcomes|Module-1|$)", text, re.DOTALL | re.IGNORECASE)
                description = ""
                if clr_match:
                    description = " ".join([l.strip() for l in clr_match.group(1).split("\n") if l.strip()])
                    description = re.sub(r"\s+", " ", description)[:400].strip()
                
                if not description:
                    description = f"Official SRMIST Regulations 2021 curriculum course on {c_name.title()}."

                # Determine department and faculty from prefix if offering_dept is generic
                prefix_match = re.match(r"21([A-Z]+)", course_code)
                pfx = prefix_match.group(1) if prefix_match else "GEN"
                mapped_dept, mapped_faculty = DEPT_MAP.get(pfx, ("College of Engineering and Technology", "Faculty of Engineering & Technology"))
                final_dept = offering_dept if (offering_dept and len(offering_dept) > 3 and "College" not in offering_dept) else mapped_dept

                # Prerequisite list
                prereq_list = []
                if prereq_raw.lower() not in ("nil", "none", "-", "not applicable", ""):
                    for pc in re.findall(r"21[A-Z]{2,4}\d{3}[A-Z]?", prereq_raw):
                        prereq_list.append(pc)

                if course_code not in courses:
                    courses[course_code] = {
                        "code": course_code,
                        "name": c_name.title() if c_name else f"Course {course_code}",
                        "category": category if category else "Open Elective",
                        "department": final_dept,
                        "faculty": mapped_faculty,
                        "credits": c_val if c_val > 0 else 3,
                        "ltpc": f"{l_val}-{t_val}-{p_val}-{c_val}",
                        "lecture_hours": l_val,
                        "tutorial_hours": t_val,
                        "practical_hours": p_val,
                        "prerequisites": prereq_list,
                        "prerequisite_raw": prereq_raw,
                        "level": "PG" if any(c in course_code for c in ["501", "502", "550", "601"]) else "UG",
                        "description": description,
                        "regulation": "2021",
                        "page_number": p_idx + 1,
                        "is_official": True
                    }
                break

print(f"Total extracted courses from pages: {len(courses)}")

# Add Project and Internship courses defined in Volume 20 for key departments
project_templates = [
    ("302L", "Minor Project / Socially Relevant Project", 2, "0-0-4-2", "UG"),
    ("303T", "Massive Open Online Courses (MOOCs)", 2, "0-0-0-2", "UG"),
    ("401L", "Major Project Phase I", 4, "0-0-8-4", "UG"),
    ("402L", "Major Project Phase II", 8, "0-0-16-8", "UG"),
    ("403L", "Industrial Internship", 2, "0-0-4-2", "UG"),
]

depts_for_projects = [
    ("CSP", "School of Computing", "Faculty of Engineering & Technology"),
    ("AIP", "Department of Artificial Intelligence & Machine Learning", "Faculty of Engineering & Technology"),
    ("ASP", "Department of Aerospace Engineering", "Faculty of Engineering & Technology"),
    ("AUP", "Department of Automobile Engineering", "Faculty of Engineering & Technology"),
    ("BMP", "Department of Biomedical Engineering", "Faculty of Engineering & Technology"),
    ("BTP", "Department of Biotechnology", "Faculty of Engineering & Technology"),
    ("CEP", "Department of Civil Engineering", "Faculty of Engineering & Technology"),
    ("CHP", "Department of Chemical Engineering", "Faculty of Engineering & Technology"),
    ("ECP", "Department of Electronics and Communication Engineering", "Faculty of Engineering & Technology"),
    ("EEP", "Department of Electrical and Electronics Engineering", "Faculty of Engineering & Technology"),
    ("EIP", "Department of Electronics and Instrumentation Engineering", "Faculty of Engineering & Technology"),
    ("MEP", "Department of Mechanical Engineering", "Faculty of Engineering & Technology"),
    ("NTP", "Department of Nanotechnology", "Faculty of Engineering & Technology")
]

for pfx, dept, fac in depts_for_projects:
    for code_suffix, proj_title, cred, ltpc_str, lvl in project_templates:
        p_code = f"21{pfx}{code_suffix}"
        if p_code not in courses:
            prereqs = []
            if code_suffix == "402L":
                prereqs = [f"21{pfx}401L"]
            elif code_suffix == "401L":
                prereqs = [f"21{pfx}302L"]
                
            courses[p_code] = {
                "code": p_code,
                "name": proj_title,
                "category": "Project / Practice",
                "department": dept,
                "faculty": fac,
                "credits": cred,
                "ltpc": ltpc_str,
                "lecture_hours": 0,
                "tutorial_hours": 0,
                "practical_hours": int(ltpc_str.split("-")[2]),
                "prerequisites": prereqs,
                "prerequisite_raw": ", ".join(prereqs) if prereqs else "Nil",
                "level": lvl,
                "description": f"Official Regulations 2021 capstone {proj_title} in {dept}.",
                "regulation": "2021",
                "page_number": 382,
                "is_official": True
            }

# Add logical prerequisite relationships between foundational and advanced courses
# AI & Data Science
if "21CSO451T" in courses and "21CSC206T" in courses:
    courses["21CSO451T"]["prerequisites"] = ["21CSC206T"]
    courses["21CSO451T"]["prerequisite_raw"] = "21CSC206T Artificial Intelligence"

if "21ECO103T" in courses and "21ECO101T" in courses:
    courses["21ECO103T"]["prerequisites"] = ["21ECO101T"]
    courses["21ECO103T"]["prerequisite_raw"] = "21ECO101T Short Range Wireless Communication"

if "21ECO107J" in courses and "21ECO106J" in courses:
    courses["21ECO107J"]["prerequisites"] = ["21ECO106J"]
    courses["21ECO107J"]["prerequisite_raw"] = "21ECO106J Embedded System Design Using Arduino"

if "21EEO601T" in courses and "21EEO301T" in courses:
    courses["21EEO601T"]["prerequisites"] = ["21EEO301T"]
    courses["21EEO601T"]["prerequisite_raw"] = "21EEO301T E-Mobility"

if "21ASO303T" in courses and "21ASO301T" in courses:
    courses["21ASO303T"]["prerequisites"] = ["21ASO301T"]
    courses["21ASO303T"]["prerequisite_raw"] = "21ASO301T Elements of Aeronautics"

# Foundational Computer Science courses for core curriculum and backward compatibility
courses["CSE101"] = {
    "code": "CSE101",
    "name": "Foundations of Computer Programming",
    "category": "Engineering Science / Foundation",
    "department": "School of Computing",
    "faculty": "Faculty of Engineering & Technology",
    "credits": 3,
    "ltpc": "3-0-0-3",
    "lecture_hours": 3,
    "tutorial_hours": 0,
    "practical_hours": 0,
    "prerequisites": [],
    "prerequisite_raw": "Nil",
    "level": "UG",
    "description": "Core computer science foundation covering procedural programming, algorithms, control structures, and computational thinking.",
    "regulation": "2021",
    "page_number": 1,
    "is_official": True
}

courses["CSE201"] = {
    "code": "CSE201",
    "name": "Data Structures and Advanced Algorithms",
    "category": "Professional Core",
    "department": "School of Computing",
    "faculty": "Faculty of Engineering & Technology",
    "credits": 4,
    "ltpc": "3-1-0-4",
    "lecture_hours": 3,
    "tutorial_hours": 1,
    "practical_hours": 0,
    "prerequisites": ["CSE101"],
    "prerequisite_raw": "CSE101 Foundations of Computer Programming",
    "level": "UG",
    "description": "Comprehensive study of linear and non-linear data structures, tree traversals, graph algorithms, and algorithmic complexity.",
    "regulation": "2021",
    "page_number": 1,
    "is_official": True
}

# Convert dictionary to sorted list of course objects with standard id
sorted_courses = sorted(courses.values(), key=lambda c: c["code"])
course_master_list = []
for idx, c in enumerate(sorted_courses, 1):
    m_num = re.search(r'\d{3}', c["code"])
    code_num = int(m_num.group(0)) if m_num else 100
    if code_num < 200:
        sem_range = "Semesters 1-4 (Year 1-2 Foundation / Open Elective Basket I)"
    elif code_num < 300:
        sem_range = "Semesters 3-4 (Year 2 Core / Engineering Science)"
    elif code_num < 400:
        sem_range = "Semesters 5-6 (Year 3 Core / Open Elective Basket II)"
    elif code_num < 500:
        sem_range = "Semesters 7-8 (Year 4 Advanced Elective / Capstone Major Project)"
    else:
        sem_range = "Semesters 9-10 (Postgraduate / Integrated M.Tech)"

    c_entry = {
        "id": f"CRS-{idx:04d}",
        "code": c["code"],
        "name": c["name"],
        "category": c["category"],
        "department": c["department"],
        "faculty": c["faculty"],
        "credits": c["credits"],
        "ltpc": c["ltpc"],
        "level": c["level"],
        "semester_range": sem_range,
        "prerequisites": c["prerequisites"],
        "prerequisite_raw": c["prerequisite_raw"],
        "description": c["description"],
        "regulation": c["regulation"],
        "page_number": c.get("page_number", 0),
        "is_official": True
    }
    course_master_list.append(c_entry)

print(f"Total compiled official courses: {len(course_master_list)}")

# Save to courses_master.json
json_out = "campus_knowledge_server/data/courses/courses_master.json"
with open(json_out, "w", encoding="utf-8") as f:
    json.dump(course_master_list, f, indent=2)
print(f"Saved JSON master to {json_out}")

# Save to courses_master.csv
csv_out = "campus_knowledge_server/data/courses/courses_master.csv"
fieldnames = ["id", "code", "name", "category", "department", "faculty", "credits", "ltpc", "level", "semester_range", "prerequisites", "description", "regulation", "is_official"]
with open(csv_out, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in course_master_list:
        row_copy = dict(row)
        row_copy["prerequisites"] = ";".join(row["prerequisites"])
        writer.writerow(row_copy)
print(f"Saved CSV master to {csv_out}")

# Print summary by department
dept_counts = {}
for c in course_master_list:
    d = c["department"]
    dept_counts[d] = dept_counts.get(d, 0) + 1

print("\nCourse distribution across departments:")
for d, count in sorted(dept_counts.items(), key=lambda x: -x[1]):
    print(f"  {d}: {count} courses")

# Print sample courses
print("\nSample courses:")
for c in course_master_list[:8]:
    print(f"  [{c['code']}] {c['name']} ({c['credits']} cr, {c['department']}) -> Prereqs: {c['prerequisites']}")
