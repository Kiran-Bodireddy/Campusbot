import json
import csv
import re
import os

courses_master_path = "campus_knowledge_server/data/courses/courses_master.json"
courses_csv_path = "campus_knowledge_server/data/courses/courses_master.csv"
curricula_path = "campus_knowledge_server/data/courses/curricula_semester_master.json"

DEPT_PREFIX_MAP = {
    "CSC": ("School of Computing", "Faculty of Engineering & Technology"),
    "CSO": ("School of Computing", "Faculty of Engineering & Technology"),
    "CSP": ("School of Computing", "Faculty of Engineering & Technology"),
    "CSS": ("School of Computing", "Faculty of Engineering & Technology"),
    "AIC": ("Department of Artificial Intelligence & Machine Learning", "Faculty of Engineering & Technology"),
    "AIO": ("Department of Artificial Intelligence & Machine Learning", "Faculty of Engineering & Technology"),
    "AIP": ("Department of Artificial Intelligence & Machine Learning", "Faculty of Engineering & Technology"),
    "AIS": ("Department of Artificial Intelligence & Machine Learning", "Faculty of Engineering & Technology"),
    "ASC": ("Department of Aerospace Engineering", "Faculty of Engineering & Technology"),
    "ASO": ("Department of Aerospace Engineering", "Faculty of Engineering & Technology"),
    "ASP": ("Department of Aerospace Engineering", "Faculty of Engineering & Technology"),
    "ASS": ("Department of Aerospace Engineering", "Faculty of Engineering & Technology"),
    "AUC": ("Department of Automobile Engineering", "Faculty of Engineering & Technology"),
    "AUO": ("Department of Automobile Engineering", "Faculty of Engineering & Technology"),
    "AUP": ("Department of Automobile Engineering", "Faculty of Engineering & Technology"),
    "AUS": ("Department of Automobile Engineering", "Faculty of Engineering & Technology"),
    "BMC": ("Department of Biomedical Engineering", "Faculty of Engineering & Technology"),
    "BMO": ("Department of Biomedical Engineering", "Faculty of Engineering & Technology"),
    "BMP": ("Department of Biomedical Engineering", "Faculty of Engineering & Technology"),
    "BMS": ("Department of Biomedical Engineering", "Faculty of Engineering & Technology"),
    "BTC": ("Department of Biotechnology", "Faculty of Engineering & Technology"),
    "BTB": ("Department of Biotechnology", "Faculty of Engineering & Technology"),
    "BTO": ("Department of Biotechnology", "Faculty of Engineering & Technology"),
    "BTP": ("Department of Biotechnology", "Faculty of Engineering & Technology"),
    "BTS": ("Department of Biotechnology", "Faculty of Engineering & Technology"),
    "CEC": ("Department of Civil Engineering", "Faculty of Engineering & Technology"),
    "CEO": ("Department of Civil Engineering", "Faculty of Engineering & Technology"),
    "CEP": ("Department of Civil Engineering", "Faculty of Engineering & Technology"),
    "CES": ("Department of Civil Engineering", "Faculty of Engineering & Technology"),
    "CHC": ("Department of Chemical Engineering", "Faculty of Engineering & Technology"),
    "CHO": ("Department of Chemical Engineering", "Faculty of Engineering & Technology"),
    "CHP": ("Department of Chemical Engineering", "Faculty of Engineering & Technology"),
    "CHS": ("Department of Chemical Engineering", "Faculty of Engineering & Technology"),
    "ECC": ("Department of Electronics and Communication Engineering", "Faculty of Engineering & Technology"),
    "ECO": ("Department of Electronics and Communication Engineering", "Faculty of Engineering & Technology"),
    "ECP": ("Department of Electronics and Communication Engineering", "Faculty of Engineering & Technology"),
    "ECS": ("Department of Electronics and Communication Engineering", "Faculty of Engineering & Technology"),
    "EEC": ("Department of Electrical and Electronics Engineering", "Faculty of Engineering & Technology"),
    "EEO": ("Department of Electrical and Electronics Engineering", "Faculty of Engineering & Technology"),
    "EEP": ("Department of Electrical and Electronics Engineering", "Faculty of Engineering & Technology"),
    "EES": ("Department of Electrical and Electronics Engineering", "Faculty of Engineering & Technology"),
    "EIC": ("Department of Electronics and Instrumentation Engineering", "Faculty of Engineering & Technology"),
    "EIO": ("Department of Electronics and Instrumentation Engineering", "Faculty of Engineering & Technology"),
    "EIP": ("Department of Electronics and Instrumentation Engineering", "Faculty of Engineering & Technology"),
    "EIS": ("Department of Electronics and Instrumentation Engineering", "Faculty of Engineering & Technology"),
    "EVC": ("Department of Environmental Engineering", "Faculty of Engineering & Technology"),
    "EVO": ("Department of Environmental Engineering", "Faculty of Engineering & Technology"),
    "EVP": ("Department of Environmental Engineering", "Faculty of Engineering & Technology"),
    "EVS": ("Department of Environmental Engineering", "Faculty of Engineering & Technology"),
    "FPC": ("Department of Food Process Engineering", "Faculty of Engineering & Technology"),
    "FPO": ("Department of Food Process Engineering", "Faculty of Engineering & Technology"),
    "FPP": ("Department of Food Process Engineering", "Faculty of Engineering & Technology"),
    "FPS": ("Department of Food Process Engineering", "Faculty of Engineering & Technology"),
    "MEC": ("Department of Mechanical Engineering", "Faculty of Engineering & Technology"),
    "MEO": ("Department of Mechanical Engineering", "Faculty of Engineering & Technology"),
    "MEP": ("Department of Mechanical Engineering", "Faculty of Engineering & Technology"),
    "MES": ("Department of Mechanical Engineering", "Faculty of Engineering & Technology"),
    "MHC": ("Department of Mechatronics Engineering", "Faculty of Engineering & Technology"),
    "MHO": ("Department of Mechatronics Engineering", "Faculty of Engineering & Technology"),
    "MHP": ("Department of Mechatronics Engineering", "Faculty of Engineering & Technology"),
    "MHS": ("Department of Mechatronics Engineering", "Faculty of Engineering & Technology"),
    "NTC": ("Department of Nanotechnology", "Faculty of Engineering & Technology"),
    "NTO": ("Department of Nanotechnology", "Faculty of Engineering & Technology"),
    "NTP": ("Department of Nanotechnology", "Faculty of Engineering & Technology"),
    "NTS": ("Department of Nanotechnology", "Faculty of Engineering & Technology"),
    "MAB": ("Department of Mathematics", "Faculty of Science and Humanities"),
    "PYB": ("Department of Physics and Nanotechnology", "Faculty of Science and Humanities"),
    "CYB": ("Department of Chemistry", "Faculty of Science and Humanities"),
    "CYM": ("Department of Chemistry", "Faculty of Science and Humanities"),
    "LEH": ("Department of English and Foreign Languages", "Faculty of Science and Humanities"),
    "LEM": ("Department of English and Foreign Languages", "Faculty of Science and Humanities"),
    "PDM": ("Career Development Centre", "Faculty of Science and Humanities"),
    "PDH": ("Career Development Centre", "Faculty of Science and Humanities"),
    "GNH": ("College of Engineering and Technology", "Faculty of Engineering & Technology"),
    "GNM": ("College of Engineering and Technology", "Faculty of Engineering & Technology"),
    "GNP": ("College of Engineering and Technology", "Faculty of Engineering & Technology"),
    "GNS": ("College of Engineering and Technology", "Faculty of Engineering & Technology"),
    "DCS": ("College of Engineering and Technology", "Faculty of Engineering & Technology")
}

