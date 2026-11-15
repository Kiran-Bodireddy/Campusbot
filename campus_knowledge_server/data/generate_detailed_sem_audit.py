import json

with open("campus_knowledge_server/data/courses/curricula_semester_master.json", "r", encoding="utf-8") as f:
    data = json.load(f)

programs = data["programs"]

progs_to_detail = [
    "B.Tech in Computer Science and Engineering",
    "B.Tech in Artificial Intelligence",
    "B.Tech in Electronics and Communication Engineering",
    "B.Tech in Mechanical Engineering",
    "B.Tech in Biotechnology",
    "B.Tech in Aerospace Engineering"
]

report = []
report.append("=" * 80)
report.append("DETAILED SEMESTER-BY-SEMESTER CURRICULUM AUDIT ACROSS MAJOR BRANCHES")
report.append("=" * 80)

for p_name in progs_to_detail:
    if p_name not in programs:
        continue
    p_data = programs[p_name]
    report.append(f"\n================================================================================")
    report.append(f"PROGRAMME: {p_name.upper()} (Page {p_data.get('implementation_plan_page')})")
    report.append(f"================================================================================")
    
    tot_credits = 0
    tot_courses = 0
    for sem in range(1, 9):
        c_list = p_data["semesters"].get(str(sem), [])
        sem_credits = sum(c.get("credits", 0) for c in c_list)
        tot_credits += sem_credits
        tot_courses += len(c_list)
        
        report.append(f"\n  [SEMESTER {sem}] - {len(c_list)} Courses | {sem_credits} Credits:")
        for c in c_list:
            report.append(f"    * {c['course_code']}: {c['course_name']} | {c['category']} | L-T-P-C: {c['ltpc']} | {c['credits']} Credits")
            
    report.append(f"\n  >> TOTAL FOR {p_name}: {tot_courses} Course Allocations, {tot_credits} Cumulative Credits")

with open("campus_knowledge_server/data/detailed_sem_audit.txt", "w", encoding="utf-8") as out:
    out.write("\n".join(report) + "\n")

print("Detailed report written to detailed_sem_audit.txt")

