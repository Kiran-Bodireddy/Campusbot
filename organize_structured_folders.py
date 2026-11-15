import os
import sys
import json
import re
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MASTER_JSON = os.path.join(BASE_DIR, "srmist_programs_master.json")
OUTPUT_ROOT = os.path.join(BASE_DIR, "campuses")

def sanitize_filename(name):
    # Remove invalid characters for Windows paths
    s = re.sub(r'[\\/*?:"<>|]', "", name)
    s = re.sub(r'[\s\-–—]+', "_", s).strip("_")
    return s[:90]

def normalize_campus_name(campus_str):
    if "Baburayanpettai" in campus_str:
        return "Baburayanpettai_Campus"
    return "Kattankulathur_Main_Campus"

def normalize_college_name(faculty_str):
    fac = faculty_str or "General_Studies"
    if "Agriculture" in fac:
        return "College_of_Agriculture_Sciences"
    elif "Engineering" in fac:
        return "Faculty_of_Engineering_and_Technology"
    elif "Medicine" in fac or "Health" in fac:
        return "Medicine_and_Health_Sciences"
    elif "Management" in fac:
        return "Faculty_of_Management"
    elif "Law" in fac:
        return "School_of_Law"
    elif "Liberal Arts" in fac or "Business Studies" in fac or "Science" in fac or "Humanities" in fac:
        return "Faculty_of_Liberal_Arts_and_Business_Studies"
    else:
        return sanitize_filename(fac)

def normalize_level_name(level_str):
    lvl = level_str or "Other"
    if "Undergraduate" in lvl or "UG" in lvl:
        return "Undergraduate_UG"
    elif "Postgraduate" in lvl or "PG" in lvl:
        return "Postgraduate_PG"
    elif "Ph.D" in lvl or "Doctoral" in lvl:
        return "Doctoral_PhD"
    elif "Diploma" in lvl or "Certificate" in lvl:
        return "Diploma_and_Certificate"
    elif "Fellowship" in lvl:
        return "Medical_Fellowships"
    else:
        return "Specialized_and_Minor_Degrees"

def create_markdown_card(p):
    fee_str = f"INR {p.get('annual_fees_inr'):,}" if p.get('annual_fees_inr') else (p.get('annual_fees_raw') or 'Contact Admissions')
    intake_str = str(p.get('sanctioned_intake') or 'N/A')
    
    md = f"""# {p.get('program_name')}

- **Degree Level**: {p.get('degree_level')}
- **Awarded Credential**: {p.get('credential') or 'N/A'}
- **Faculty / College**: {p.get('faculty')}
- **Department**: {p.get('department') or 'N/A'}
- **Campus**: {p.get('campuses_available') or 'Main Campus'}
- **Duration**: {p.get('duration') or 'N/A'}
- **Sanctioned Intake**: {intake_str}
- **Annual Tuition Fees**: {fee_str}

---

## Eligibility & Admission Criteria
{p.get('eligibility_criteria') or 'Please consult the official admissions prospectus for entry requirements.'}

---

## Program Overview & Curriculum Scope
{p.get('about_program') or 'Comprehensive academic curriculum offered at SRM Institute of Science and Technology.'}
"""

    if p.get('career_opportunities'):
        md += f"""
---

## Career Opportunities
{p.get('career_opportunities')}
"""

    if p.get('offerings'):
        md += "\n---\n\n## Campus Offerings Breakdown\n\n| Campus | Duration | Intake | Annual Fee |\n| :--- | :--- | :--- | :--- |\n"
        for o in p.get('offerings'):
            md += f"| {o.get('campus') or 'Main Campus'} | {o.get('duration') or p.get('duration') or 'N/A'} | {o.get('intake') or 'N/A'} | {o.get('fees') or fee_str} |\n"

    md += f"""
---

## Official Links
- [View on SRMIST Official Website]({p.get('program_url')})
"""
    return md