with open(courses_master_path, "r", encoding="utf-8") as f:
    existing_courses = json.load(f)

with open(curricula_path, "r", encoding="utf-8") as f:
    curricula_data = json.load(f)

# Build semester and program mappings for all courses in curricula
course_allocations = {}
for prog_name, p_info in curricula_data["programs"].items():
    for sem_str, c_list in p_info["semesters"].items():
        sem_num = int(sem_str)
        for c in c_list:
            code = c["course_code"]
            if code not in course_allocations:
                course_allocations[code] = {
                    "programs": [],
                    "semesters": {}, # prog -> sem
                    "sem_list": [],
                    "credits": c["credits"],
                    "ltpc": c["ltpc"],
                    "name": c["course_name"],
                    "category": c["category"],
                    "page_number": c["page_number"]
                }
            if prog_name not in course_allocations[code]["programs"]:
                course_allocations[code]["programs"].append(prog_name)
            course_allocations[code]["semesters"][prog_name] = sem_num
            course_allocations[code]["sem_list"].append(sem_num)

existing_by_code = {c["code"]: c for c in existing_courses}

# 1. Enrich existing Volume 20 courses with Volume 1 program and semester allocations
for code, c in existing_by_code.items():
    if code in course_allocations:
        alloc = course_allocations[code]
        c["programs"] = alloc["programs"]
        c["semesters_offered"] = alloc["semesters"]
        primary_sem = min(alloc["sem_list"])
        c["primary_semester"] = primary_sem
        c["academic_year"] = (primary_sem + 1) // 2
        c["semester_range"] = f"Semester {primary_sem} (Year {c['academic_year']} Core / Mandatory)" if len(set(alloc["sem_list"])) == 1 else f"Semesters {min(alloc['sem_list'])}-{max(alloc['sem_list'])}"
    else:
        # Open elective not directly bound to a single program
        c["programs"] = ["University-Wide Open Elective Pool (All Engineering Programmes)"]
        c["semesters_offered"] = {"All Engineering Programmes": 5}
        c["primary_semester"] = 5
        c["academic_year"] = 3

