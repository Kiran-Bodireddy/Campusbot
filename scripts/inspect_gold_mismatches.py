import json
import os
import csv

with open("campus_knowledge_server/eval/benchmark_dataset.json", "r", encoding="utf-8") as f:
    ds = json.load(f)

with open("campus_knowledge_server/data/campus_graph_unified.json", "r", encoding="utf-8") as f:
    unified = json.load(f)

with open("campus_knowledge_server/data/courses/admission_eligibility_master.json", "r", encoding="utf-8") as f:
    admissions = json.load(f)

with open("campus_knowledge_server/data/courses/curricula_semester_master.json", "r", encoding="utf-8") as f:
    curricula = json.load(f)

courses_by_code = {c["code"].upper(): c for c in unified.get("courses", [])}
rooms_by_id = {r["id"].upper(): r for r in unified.get("rooms", [])}
faculty_names = [f["name"] for f in unified.get("faculty", [])]
prog_by_id = {p["program_id"]: p for p in admissions}
schedules = unified.get("schedules", [])
prereqs = unified.get("prerequisites", [])

print(f"Loaded sources: courses={len(courses_by_code)}, rooms={len(rooms_by_id)}, faculty={len(faculty_names)}, admissions={len(prog_by_id)}, curricula_progs={len(curricula)}")

# Build room occupancy lookup from unified.json schedules
occ_map = {}  # (day_lower, slot) -> set of room_ids
for sc in schedules:
    key = (str(sc.get("day", "")).lower(), str(sc.get("slot", "")))
    occ_map.setdefault(key, set()).add(str(sc.get("room_id", "")).upper())

SLOT_MAP = {
    1: "08:45-09:35", 2: "09:45-10:35", 3: "10:45-11:35", 4: "11:45-12:35",
    5: "13:30-14:20", 6: "14:30-15:20", 7: "15:30-16:20", 8: "16:30-17:20"
}

print("\n=== INSPECTING ALL 80 LEGITIMATE ITEMS AGAINST SOURCE JSON FILES ===")
for q in ds:
    if q.get("should_block"):
        continue
    qid = q["id"]
    tool = q["gold_tool"]
    params = q.get("gold_params", {})
    gents = q.get("gold_entities", [])
    issues = []

    if tool == "find_available_rooms":
        bcode = str(params.get("building_code", "TP")).upper()
        day = str(params.get("day", "Monday")).lower()
        slot_raw = params.get("slot", "08:45-09:35")
        slot_str = SLOT_MAP.get(slot_raw, str(slot_raw))
        min_cap = params.get("min_capacity", 30)
        occ = occ_map.get((day, slot_str), set())
        avail_from_source = [
            r["id"] for r in unified.get("rooms", [])
            if r.get("building_code", "").upper() == bcode and r.get("capacity", 0) >= min_cap and r["id"].upper() not in occ
        ]
        for ge in gents:
            if ge["id"].upper() not in avail_from_source:
                issues.append(f"room {ge['id']} NOT available in source (slot={slot_raw}->{slot_str}, min_cap={min_cap}); actual first 3 in source: {avail_from_source[:3]}")

    elif tool == "check_admission_eligibility":
        pq = params.get("program_query", "").lower()
        for ge in gents:
            if ge["id"] not in prog_by_id:
                matches = [p for p in admissions if pq in p["program_name"].lower()]
                if not matches:
                    toks = [t for t in pq.replace(".", "").split() if len(t) >= 2]
                    matches = [p for p in admissions if all(t in p["program_name"].lower().replace(".", "") for t in toks)]
                issues.append(f"program {ge['id']} NOT in admission_eligibility_master.json; source matches: {[(m['program_id'], m['program_name']) for m in matches[:3]]}")
            else:
                # Check if the ID actually matches the program query!
                p_name = prog_by_id[ge["id"]]["program_name"]
                if pq not in p_name.lower() and not all(t in p_name.lower().replace(".", "") for t in pq.replace(".", "").split() if len(t) >= 3):
                    matches = [p for p in admissions if pq in p["program_name"].lower()]
                    if not matches:
                        toks = [t for t in pq.replace(".", "").split() if len(t) >= 2]
                        matches = [p for p in admissions if all(t in p["program_name"].lower().replace(".", "") for t in toks)]
                    issues.append(f"program {ge['id']}='{p_name}' MISMATCHES query '{pq}'; actual source matches: {[(m['program_id'], m['program_name']) for m in matches[:3]]}")

    elif tool == "search_courses_semantic":
        sq = params.get("query", "").lower()
        toks = [t for t in sq.split() if len(t) >= 3]
        for ge in gents:
            c = courses_by_code.get(ge["id"].upper())
            if not c:
                issues.append(f"course {ge['id']} NOT in courses.json")
            else:
                blob = (c.get("name", "") + " " + c.get("description", "")).lower()
                if not any(t in blob for t in toks):
                    # Find actual courses in source JSON matching query words
                    src_matches = [
                        (cc["code"], cc["name"]) for cc in unified.get("courses", [])
                        if any(t in cc.get("name", "").lower() for t in toks)
                    ]
                    issues.append(f"gold {ge['id']}='{c['name']}' unrelated to '{sq}'; source title matches: {src_matches[:4]}")

    elif tool == "get_semester_curriculum":
        pq = params.get("program_query", "")
        sem = params.get("semester")
        for ge in gents:
            if ge.get("type") == "course" and ge["id"].upper() not in courses_by_code:
                issues.append(f"course {ge['id']} NOT in source courses")
        # Check if gold entity actually appears in curricula_semester_master.json for that program/semester
        cur_keys = list(curricula.keys())
        matched_ckey = None
        for ck in cur_keys:
            if pq.lower() in ck.lower():
                matched_ckey = ck
                break
        if matched_ckey and sem:
            sem_courses = curricula[matched_ckey].get("semesters", {}).get(str(sem), [])
            sem_codes = [sc["course_code"].upper() for sc in sem_courses]
            for ge in gents:
                if ge.get("type") == "course" and ge["id"].upper() not in sem_codes:
                    issues.append(f"course {ge['id']} NOT in {matched_ckey} sem {sem}; source sem codes: {sem_codes[:5]}")
        elif not matched_ckey:
            issues.append(f"program_query '{pq}' not directly in curricula keys; sample keys: {cur_keys[:5]}")

    elif tool in ("lookup_course", "get_prerequisite_tree", "verify_prerequisites", "find_faculty_for_course"):
        for ge in gents:
            if ge.get("type") == "course" and ge["id"].upper() not in courses_by_code:
                issues.append(f"course {ge['id']} NOT in source courses")

    elif tool == "lookup_faculty_profile":
        for ge in gents:
            if ge.get("type") == "faculty":
                gid = ge["id"].lower()
                if not any(gid in fn.lower() or fn.lower() in gid for fn in faculty_names):
                    issues.append(f"faculty {ge['id']} NOT in source faculty")

    if issues:
        print(f"[{qid}] ({tool}) query='{q['query']}'")
        for iss in issues:
            print(f"    -> {iss}")