def main():
    print(f"[+] Loading master programs from: {MASTER_JSON} ...")
    with open(MASTER_JSON, "r", encoding="utf-8") as f:
        programs = json.load(f)

    print(f"[+] Processing {len(programs)} programs into structured directory hierarchy...")
    
    # Track hierarchy: campus -> college -> level -> [programs]
    tree = {}
    
    for p in programs:
        campus = normalize_campus_name(p.get('campuses_available', ''))
        college = normalize_college_name(p.get('faculty', ''))
        level = normalize_level_name(p.get('degree_level', ''))
        
        if campus not in tree:
            tree[campus] = {}
        if college not in tree[campus]:
            tree[campus][college] = {}
        if level not in tree[campus][college]:
            tree[campus][college][level] = []
            
        tree[campus][college][level].append(p)

    total_created_folders = 0
    total_written_programs = 0

    # Build directory structure
    for campus, colleges in tree.items():
        campus_dir = os.path.join(OUTPUT_ROOT, campus)
        os.makedirs(campus_dir, exist_ok=True)
        campus_programs_all = []

        for college, levels in colleges.items():
            college_dir = os.path.join(campus_dir, college)
            os.makedirs(college_dir, exist_ok=True)
            college_programs_all = []

            for level, progs in levels.items():
                level_dir = os.path.join(college_dir, level)
                os.makedirs(level_dir, exist_ok=True)
                total_created_folders += 1

                level_rows = []
                for p in progs:
                    total_written_programs += 1
                    college_programs_all.append(p)
                    campus_programs_all.append(p)

                    prog_slug = sanitize_filename(p.get('program_name') or f"program_{p['program_id']}")
                    
                    # 1. Write individual JSON
                    json_path = os.path.join(level_dir, f"{prog_slug}.json")
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(p, f, ensure_ascii=False, indent=2)

                    # 2. Write individual Markdown
                    md_path = os.path.join(level_dir, f"{prog_slug}.md")
                    with open(md_path, "w", encoding="utf-8") as f:
                        f.write(create_markdown_card(p))

                    # Collect summary row
                    level_rows.append({
                        "Program ID": p.get("program_id"),
                        "Program Name": p.get("program_name"),
                        "Credential": p.get("credential"),
                        "Department": p.get("department"),
                        "Duration": p.get("duration"),
                        "Sanctioned Intake": p.get("sanctioned_intake"),
                        "Annual Fees (INR)": p.get("annual_fees_inr"),
                        "Annual Fees (Raw)": p.get("annual_fees_raw"),
                        "Program URL": p.get("program_url")
                    })

                # Write level summary CSV
                df_level = pd.DataFrame(level_rows)
                df_level.to_csv(os.path.join(level_dir, "programs_summary.csv"), index=False, encoding="utf-8-sig")

            # Write College Summary CSV & README
            df_col = pd.DataFrame([{
                "Program ID": p.get("program_id"),
                "Program Name": p.get("program_name"),
                "Degree Level": p.get("degree_level"),
                "Department": p.get("department"),
                "Duration": p.get("duration"),
                "Annual Fees (INR)": p.get("annual_fees_inr"),
                "Program URL": p.get("program_url")
            } for p in college_programs_all])
            df_col.to_csv(os.path.join(college_dir, "college_programs.csv"), index=False, encoding="utf-8-sig")

            with open(os.path.join(college_dir, "README.md"), "w", encoding="utf-8") as f:
                f.write(f"# {college.replace('_', ' ')}\n\n")
                f.write(f"- **Campus**: {campus.replace('_', ' ')}\n")
                f.write(f"- **Total Programs**: {len(college_programs_all)}\n")
                f.write(f"- **Degree Levels Available**: {', '.join(levels.keys())}\n\n")
                f.write("### Sub-folders by Degree Level:\n")
                for lvl, l_progs in levels.items():
                    f.write(f"- [`{lvl}/`]({lvl}/): {len(l_progs)} programs\n")

        # Write Campus Summary CSV & README
        df_cam = pd.DataFrame([{
            "Program ID": p.get("program_id"),
            "Program Name": p.get("program_name"),
            "College / Faculty": p.get("faculty"),
            "Degree Level": p.get("degree_level"),
            "Duration": p.get("duration"),
            "Annual Fees (INR)": p.get("annual_fees_inr"),
            "Program URL": p.get("program_url")
        } for p in campus_programs_all])
        df_cam.to_csv(os.path.join(campus_dir, "campus_programs.csv"), index=False, encoding="utf-8-sig")

        with open(os.path.join(campus_dir, "README.md"), "w", encoding="utf-8") as f:
            f.write(f"# {campus.replace('_', ' ')}\n\n")
            f.write(f"- **Total Programs Offered**: {len(campus_programs_all)}\n")
            f.write(f"- **Colleges / Faculties**: {len(colleges)}\n\n")
            f.write("### Colleges & Faculties:\n")
            for col, lvls in colleges.items():
                p_count = sum(len(x) for x in lvls.values())
                f.write(f"- [`{col}/`]({col}/): {p_count} programs across {len(lvls)} degree levels\n")

    # Generate Top-Level Index of the Structured Directory
    index_md_path = os.path.join(BASE_DIR, "STRUCTURED_DIRECTORY_INDEX.md")
    with open(index_md_path, "w", encoding="utf-8") as f:
        f.write("# SRMIST Structured Academic Catalog - Campus & College Directory Tree\n\n")
        f.write("This directory structure organizes all 428 academic programs into a clean hierarchy:\n")
        f.write("`Campus` ➔ `College / Faculty` ➔ `Degree Level` ➔ `Individual Program Files (.md / .json)`\n\n")
        f.write("---\n\n")
        
        for campus, colleges in tree.items():
            total_cam = sum(sum(len(p) for p in lvls.values()) for lvls in colleges.values())
            f.write(f"## 🏛️ [{campus.replace('_', ' ')}](campuses/{campus}/) ({total_cam} Programs)\n\n")
            for college, levels in colleges.items():
                total_col = sum(len(p) for p in levels.values())
                f.write(f"### 🏫 [{college.replace('_', ' ')}](campuses/{campus}/{college}/) ({total_col} Programs)\n\n")
                for level, progs in levels.items():
                    f.write(f"- **[{level.replace('_', ' ')}](campuses/{campus}/{college}/{level}/)**: {len(progs)} programs\n")
                f.write("\n")
            f.write("---\n\n")

    print(f"[✔] Successfully generated structured directory tree in: {OUTPUT_ROOT}")
    print(f"    * Total programs organized: {total_written_programs}")
    print(f"    * Top-level index generated at: {index_md_path}")

if __name__ == "__main__":
    main()
