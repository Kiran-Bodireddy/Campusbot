"""
run_batch_a_data_and_graph.py
-----------------------------
Executes all Batch A source-file and live-Neo4j data/graph fixes in a single
repeatable, idempotent pass (requires Neo4j in write mode):

  Item 1:  BEL = "Basic Engineering Lab" in graph-blueprint.json, campus_graph_unified.json,
           and live Neo4j + re-embed all 20 building_embeddings.
  Item 2:  Fix ALL 55 curriculum program mappings (exact degree-aware matching, no wrong
           fuzzy merges, canonical PROG-431..438 nodes for the 8 Reg-2021 curriculum-only
           programs, restoring all 3,498 OFFERS_IN_SEMESTER edges + 100% program embeddings).
  Item 3:  Merge duplicate MBBS (PROG-429 -> PROG-423), preserving NEET-UG eligibility.
  Item 4:  Compute and store canonical normalized_department on every FacultyMember using
           matching_config.yaml rules.
  Item 7:  Clean faculty names (double spaces), specializations (trailing commas / spacing),
           and junk/job-history experience strings across source files and live Neo4j.
  Item 8:  Load official directory phone + compute phone_shared_count on every FacultyMember.
  Item 9:  Remove junk prerequisite CSE201 -> CSE101 from CSV/JSON and live Neo4j.
  Item 10: Normalize inconsistent Course.category values via matching_config.yaml.
"""

import csv
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
import requests
from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from campus_knowledge_server.config.matching_config import (
    normalize_course_category,
    normalize_department_name,
)

load_dotenv(ROOT / ".env")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")


def generate_embedding(text: str) -> list[float]:
    resp = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=60,
    )
    resp.raise_for_status()
    emb = resp.json().get("embedding")
    if not emb or len(emb) != 768:
        raise RuntimeError(f"Unexpected embedding dimension: {len(emb) if emb else 0}")
    return emb


# ── Cleaning helpers (Item 7 & 8) ──────────────────────────────────────────────

_WORD_NUMS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12",
}

_JOB_HISTORY_MARKERS = re.compile(
    r"\b(?:assistant\s+professor|associate\s+professor|professor|lecturer|instructor|"
    r"job\s+position|srm\s+institute|srm\s+university|srm\s+ist|engineering\s+college|"
    r"university/college|other\s+professional\s+experience|till\s+date|current|"
    r"present|worked\s+as|working\s+as|served\s+as|tenure|teacher\s+at|"
    r"autonomous|college\s+for|college\s+of|school\s+of|department\s+of|"
    r"from\s+\d{1,2}[/\-\.]\d{1,2}|\b(?:19|20)\d{2}\s*[-–to]+\s*(?:(?:19|20)\d{2}|till|present|current))\b",
    re.IGNORECASE,
)


def clean_name(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "").replace("\xa0", " ").strip())


def clean_specialization(raw: str) -> str:
    s = re.sub(r"\s+", " ", (raw or "").replace("\xa0", " ").strip())
    # Strip trailing commas/semicolons
    s = re.sub(r"[,;\s]+$", "", s).strip()
    # Normalize spacing around commas
    s = re.sub(r"\s*,\s*", ", ", s)
    return s