# 2. Add courses that appear ONLY in Volume 1 (core subjects like 21CSC201J DSA, 21CSC202J OS, etc.)
new_courses = []
next_id = len(existing_courses) + 1

for code, alloc in course_allocations.items():
    if code not in existing_by_code:
        # Determine department and faculty from prefix
        prefix3 = code[2:5] if len(code) >= 5 else "CSC"
        dept_info = DEPT_PREFIX_MAP.get(prefix3, ("College of Engineering and Technology", "Faculty of Engineering & Technology"))
        dept_name, fac_name = dept_info
        
        primary_sem = min(alloc["sem_list"])
        acad_year = (primary_sem + 1) // 2
        
        new_entry = {
            "id": f"CRS-{next_id:04d}",
            "code": code,
            "name": alloc["name"],
            "category": alloc["category"],
            "department": dept_name,
            "faculty": fac_name,
            "credits": alloc["credits"],
            "ltpc": alloc["ltpc"],
            "level": "UG",
            "semester_range": f"Semester {primary_sem} (Year {acad_year} Core / Mandatory)" if len(set(alloc["sem_list"])) == 1 else f"Semesters {min(alloc['sem_list'])}-{max(alloc['sem_list'])}",
            "primary_semester": primary_sem,
            "academic_year": acad_year,
            "programs": alloc["programs"],
            "semesters_offered": alloc["semesters"],
            "prerequisites": [],
            "prerequisite_raw": "Nil",
            "description": f"Core curriculum subject for {', '.join(alloc['programs'][:2])} under SRMIST Regulations 2021 Unified Curriculum.",
            "regulation": "2021",
            "page_number": alloc["page_number"],
            "is_official": True
        }
        new_courses.append(new_entry)
        next_id += 1

merged_all_courses = list(existing_by_code.values()) + new_courses

# Save to courses_master.json
with open(courses_master_path, "w", encoding="utf-8") as f:
    json.dump(merged_all_courses, f, indent=2)

# Save to courses_master.csv
csv_fields = [
    "id", "code", "name", "category", "department", "faculty",
    "credits", "ltpc", "level", "semester_range", "primary_semester",
    "academic_year", "prerequisites", "regulation", "page_number", "is_official"
]

with open(courses_csv_path, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=csv_fields)
    writer.writeheader()
    for c in merged_all_courses:
        row = {k: c.get(k, "") for k in csv_fields}
        if isinstance(row["prerequisites"], list):
            row["prerequisites"] = ";".join(row["prerequisites"])
        writer.writerow(row)

print(f"Successfully merged courses catalog:")
print(f"  Volume 20 courses: {len(existing_courses)}")
print(f"  New Volume 1 courses added: {len(new_courses)}")
print(f"  Total official courses catalog: {len(merged_all_courses)}")

