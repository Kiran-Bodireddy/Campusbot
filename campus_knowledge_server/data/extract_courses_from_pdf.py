import fitz
import re
import json

doc = fitz.open("campus_knowledge_server/data/courses/common-courses-syllabus-2021.pdf")
print("Total pages:", len(doc))

extracted_courses = []
seen_codes = set()

for page_idx in range(len(doc)):
    page_text = doc[page_idx].get_text()
    lines = [l.strip() for l in page_text.split("\n") if l.strip()]
    
    # Check if this page starts a course syllabus
    # Look for "Course" followed by "Code" followed by code pattern
    for i in range(len(lines) - 8):
        if lines[i] == "Course" and lines[i+1] == "Code":
            code_cand = lines[i+2].strip()
            # SRM course codes: e.g. 21CSC206T, 21IPC501J, 21ASO301T, etc.
            if re.match(r"^21[A-Z]{2,4}\d{3}[A-Z]?$", code_cand):
                course_code = code_cand
                
                # Course Name
                course_name = ""
                idx = i + 3
                if idx < len(lines) and lines[idx] == "Course" and idx + 1 < len(lines) and lines[idx+1] == "Name":
                    idx += 2
                    name_parts = []
                    while idx < len(lines) and lines[idx] != "Course" and lines[idx] != "L":
                        name_parts.append(lines[idx])
                        idx += 1
                    course_name = " ".join(name_parts)
                
                # Category
                category = ""
                if idx < len(lines) and lines[idx] == "Course" and idx + 1 < len(lines) and lines[idx+1] == "Category":
                    idx += 2
                    cat_parts = []
                    while idx < len(lines) and lines[idx] != "L":
                        cat_parts.append(lines[idx])
                        idx += 1
                    category = " ".join(cat_parts)
                
                # L T P C
                l_val, t_val, p_val, c_val = 0, 0, 0, 0
                if idx < len(lines) and lines[idx] == "L" and idx + 3 < len(lines) and lines[idx+3] == "C":
                    idx += 4
                    try:
                        l_val = int(lines[idx])
                        t_val = int(lines[idx+1])
                        p_val = int(lines[idx+2])
                        c_val = int(lines[idx+3])
                        idx += 4
                    except (ValueError, IndexError):
                        pass
                
                # Prerequisites
                prereq_raw = "Nil"
                while idx < len(lines) and not ("Pre-requisite" in lines[idx] or "Prerequisite" in lines[idx]):
                    if idx > i + 35: # don't run away
                        break
                    idx += 1
                if idx < len(lines) and ("Pre-requisite" in lines[idx] or "Prerequisite" in lines[idx]):
                    idx += 1
                    if idx < len(lines) and lines[idx] == "Courses":
                        idx += 1
                    if idx < len(lines):
                        prereq_raw = lines[idx]
                        idx += 1
                
                # Co-requisites
                coreq_raw = "Nil"
                while idx < len(lines) and not ("Co-requisite" in lines[idx] or "Co- requisite" in lines[idx]):
                    if idx > i + 45:
                        break
                    idx += 1
                if idx < len(lines) and ("Co-requisite" in lines[idx] or "Co- requisite" in lines[idx]):
                    idx += 1
                    if idx < len(lines) and lines[idx] == "Courses":
                        idx += 1
                    if idx < len(lines):
                        coreq_raw = lines[idx]
                        idx += 1
                        
                # Offering Department
                offering_dept = ""
                while idx < len(lines) and lines[idx] != "Course Offering Department":
                    if idx > i + 55:
                        break
                    idx += 1
                if idx < len(lines) and lines[idx] == "Course Offering Department":
                    idx += 1
                    dept_parts = []
                    while idx < len(lines) and not ("Data Book" in lines[idx] or "Course Learning" in lines[idx] or "Course Outcomes" in lines[idx]):
                        dept_parts.append(lines[idx])
                        idx += 1
                    offering_dept = " ".join(dept_parts)
                
                # Description / Course Learning Rationale
                clr_text = ""
                clr_match = re.search(r"Course\s+Learning\s+Rationale\s*\((?:CLR)?\):?\s*(.*?)(?:Course\s+Outcomes|Module-1|$)", page_text, re.DOTALL | re.IGNORECASE)
                if clr_match:
                    clr_text = " ".join([l.strip() for l in clr_match.group(1).split("\n") if l.strip()])
                    # clean up excessive whitespace
                    clr_text = re.sub(r"\s+", " ", clr_text)[:500]
                
                # Parse prerequisites list
                prereq_list = []
                if prereq_raw and prereq_raw.lower() not in ("nil", "none", "-", "not applicable"):
                    # Find any course codes in prereq_raw
                    pcodes = re.findall(r"21[A-Z]{2,4}\d{3}[A-Z]?", prereq_raw)
                    if pcodes:
                        prereq_list = pcodes
                    else:
                        prereq_list = [prereq_raw.strip()]

                course_rec = {
                    "course_code": course_code,
                    "course_name": course_name.title(),
                    "category": category,
                    "credits": c_val if c_val > 0 else 3,
                    "ltpc": f"{l_val}-{t_val}-{p_val}-{c_val}",
                    "lecture_hours": l_val,
                    "tutorial_hours": t_val,
                    "practical_hours": p_val,
                    "prerequisites": prereq_list,
                    "prerequisite_raw": prereq_raw,
                    "corequisites": coreq_raw,
                    "department": offering_dept if offering_dept else "Engineering and Technology",
                    "description": clr_text if clr_text else f"Official SRMIST Regulations 2021 curriculum course on {course_name.title()}.",
                    "page_number": page_idx + 1,
                    "regulation": "2021",
                    "is_official": True
                }
                
                if course_code not in seen_codes:
                    seen_codes.add(course_code)
                    extracted_courses.append(course_rec)
                break

print(f"\nSuccessfully extracted {len(extracted_courses)} distinct courses from syllabus PDF!")
print("\nSample 5 extracted courses:")
for c in extracted_courses[:5]:
    print(json.dumps(c, indent=2))

output_path = "campus_knowledge_server/data/courses/official_srm_courses_extracted.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(extracted_courses, f, indent=2)
print(f"\nSaved extracted courses to {output_path}")