def clean_experience(raw: str) -> str:
    """
    Normalizes valid teaching-duration strings (e.g. '15 Years years of experience' -> '15 years',
    '10 year 10 months years of experience' -> '10 years 10 months').
    Clears junk labels ('University/College', 'Other Professional Experience:') and
    employment/job-history sentences to ''.
    """
    s = re.sub(r"\s+", " ", (raw or "").replace("\xa0", " ").strip())
    if not s:
        return ""
    # Reject job-history descriptions & known header junk outright
    if _JOB_HISTORY_MARKERS.search(s):
        return ""
    # Reject very long prose sentences (>65 chars)
    if len(s) > 65:
        return ""

    # Convert leading spelled-out numbers ("One year and six months")
    low = s.lower()
    for w, d in _WORD_NUMS.items():
        low = re.sub(rf"\b{w}\b", d, low)

    # Strip boilerplate prefixes & trailing 'of experience' (KEEP 'years'/'months' intact!)
    low = re.sub(r"^(?:teaching|total|overall|academic|industry|research)?\s*(?:experience|exp\.?)\s*[:\-]?\s*(?:of\s+)?", "", low).strip()
    low = re.sub(r"\s*(?:of\s+)?(?:teaching\s+|academic\s+|research\s+)?experience\s*\.?$", "", low).strip()
    # Collapse duplicated 'years years' (from '15 Years years of experience')
    low = re.sub(r"\b(years?|yrs?)(?:\s+(?:years?|yrs?))+\b", "years", low)

    # Pattern 1: X years [and] Y months
    m_ym = re.search(
        r"(\d+(?:\.\d+)?)\s*(\+)?\s*(?:years?|yrs?)\s*(?:,?\s*(?:and\s+)?)?(\d+)\s*(?:th\s+)?(?:months?|mos?)",
        low,
    )
    if m_ym:
        yrs, plus, mos = m_ym.group(1), m_ym.group(2) or "", m_ym.group(3)
        y_unit = "year" if yrs == "1" and not plus else "years"
        m_unit = "month" if mos == "1" else "months"
        return f"{yrs}{plus} {y_unit} {mos} {m_unit}"

    # Pattern 2: X[+] years
    m_y = re.search(r"(\d+(?:\.\d+)?)\s*(\+)?\s*(?:years?|yrs?)", low)
    if m_y:
        yrs, plus = m_y.group(1), m_y.group(2) or ""
        try:
            if float(yrs) > 70:  # reject stray calendar years like 2018
                return ""
        except ValueError:
            return ""
        y_unit = "year" if yrs == "1" and not plus else "years"
        return f"{yrs}{plus} {y_unit}"

    # Pattern 3: Y months only
    m_m = re.search(r"(\d+)\s*(?:months?|mos?)", low)
    if m_m:
        mos = m_m.group(1)
        m_unit = "month" if mos == "1" else "months"
        return f"{mos} {m_unit}"

    # Anything else (pure junk like '-', 'nil', 'University/College', etc.) -> empty
    return ""


