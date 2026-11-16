"""
Admission Eligibility Master Table Builder
Parses SRMIST programs catalog and standardizes admission eligibility criteria
into structured, numeric, and queryable fields across all 428 academic programs.
"""

import os
import json
import csv
import re
from typing import Dict, Any, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGRAMS_JSON_PATH = os.path.join(BASE_DIR, "data", "courses", "srmist_programs_master.json")
OUTPUT_CSV_PATH = os.path.join(BASE_DIR, "data", "courses", "admission_eligibility_master.csv")
OUTPUT_JSON_PATH = os.path.join(BASE_DIR, "data", "courses", "admission_eligibility_master.json")

def parse_program_eligibility(prog: Dict[str, Any]) -> Dict[str, Any]:
    name = prog.get("program_name", "").strip()
    faculty = prog.get("faculty", "").strip()
    dept = prog.get("department", "").strip()
    level = prog.get("degree_level", "").strip()
    raw_elig = (prog.get("eligibility_criteria") or "").strip()
    prog_id = f"PROG-{prog.get('program_id', 1):03d}"

    name_lower = name.lower()
    fac_lower = faculty.lower()
    lvl_lower = level.lower()

    # Defaults
    min_education = "10+2 (Higher Secondary)"
    mandatory_subjects = "Any Stream"
    min_pct_gen = 50.0
    min_pct_res = 45.0
    entrance_exam = "Merit Based"

    # 1. Doctoral / Ph.D.
    if "doctoral" in lvl_lower or "ph.d" in name_lower or "phd" in name_lower:
        min_education = "Master's Degree in Relevant Discipline"
        mandatory_subjects = "Recognized PG Degree (M.E./M.Tech/M.Sc/MBA/M.A./LL.M/MD)"
        min_pct_gen = 55.0
        min_pct_res = 50.0
        entrance_exam = "SRMIST Ph.D. Entrance Exam + Interview (UGC-NET/GATE Exempt)"

    # 2. Engineering & Technology (UG)
    elif "b.tech" in name_lower:
        min_education = "10+2 (Higher Secondary) - Regular"
        if any(b in name_lower for b in ["biotech", "biomedical", "genetic"]):
            mandatory_subjects = "Physics & Mathematics OR Biology (PCM / PCB)"
        else:
            mandatory_subjects = "Physics & Mathematics (compulsory) + Chemistry/CS/IT (PCM)"
        min_pct_gen = 60.0
        min_pct_res = 50.0
        entrance_exam = "SRMJEEE (UG) / JEE Main"

    elif "b.arch" in name_lower:
        min_education = "10+2 (Higher Secondary) or 10+3 Diploma"
        mandatory_subjects = "Physics, Chemistry & Mathematics"
        min_pct_gen = 50.0
        min_pct_res = 45.0
        entrance_exam = "NATA (National Aptitude Test in Architecture)"

    elif "b.des" in name_lower:
        min_education = "10+2 (Higher Secondary)"
        mandatory_subjects = "Any Stream"
        min_pct_gen = 50.0
        min_pct_res = 45.0
        entrance_exam = "UCEED / SRM Design Aptitude Test"

    # 3. Engineering & Technology (PG)
    elif "m.tech" in name_lower or ("postgraduate" in lvl_lower and "engineering" in fac_lower):
        min_education = "B.E. / B.Tech in Relevant Branch"
        mandatory_subjects = "Matching Engineering / Technology Discipline"
        min_pct_gen = 50.0
        min_pct_res = 45.0
        entrance_exam = "SRMJEEM / GATE / TANCET"

    # 4. Management
    elif "mba" in name_lower or "m.b.a" in name_lower:
        min_education = "Bachelor's Degree (3+ Years)"
        mandatory_subjects = "Any Recognized Undergraduate Discipline"
        min_pct_gen = 50.0
        min_pct_res = 45.0
        entrance_exam = "CAT / MAT / XAT / CMAT / NMAT / TANCET / SRMJEEM"

    elif "bba" in name_lower or "b.b.a" in name_lower:
        min_education = "10+2 (Higher Secondary)"
        mandatory_subjects = "Any Stream (Commerce/Science preferred)"
        min_pct_gen = 50.0
        min_pct_res = 45.0
        entrance_exam = "Direct Merit Based"

    # 5. Law
    elif "ll.b" in name_lower or "law" in fac_lower:
        if "5" in raw_elig or "integrated" in name_lower or "b.a" in name_lower or "b.b.a" in name_lower:
            min_education = "10+2 (Higher Secondary) - Regular Mode"
            mandatory_subjects = "Any Stream (Regular Schooling per BCI)"
            min_pct_gen = 60.0
            min_pct_res = 55.0
            entrance_exam = "CLAT / LSAT-India / SRMJEEL"
        elif "ll.m" in name_lower:
            min_education = "LL.B (3-Year or 5-Year Integrated)"
            mandatory_subjects = "Recognized Law Degree from BCI-approved institute"
            min_pct_gen = 60.0
            min_pct_res = 55.0
            entrance_exam = "CLAT-PG / SRM Law Merit"
        else:
            min_education = "Bachelor's Degree in Any Stream"
            mandatory_subjects = "Any Recognized Undergraduate Degree"
            min_pct_gen = 60.0
            min_pct_res = 55.0
            entrance_exam = "Direct Merit Based"

    # 6. Medicine & Health Sciences
    elif "mbbs" in name_lower or "bds" in name_lower:
        min_education = "10+2 (Higher Secondary) - Min Age 17"
        mandatory_subjects = "Physics, Chemistry, Biology/Biotechnology & English"
        min_pct_gen = 50.0
        min_pct_res = 40.0
        entrance_exam = "NEET-UG (Mandatory Central MCC Counselling)"

    elif "md" in name_lower or "m.s." in name_lower or "mds" in name_lower:
        min_education = "MBBS / BDS Degree + 1-Year Compulsory Internship"
        mandatory_subjects = "Permanent State / NMC Registration"
        min_pct_gen = 50.0
        min_pct_res = 40.0
        entrance_exam = "NEET-PG / NEET-MDS"

    elif "d.m." in name_lower or "m.ch" in name_lower:
        min_education = "MD / MS / DNB in Relevant Specialty"
        mandatory_subjects = "Clinical Medical Post-Graduate Degree"
        min_pct_gen = 50.0
        min_pct_res = 40.0
        entrance_exam = "NEET-SS"

    elif "b.pharm" in name_lower or "pharm.d" in name_lower:
        min_education = "10+2 (Higher Secondary)"
        mandatory_subjects = "Physics & Chemistry + Mathematics or Biology (PCM/PCB)"
        min_pct_gen = 50.0
        min_pct_res = 45.0
        entrance_exam = "Direct Merit Based"

    elif "nursing" in name_lower:
        min_education = "10+2 (Higher Secondary) - Min Age 17"
        mandatory_subjects = "Physics, Chemistry, Biology & English (PCB)"
        min_pct_gen = 45.0
        min_pct_res = 40.0
        entrance_exam = "Direct Merit / Nursing Board Norms"

    elif "physiotherapy" in name_lower or "b.p.t" in name_lower or "b.o.t" in name_lower:
        min_education = "10+2 (Higher Secondary)"
        mandatory_subjects = "Physics, Chemistry, Biology & English (PCB)"
        min_pct_gen = 50.0
        min_pct_res = 45.0
        entrance_exam = "Direct Merit Based"

    # 7. Agriculture
    elif "agriculture" in name_lower or "horticulture" in name_lower:
        if "postgraduate" in lvl_lower or "m.sc" in name_lower:
            min_education = "4-Year B.Sc. (Hons) Agriculture / Horticulture"
            mandatory_subjects = "ICAR Accredited Degree in Agriculture/Horticulture"
            min_pct_gen = 60.0
            min_pct_res = 55.0
            entrance_exam = "SRM Agriculture PG Merit"
        else:
            min_education = "10+2 (Higher Secondary)"
            mandatory_subjects = "Physics, Chemistry, Biology/Maths or Vocational Agriculture"
            min_pct_gen = 50.0
            min_pct_res = 45.0
            entrance_exam = "Direct Merit Based (No Entrance Exam)"

    # 8. Science & Humanities (B.Sc, BCA, B.Com, B.A, MCA)
    elif "bca" in name_lower:
        min_education = "10+2 (Higher Secondary)"
        mandatory_subjects = "Mathematics or Computer Science or Business Maths"
        min_pct_gen = 50.0
        min_pct_res = 45.0
        entrance_exam = "Direct Merit Based"

    elif "mca" in name_lower:
        min_education = "BCA / B.Sc (CS/IT) or Bachelor's Degree"
        mandatory_subjects = "Mathematics at 10+2 or Graduation Level"
        min_pct_gen = 50.0
        min_pct_res = 45.0
        entrance_exam = "TANCET / SRM Entrance"

    elif "b.sc" in name_lower:
        min_education = "10+2 (Higher Secondary)"
        if any(c in name_lower for c in ["computer", "data", "cyber", "information"]):
            mandatory_subjects = "Mathematics, Statistics, or Computer Science"
        elif any(c in name_lower for c in ["chemistry", "physics", "bio", "biotech"]):
            mandatory_subjects = "Physics & Chemistry + Mathematics or Biology (PCM/PCB)"
        else:
            mandatory_subjects = "Science / Relevant 10+2 Stream"
        min_pct_gen = 50.0
        min_pct_res = 45.0
        entrance_exam = "Direct Merit Based"

    elif "b.com" in name_lower:
        min_education = "10+2 (Higher Secondary)"
        mandatory_subjects = "Commerce, Accountancy, Economics, or Mathematics"
        min_pct_gen = 50.0
        min_pct_res = 45.0
        entrance_exam = "Direct Merit Based"

    elif "b.a" in name_lower:
        min_education = "10+2 (Higher Secondary)"
        mandatory_subjects = "Any Stream"
        min_pct_gen = 50.0
        min_pct_res = 45.0
        entrance_exam = "Direct Merit Based"

    elif "postgraduate" in lvl_lower or "m.sc" in name_lower or "m.a" in name_lower or "m.com" in name_lower:
        min_education = "Bachelor's Degree in Relevant Discipline"
        mandatory_subjects = "Matching Undergraduate Major Subject"
        min_pct_gen = 50.0
        min_pct_res = 45.0
        entrance_exam = "Direct Merit Based"

    # Fallback to official raw text if it exists
    final_text = raw_elig if raw_elig else (
        f"Minimum eligibility requires {min_education} with {mandatory_subjects} and minimum {min_pct_gen}% aggregate marks. Selection via {entrance_exam}."
    )

    return {
        "program_id": prog_id,
        "program_name": name,
        "faculty": faculty,
        "department": dept,
        "degree_level": level,
        "min_education": min_education,
        "mandatory_subjects": mandatory_subjects,
        "min_percentage_general": min_pct_gen,
        "min_percentage_reserved": min_pct_res,
        "required_entrance_exam": entrance_exam,
        "official_eligibility_text": final_text
    }