def normalize_phone(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    if s.endswith(".0"):
        s = s[:-2]
    # Keep digits and leading '+' if present
    cleaned = re.sub(r"[^\d+]", "", s)
    if len(re.sub(r"\D", "", cleaned)) < 6:
        return ""
    return cleaned


# ── Program degree-aware canonical matcher (Item 2) ────────────────────────────

def _degree_family(name: str) -> str:
    low = (name or "").lower()
    if "integrated" in low and ("m.tech" in low or "mtech" in low):
        return "integrated_mtech"
    if re.search(r"\bm\.?\s*tech\b", low):
        return "mtech"
    if re.search(r"\bb\.?\s*tech\b", low):
        return "btech"
    if re.search(r"\bph\.?\s*d\b", low):
        return "phd"
    if re.search(r"\bminor\s+degree\b", low):
        return "minor"
    return "other"


def _canonical_prog_core(name: str) -> str:
    s = (name or "").lower()
    s = s.replace("b.tech.", " ").replace("b.tech", " ")
    s = s.replace("m.tech.", " ").replace("m.tech", " ")
    s = s.replace("(integrated)", " ").replace("integrated", " ")
    s = re.sub(r"\bin\s+collaboration\s+with\s+[^)]+", " ", s)
    s = re.sub(r"\bwith\s+specialization\s+in\b", " ", s)
    s = re.sub(r"\bw/s\s+in\b|\bw/s\b", " ", s)
    # Minor spelling normalizations (no program-name hardcoding)
    s = s.replace("cybersecurity", "cyber security")
    s = s.replace("data sciences", "data science")
    s = s.replace("micro electronics", "microelectronics")
    s = s.replace("material science", "materials science")
    s = re.sub(r"\b(?:in|and|of|the)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ── Step A: Update Source Files (Items 1, 7, 9, 10) ────────────────────────────

def update_source_files():
    print("========== STEP A: SOURCE FILES CLEANUP ==========")

    # 1. Clean faculty-cabins.csv & srmist_faculty_cabins.csv (double spaces + trailing commas)
    cab_paths = [
        ROOT / "Datasets" / "faculty-cabins.csv",
        ROOT / "campus_knowledge_server" / "data" / "srmist_faculty_cabins.csv",
    ]
    faculty_by_index = {}  # 1-based row index -> cleaned dict (matches FAC-0001..FAC-2501)
    phone_counts = Counter()

    with open(cab_paths[0], "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        raw_rows = list(reader)

    dbl_space_fixed = 0
    comma_spec_fixed = 0
    exp_cleaned = 0
    cleaned_rows = []
    for idx, row in enumerate(raw_rows, 1):
        old_name = row.get("name", "")
        new_name = clean_name(old_name)
        if "  " in old_name:
            dbl_space_fixed += 1

        old_spec = row.get("specialization", "")
        new_spec = clean_specialization(old_spec)
        if (old_spec or "").strip().endswith(","):
            comma_spec_fixed += 1

        old_exp = row.get("experience", "")
        new_exp = clean_experience(old_exp)
        if old_exp.strip() != new_exp:
            exp_cleaned += 1

        ph = normalize_phone(row.get("phone", ""))
        if ph:
            phone_counts[ph] += 1

        row_clean = dict(row)
        row_clean["name"] = new_name
        row_clean["specialization"] = new_spec
        row_clean["experience"] = new_exp
        row_clean["phone"] = ph
        cleaned_rows.append(row_clean)

        raw_dept = (row.get("fullDepartment") or row.get("department") or "").strip()
        faculty_by_index[f"FAC-{idx:04d}"] = {
            "id": f"FAC-{idx:04d}",
            "name": new_name,
            "specialization": new_spec,
            "experience": new_exp,
            "phone": ph,
            "raw_department": raw_dept,
            "normalized_department": normalize_department_name(raw_dept),
        }

    for fid, info in faculty_by_index.items():
        ph = info["phone"]
        info["phone_shared_count"] = phone_counts[ph] if ph else 0

    for cp in cab_paths:
        if cp.exists():
            with open(cp, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(cleaned_rows)

    print(f"  Faculty CSVs cleaned: double-space names fixed={dbl_space_fixed}, trailing-comma specs fixed={comma_spec_fixed}, experience cleaned={exp_cleaned}")
    print(f"  Phones computed: non-empty={sum(1 for v in faculty_by_index.values() if v['phone'])}, unique={sum(1 for v in faculty_by_index.values() if v['phone_shared_count']==1)}, shared={sum(1 for v in faculty_by_index.values() if v['phone_shared_count']>1)}, empty={sum(1 for v in faculty_by_index.values() if not v['phone'])}")

    # 2. Remove junk CSE201 -> CSE101 from prerequisites CSVs
    for pr_path in [
        ROOT / "Datasets" / "prerequisites.csv",
        ROOT / "campus_knowledge_server" / "data" / "courses" / "prerequisites_master.csv",
    ]:
        if pr_path.exists():
            with open(pr_path, "r", encoding="utf-8-sig", newline="") as f:
                r = csv.DictReader(f)
                fns = r.fieldnames
                rows = list(r)
            kept = [
                x for x in rows
                if not (
                    (x.get("target_course_code") or "").strip().upper() == "CSE201"
                    and (x.get("prerequisite_course_code") or "").strip().upper() == "CSE101"
                )
            ]
            with open(pr_path, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fns)
                w.writeheader()
                w.writerows(kept)
            print(f"  {pr_path.relative_to(ROOT)}: {len(rows)} -> {len(kept)} prerequisites")

    # 3. Update Datasets/graph-blueprint.json & campus_knowledge_server/data/campus_graph_unified.json
    for jf in [
        ROOT / "Datasets" / "graph-blueprint.json",
        ROOT / "campus_knowledge_server" / "data" / "campus_graph_unified.json",
    ]:
        if not jf.exists():
            continue
        data = json.loads(jf.read_text(encoding="utf-8"))

        # Item 1: Fix ONLY BEL building name & focus (do not alter other 8 names!)
        for b in data.get("buildings", []):
            if b.get("code") == "BEL":
                b["name"] = "Basic Engineering Lab"
                b["focus"] = "1st-Year Engineering Practicals, Foundational Labs & Workshops"

        # Item 9: Remove CSE201 -> CSE101 from prerequisites
        before_pr = len(data.get("prerequisites", []))
        data["prerequisites"] = [
            p for p in data.get("prerequisites", [])
            if not (
                (p.get("target_course_code") or "").upper() == "CSE201"
                and (p.get("prerequisite_course_code") or "").upper() == "CSE101"
            )
        ]
        after_pr = len(data["prerequisites"])

        # Item 7 & 4 & 8: Clean faculty records
        for fac in data.get("faculty", []):
            fid = fac.get("id")
            if fid in faculty_by_index:
                ci = faculty_by_index[fid]
                fac["name"] = ci["name"]
                fac["specialization"] = ci["specialization"]
                fac["experience"] = ci["experience"]
                fac["phone"] = ci["phone"]
                fac["phone_shared_count"] = ci["phone_shared_count"]
                fac["normalized_department"] = ci["normalized_department"]
            else:
                fac["name"] = clean_name(fac.get("name", ""))
                fac["specialization"] = clean_specialization(fac.get("specialization", ""))
                fac["experience"] = clean_experience(fac.get("experience", ""))
                fac["normalized_department"] = normalize_department_name(fac.get("department", ""))

        # Item 10: Normalize course categories
        for c in data.get("courses", []):
            if c.get("category"):
                c["category"] = normalize_course_category(c["category"])

        jf.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Updated {jf.relative_to(ROOT)}: BEL fixed, prereqs {before_pr}->{after_pr}, faculty cleaned & enriched")

    return faculty_by_index


# ── Step B: Live Neo4j Migration (Items 1, 2, 3, 4, 7, 8, 9, 10) ──────────────

def update_live_neo4j(faculty_by_index: dict):
    print("\n========== STEP B: LIVE NEO4J MIGRATION ==========")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    driver.verify_connectivity()

    # Verify write access
    with driver.session(database=NEO4J_DATABASE) as s:
        s.run("MERGE (t:_WriteTest {id:'batch_a'}) DELETE t")
    print("  Neo4j write access confirmed.")

    # --- ITEM 1: Update BEL Building & Re-embed ALL 20 Building nodes ---
    print("\n--- Item 1: BEL Building + Re-embed building_embeddings ---")
    with driver.session(database=NEO4J_DATABASE) as s:
        s.run("""
            MATCH (b:Building {code: 'BEL'})
            SET b.name = 'Basic Engineering Lab',
                b.focus = '1st-Year Engineering Practicals, Foundational Labs & Workshops',
                b.aliases = ['BEL', 'BEL Block', 'Basic Engineering Lab', 'Basic Engineering Labs', 'Workshop Block', 'First Year Engineering Lab'],
                b.description = 'The Basic Engineering Lab (BEL) is a G+5 facility housing foundational practical laboratories for all first-year B.Tech engineering students. It houses the heavy mechanical workshop practice hangars for welding, carpentry, and fitting, the Basic Electrical and Electronics (BEEE) labs, high-capacity engineering graphics drawing halls, and first-year physics and chemistry experimentation laboratories.'
        """)
        bldgs = s.run("""
            MATCH (b:Building)
            RETURN b.code AS code, b.name AS name, b.aliases AS aliases, b.floors AS floors,
                   b.focus AS focus, b.description AS description,
                   b.departments_housed AS departments_housed, b.facilities AS facilities
            ORDER BY b.code
        """).data()
        t0 = time.time()
        for b in bldgs:
            embed_text = (
                f"Building: {b['name']} | Code: {b['code']} | "
                f"Aliases: {', '.join(b['aliases'] or [])} | "
                f"Floors: {b['floors']} | Primary Focus: {b['focus'] or ''} | "
                f"Description: {b['description'] or ''} | "
                f"Departments: {', '.join(b['departments_housed'] or [])} | "
                f"Key Facilities: {', '.join(b['facilities'] or [])}"
            )
            vec = generate_embedding(embed_text)
            s.run("MATCH (b:Building {code: $code}) SET b.embedding = $vec", code=b["code"], vec=vec)
        print(f"  Re-embedded all {len(bldgs)} Building nodes ({time.time() - t0:.1f}s)")

    # --- ITEM 3: Merge duplicate MBBS (PROG-429 -> PROG-423) ---
    print("\n--- Item 3: Merge Duplicate MBBS (PROG-429 -> PROG-423) ---")
    with driver.session(database=NEO4J_DATABASE) as s:
        p429 = s.run("MATCH (p:Program {id: 'PROG-429'}) RETURN properties(p) AS props").single()
        if p429:
            props429 = p429["props"]
            s.run("""
                MATCH (p:Program {id: 'PROG-423'})
                SET p.official_eligibility_text = $elig_text,
                    p.required_entrance_exam = $exam,
                    p.mandatory_subjects = $subj,
                    p.min_percentage_general = $gen,
                    p.min_percentage_reserved = $res,
                    p.merged_duplicate_ids = ['PROG-429']
            """,
                elig_text=props429.get("official_eligibility_text", ""),
                exam=props429.get("required_entrance_exam", "NEET-UG"),
                subj=props429.get("mandatory_subjects", ""),
                gen=props429.get("min_percentage_general", 50.0),
                res=props429.get("min_percentage_reserved", 40.0),
            )
            # Transfer any edges from PROG-429 just in case, then delete PROG-429
            s.run("""
                MATCH (dup:Program {id: 'PROG-429'})-[r:OFFERS_IN_SEMESTER]->(c:Course)
                MATCH (canon:Program {id: 'PROG-423'})
                MERGE (canon)-[nr:OFFERS_IN_SEMESTER {semester: r.semester}]->(c)
                SET nr = properties(r)
            """)
            s.run("MATCH (dup:Program {id: 'PROG-429'}) DETACH DELETE dup")
            mbbs_vec = generate_embedding(
                "Program: MBBS Bachelor of Medicine and Bachelor of Surgery | "
                "Faculty: Medicine & Health Sciences | Degree: Undergraduate (UG) | "
                f"Eligibility: {props429.get('official_eligibility_text', '')}"
            )
            s.run("MATCH (p:Program {id: 'PROG-423'}) SET p.embedding = $vec", vec=mbbs_vec)
            print("  Merged PROG-429 into PROG-423 and deleted duplicate PROG-429.")
        else:
            print("  PROG-429 already merged/absent.")

    # --- ITEM 2: Rebuild ALL 55 Curriculum Programs -> 3,498 OFFERS_IN_SEMESTER links ---
    print("\n--- Item 2: Fix All 55 Curriculum Program Links (3,498 expected) ---")
    curr_data = json.loads((ROOT / "Datasets" / "curriculum.json").read_text(encoding="utf-8"))
    curr_progs = curr_data["programs"]

    with driver.session(database=NEO4J_DATABASE) as s:
        # Remove previously created curriculum_2021 nodes if re-running idempotently
        s.run("MATCH (p:Program) WHERE p.source = 'curriculum_2021' DETACH DELETE p")
        # Clear all OFFERS_IN_SEMESTER so we rebuild cleanly without stale/mismerged edges
        del_cnt = s.run("MATCH ()-[r:OFFERS_IN_SEMESTER]->() DELETE r RETURN count(r) AS n").single()["n"]
        print(f"  Cleared {del_cnt} existing OFFERS_IN_SEMESTER edges for clean rebuild.")

        admission_progs = s.run(
            "MATCH (p:Program) WHERE p.id IS NOT NULL RETURN p.id AS id, p.name AS name, p.degree_level AS deg ORDER BY p.id"
        ).data()

        # Index admission programs by (degree_family, core_name) AND (other_core_name for Specialized/Other 4-yr B.Tech)
        by_fam_core = defaultdict(list)
        by_specialized_core = defaultdict(list)
        for ap in admission_progs:
            fam = _degree_family(ap["name"])
            core = _canonical_prog_core(ap["name"])
            by_fam_core[(fam, core)].append(ap)
            if ap.get("deg") == "Specialized / Other" and fam == "other":
                by_specialized_core[core].append(ap)

        next_prog_num = 431
        mapping_report = []
        created_curr_progs = []

        for pname, pinfo in curr_progs.items():
            fam = _degree_family(pname)
            core = _canonical_prog_core(pname)
            exp_edges = sum(len(cl) for cl in pinfo.get("semesters", {}).values())

            # Strict degree-aware exact match ONLY (never cross-degree, never fuzzy!)
            target = None
            match_type = ""
            if (fam, core) in by_fam_core:
                target = by_fam_core[(fam, core)][0]
                match_type = "exact_admission"
            elif fam == "btech" and core in by_specialized_core:
                target = by_specialized_core[core][0]
                match_type = "exact_specialized_admission"
            else:
                # Create a canonical, embedded Reg-2021 curriculum Program node
                new_id = f"PROG-{next_prog_num:03d}"
                next_prog_num += 1
                deg_level = "Integrated Postgraduate (5 Years)" if fam == "integrated_mtech" else "Undergraduate (UG)"
                # Derive department cleanly from program title
                dept_clean = re.sub(r"^(?:Integrated\s+M\.Tech|B\.Tech)\s+in\s+", "", pname).strip()
                dept_clean = re.sub(r"\s+with\s+Specialization\s+in\s+.*$", "", dept_clean, flags=re.I).strip()
                dept_label = f"Department of {dept_clean}"
                emb_vec = generate_embedding(
                    f"Program: {pname} | Degree: {deg_level} | Faculty: Faculty of Engineering & Technology | "
                    f"Department: {dept_label} | Regulation: 2021 Curriculum"
                )
                s.run("""
                    CREATE (p:Program {
                        id: $id,
                        name: $name,
                        degree_level: $deg,
                        faculty: 'Faculty of Engineering & Technology',
                        department: $dept,
                        source: 'curriculum_2021',
                        embedding: $vec
                    })
                """, id=new_id, name=pname, deg=deg_level, dept=dept_label, vec=emb_vec)
                target = {"id": new_id, "name": pname}
                match_type = "created_curriculum_2021"
                created_curr_progs.append((new_id, pname, exp_edges))

            # Link all semester courses for this curriculum program
            batch = []
            for sem_str, c_list in pinfo.get("semesters", {}).items():
                sem_num = int(sem_str)
                for c in c_list:
                    batch.append({
                        "semester": sem_num,
                        "academic_year": c.get("academic_year", (sem_num + 1) // 2),
                        "course_code": c["course_code"],
                        "credits": c.get("credits", 0),
                        "ltpc": c.get("ltpc", ""),
                        "category": normalize_course_category(c.get("category", "")),
                    })
            linked = s.run("""
                UNWIND $batch AS row
                MATCH (p:Program {id: $pid})
                MATCH (c:Course {code: row.course_code})
                MERGE (p)-[r:OFFERS_IN_SEMESTER {semester: row.semester}]->(c)
                SET r.academic_year = row.academic_year,
                    r.credits = row.credits,
                    r.ltpc = row.ltpc,
                    r.category = row.category,
                    r.source = 'official'
                RETURN count(r) AS n
            """, pid=target["id"], batch=batch).single()["n"]

            mapping_report.append({
                "curriculum_program": pname,
                "target_id": target["id"],
                "target_name": target["name"],
                "match_type": match_type,
                "expected_edges": exp_edges,
                "linked_edges": linked,
            })

        total_offers = s.run("MATCH ()-[r:OFFERS_IN_SEMESTER]->() RETURN count(r) AS n").single()["n"]
        total_progs = s.run("MATCH (p:Program) RETURN count(p) AS n").single()["n"]
        emb_progs = s.run("MATCH (p:Program) WHERE p.embedding IS NOT NULL RETURN count(p) AS n").single()["n"]
        stub_progs = s.run("MATCH (p:Program) WHERE p.id IS NULL RETURN count(p) AS n").single()["n"]
        print(f"  Rebuilt OFFERS_IN_SEMESTER: {total_offers} (expected 3498)")
        print(f"  Programs in Neo4j: total={total_progs}, embedded={emb_progs}, stubs={stub_progs}")
        print(f"  Created {len(created_curr_progs)} canonical curriculum_2021 Program nodes: {[x[0] for x in created_curr_progs]}")

    # --- ITEMS 4, 7, 8: Faculty cleanups, normalized_department, phone & phone_shared_count ---
    print("\n--- Items 4, 7, 8: Faculty Cleanups, Normalized Department & Directory Phones ---")
    with driver.session(database=NEO4J_DATABASE) as s:
        fac_batch = list(faculty_by_index.values())
        updated_fac = s.run("""
            UNWIND $batch AS row
            MATCH (f:FacultyMember {id: row.id})
            SET f.name = row.name,
                f.specialization = row.specialization,
                f.experience = row.experience,
                f.normalized_department = row.normalized_department,
                f.phone = row.phone,
                f.phone_shared_count = row.phone_shared_count
            RETURN count(f) AS n
        """, batch=fac_batch).single()["n"]
        print(f"  Updated {updated_fac} FacultyMember nodes in Neo4j.")

        # Verify cleanups
        v_dbl = s.run("MATCH (f:FacultyMember) WHERE f.name CONTAINS '  ' RETURN count(f) AS n").single()["n"]
        v_comma = s.run("MATCH (f:FacultyMember) WHERE trim(coalesce(f.specialization, '')) ENDS WITH ',' RETURN count(f) AS n").single()["n"]
        v_norm_dept = s.run("MATCH (f:FacultyMember) RETURN count(DISTINCT f.normalized_department) AS n").single()["n"]
        v_raw_dept = s.run("MATCH (f:FacultyMember) RETURN count(DISTINCT f.department) AS n").single()["n"]
        v_phone = s.run("MATCH (f:FacultyMember) WHERE f.phone IS NOT NULL AND f.phone <> '' RETURN count(f) AS n").single()["n"]
        v_exp_nonempty = s.run("MATCH (f:FacultyMember) WHERE f.experience IS NOT NULL AND f.experience <> '' RETURN count(f) AS n").single()["n"]
        print(f"  Verify: double-space names={v_dbl}, comma specs={v_comma}, distinct raw dept={v_raw_dept} -> normalized_department={v_norm_dept}")
        print(f"  Verify: non-empty phones={v_phone}, clean non-empty experience={v_exp_nonempty}")

    # --- ITEM 9: Remove junk prerequisite CSE201 -> CSE101 ---
    print("\n--- Item 9: Remove Junk Prerequisite CSE201 -> CSE101 ---")
    with driver.session(database=NEO4J_DATABASE) as s:
        before_pr = s.run("MATCH ()-[r:REQUIRES_PREREQUISITE]->() RETURN count(r) AS n").single()["n"]
        del_pr = s.run("""
            MATCH (a:Course {code: 'CSE201'})-[r:REQUIRES_PREREQUISITE]->(b:Course {code: 'CSE101'})
            DELETE r
            RETURN count(r) AS n
        """).single()["n"]
        after_pr = s.run("MATCH ()-[r:REQUIRES_PREREQUISITE]->() RETURN count(r) AS n").single()["n"]
        print(f"  REQUIRES_PREREQUISITE: {before_pr} -> {after_pr} (removed {del_pr})")

    # --- ITEM 10: Normalize Course.category ---
    print("\n--- Item 10: Normalize Course.category ---")
    with driver.session(database=NEO4J_DATABASE) as s:
        before_cats = s.run("MATCH (c:Course) RETURN c.category AS cat, count(c) AS n ORDER BY n DESC").data()
        cat_mapping = {}
        for r in before_cats:
            old_c = r["cat"] or ""
            new_c = normalize_course_category(old_c)
            cat_mapping[old_c] = new_c
            if old_c != new_c:
                s.run("MATCH (c:Course) WHERE c.category = $old SET c.category = $new", old=old_c, new=new_c)
        after_cats = s.run("MATCH (c:Course) RETURN c.category AS cat, count(c) AS n ORDER BY n DESC").data()
        print("  Category mapping:")
        for k, v in sorted(cat_mapping.items()):
            print(f"    {k!r} -> {v!r}")
        print("  Normalized Course categories in Neo4j:", [(r["cat"], r["n"]) for r in after_cats])

    # Verify all vector indexes
    with driver.session(database=NEO4J_DATABASE) as s:
        v_idx = s.run("SHOW VECTOR INDEXES YIELD name, state, populationPercent RETURN name, state, populationPercent").data()
        print("\n--- Vector Indexes ---")
        for row in v_idx:
            print(" ", row)

    driver.close()

    # Save mapping report to scratch for verbatim printing
    report_path = Path("C:/Users/heyit/.gemini/antigravity/brain/5a112f75-e1b1-4d4a-a500-97ad81f6df4c/scratch/curriculum_55_mapping.json")
    report_path.write_text(json.dumps(mapping_report, indent=2), encoding="utf-8")
    print(f"\nSaved 55-program mapping report to {report_path}")


if __name__ == "__main__":
    fac_idx = update_source_files()
    update_live_neo4j(fac_idx)
    print("\nBatch A data & Neo4j migration complete.")