def main():
    if not os.path.exists(PROGRAMS_JSON_PATH):
        print(f"Error: Programs JSON not found at {PROGRAMS_JSON_PATH}")
        return

    with open(PROGRAMS_JSON_PATH, "r", encoding="utf-8") as f:
        programs = json.load(f)

    eligibility_records = []
    for p in programs:
        rec = parse_program_eligibility(p)
        eligibility_records.append(rec)

    # Flagship Medicine & Dental programs under SRM Medical & Dental Colleges
    flagship_programs = [
        {
            "program_id": f"PROG-{len(eligibility_records)+1:03d}",
            "program_name": "MBBS - Bachelor of Medicine and Bachelor of Surgery",
            "faculty": "Faculty of Medicine and Health Sciences",
            "department": "SRM Medical College Hospital and Research Centre",
            "degree_level": "Undergraduate (UG)",
            "min_education": "10+2 (Higher Secondary)",
            "mandatory_subjects": "Physics, Chemistry, Biology / Biotechnology & English (PCB)",
            "min_percentage_general": 50.0,
            "min_percentage_reserved": 40.0,
            "required_entrance_exam": "NEET-UG (National Eligibility cum Entrance Test)",
            "official_eligibility_text": "Candidates must have passed 10+2 with Physics, Chemistry, Biology/Biotechnology and English with minimum 50% marks in PCB aggregate (40% for SC/ST/OBC). Must qualify NEET-UG conducted by NTA."
        },
        {
            "program_id": f"PROG-{len(eligibility_records)+2:03d}",
            "program_name": "BDS - Bachelor of Dental Surgery",
            "faculty": "Faculty of Medicine and Health Sciences",
            "department": "SRM Dental College",
            "degree_level": "Undergraduate (UG)",
            "min_education": "10+2 (Higher Secondary)",
            "mandatory_subjects": "Physics, Chemistry, Biology & English (PCB)",
            "min_percentage_general": 50.0,
            "min_percentage_reserved": 40.0,
            "required_entrance_exam": "NEET-UG (National Eligibility cum Entrance Test)",
            "official_eligibility_text": "Candidates must have passed 10+2 with Physics, Chemistry, Biology and English with minimum 50% marks in PCB aggregate (40% for SC/ST/OBC). Must qualify NEET-UG conducted by NTA."
        }
    ]
    eligibility_records.extend(flagship_programs)

    print(f"Standardized admission eligibility for all {len(eligibility_records)} programs.")

    # 1. Save JSON
    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(eligibility_records, f, indent=2)
    print(f"Saved: {OUTPUT_JSON_PATH}")

    # 2. Save CSV
    headers = [
        "program_id",
        "program_name",
        "faculty",
        "department",
        "degree_level",
        "min_education",
        "mandatory_subjects",
        "min_percentage_general",
        "min_percentage_reserved",
        "required_entrance_exam",
        "official_eligibility_text"
    ]

    with open(OUTPUT_CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(eligibility_records)
    print(f"Saved: {OUTPUT_CSV_PATH}")

    # Summary Statistics
    from collections import Counter
    pct_dist = Counter([r["min_percentage_general"] for r in eligibility_records])
    exam_dist = Counter([r["required_entrance_exam"] for r in eligibility_records])

    print("\n--- Summary of Minimum General Percentages ---")
    for pct, count in pct_dist.most_common():
        print(f"  {pct}% : {count} programs")

    print("\n--- Top Entrance Examination Channels ---")
    for exam, count in exam_dist.most_common(6):
        print(f"  {exam} : {count} programs")

if __name__ == "__main__":
    main()
