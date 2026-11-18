"""
update_courses_neo4j.py
-----------------------
Update Neo4j Course nodes with structured syllabus data extracted from the PDF,
and refresh 768-dim embeddings for the updated courses.
Steps:
  1. Mark ALL 668 courses as has_detailed_syllabus=False
  2. Update the 189 PDF-backed courses with structured fields
  3. Add the 1 PDF-only course (21MEO113J) as a new :Course node
  4. Refresh 768-dim embeddings for all 190 PDF-backed courses via nomic-embed-text
  5. Report counts
"""

import json
import os
import sys
import time
from pathlib import Path

# ── connection ─────────────────────────────────────────────────────────────────
try:
    from neo4j import GraphDatabase
except ImportError:
    print("ERROR: neo4j package not found. Install with: pip install neo4j")
    sys.exit(1)

try:
    import requests
except ImportError:
    requests = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://127.0.0.1:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     os.getenv("NEO4J_USERNAME", "neo4j"))
NEO4J_PASS     = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
OLLAMA_URL     = os.getenv("OLLAMA_URL",     "http://127.0.0.1:11434")
EMBED_MODEL    = os.getenv("EMBED_MODEL",    "nomic-embed-text")

ROOT = Path(__file__).resolve().parent.parent
SYLLABUS_JSON = ROOT / "campus_knowledge_server" / "data" / "courses" / "syllabus_extracted.json"
COURSES_JSON  = ROOT / "Datasets" / "courses.json"


def connect():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    driver.verify_connectivity()
    print(f"Connected to Neo4j at {NEO4J_URI}")
    return driver


def test_write_access(driver):
    """Try a benign write to verify Neo4j is not in read-only mode."""
    with driver.session() as session:
        try:
            session.run("MERGE (t:_WriteTest {id: 'test'}) SET t.ts = timestamp() RETURN t")
            session.run("MATCH (t:_WriteTest {id: 'test'}) DELETE t")
        except Exception as e:
            print(f"WRITE ACCESS DENIED: {e}")
            print("Set server.databases.default_to_read_only=false in neo4j.conf and restart Neo4j.")
            sys.exit(1)
    print("Write access confirmed.")


def step1_mark_all_no_syllabus(driver, total_expected=668):
    """Mark all :Course nodes as has_detailed_syllabus=False."""
    with driver.session() as session:
        result = session.run(
            "MATCH (c:Course) SET c.has_detailed_syllabus = false RETURN count(c) AS n"
        )
        n = result.single()["n"]
        print(f"Step 1: Marked {n} courses as has_detailed_syllabus=false")
        return n


def step2_update_pdf_courses(driver, extracted: dict, graph_codes: set):
    """Update the 189 overlapping courses with structured syllabus data."""
    updated = 0
    skipped = 0
    
    for code, rec in extracted.items():
        if code not in graph_codes:
            skipped += 1
            continue

        # Serialize list fields as JSON strings (Neo4j doesn't natively store lists of dicts)
        course_rationale   = rec.get("course_rationale") or []
        course_outcomes    = rec.get("course_outcomes") or []
        syllabus_units_raw = rec.get("syllabus_units") or []
        textbooks          = rec.get("textbooks") or []
        assessment         = rec.get("assessment_summary") or {}

        # Store syllabus_units as JSON string (list of dicts)
        syllabus_units_json = json.dumps(syllabus_units_raw, ensure_ascii=False)
        assessment_json     = json.dumps(assessment, ensure_ascii=False)

        with driver.session() as session:
            result = session.run(
                """
                MATCH (c:Course)
                WHERE toUpper(c.code) = toUpper($code)
                SET
                    c.has_detailed_syllabus   = true,
                    c.course_rationale        = $course_rationale,
                    c.course_outcomes         = $course_outcomes,
                    c.syllabus_units          = $syllabus_units,
                    c.textbooks               = $textbooks,
                    c.assessment_summary      = $assessment_summary,
                    c.corequisites_raw        = $corequisites_raw,
                    c.progressive_courses_raw = $progressive_courses_raw,
                    c.description             = CASE WHEN $description <> '' THEN $description ELSE c.description END
                RETURN count(c) AS n
                """,
                code                   = code,
                course_rationale       = course_rationale,
                course_outcomes        = course_outcomes,
                syllabus_units         = syllabus_units_json,
                textbooks              = textbooks,
                assessment_summary     = assessment_json,
                corequisites_raw       = rec.get("corequisites_raw") or "Nil",
                progressive_courses_raw= rec.get("progressive_courses_raw") or "Nil",
                description            = rec.get("description") or "",
            )
            n = result.single()["n"]
            if n > 0:
                updated += 1
            else:
                print(f"  WARNING: code {code} not found in graph (Cypher matched 0 nodes)")
                skipped += 1

    print(f"Step 2: Updated {updated} courses | Skipped (not in graph): {skipped}")
    return updated


def step3_add_pdf_only_course(driver, extracted: dict, graph_codes: set):
    """Add courses from PDF that aren't in the graph yet."""
    pdf_only = {c: v for c, v in extracted.items() if c not in graph_codes}
    added = 0

    for code, rec in pdf_only.items():
        syllabus_units_json = json.dumps(rec.get("syllabus_units") or [], ensure_ascii=False)
        assessment_json     = json.dumps(rec.get("assessment_summary") or {}, ensure_ascii=False)

        with driver.session() as session:
            session.run(
                """
                MERGE (c:Course {code: $code})
                SET
                    c.id                      = $code,
                    c.name                    = $name,
                    c.category                = $category,
                    c.ltpc                    = $ltpc,
                    c.credits                 = $credits,
                    c.department              = $department,
                    c.has_detailed_syllabus   = true,
                    c.is_official             = true,
                    c.source                  = 'pdf_syllabus',
                    c.regulation              = '2021',
                    c.course_rationale        = $course_rationale,
                    c.course_outcomes         = $course_outcomes,
                    c.syllabus_units          = $syllabus_units,
                    c.textbooks               = $textbooks,
                    c.assessment_summary      = $assessment_summary,
                    c.corequisites_raw        = $corequisites_raw,
                    c.progressive_courses_raw = $progressive_courses_raw,
                    c.description             = $description
                """,
                code                   = code,
                name                   = rec.get("name") or code,
                category               = rec.get("category") or "",
                ltpc                   = rec.get("ltpc") or "",
                credits                = rec.get("credits") or 0,
                department             = rec.get("department") or "",
                course_rationale       = rec.get("course_rationale") or [],
                course_outcomes        = rec.get("course_outcomes") or [],
                syllabus_units         = syllabus_units_json,
                textbooks              = rec.get("textbooks") or [],
                assessment_summary     = assessment_json,
                corequisites_raw       = rec.get("corequisites_raw") or "Nil",
                progressive_courses_raw= rec.get("progressive_courses_raw") or "Nil",
                description            = rec.get("description") or "",
            )
        added += 1
        print(f"  Added new :Course node: {code} ({rec.get('name')})")

    print(f"Step 3: Added {added} new course nodes")
    return added


def generate_embedding(text: str) -> list[float]:
    """Generate 768-dim embedding via local Ollama nomic-embed-text."""
    if requests is None:
        raise RuntimeError("requests package required for embedding generation")
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


def step4_refresh_embeddings(driver, extracted: dict):
    """Refresh 768-dim embeddings for all PDF-backed courses using clean structured text."""
    print(f"\nStep 4: Refreshing embeddings for {len(extracted)} PDF-backed courses via {EMBED_MODEL}...")
    t0 = time.time()
    refreshed = 0
    failed = 0

    for idx, (code, rec) in enumerate(extracted.items(), 1):
        unit_titles = [u["title"] for u in (rec.get("syllabus_units") or [])]
        co_text = " ".join(rec.get("course_outcomes") or [])
        embed_text = (
            f"Course: {code} - {rec.get('name') or code} | "
            f"Category: {rec.get('category') or ''} | "
            f"Department: {rec.get('department') or ''} | "
            f"Description: {rec.get('description') or ''} | "
            f"Topics: {', '.join(unit_titles)} | "
            f"Outcomes: {co_text}"
        )
        try:
            vec = generate_embedding(embed_text)
            with driver.session(database=NEO4J_DATABASE) as session:
                session.run(
                    """
                    MATCH (c:Course)
                    WHERE toUpper(c.code) = toUpper($code)
                    SET c.embedding = $embedding
                    """,
                    code=code,
                    embedding=vec,
                )
            refreshed += 1
            if idx % 25 == 0 or idx == len(extracted):
                print(f"  [{idx}/{len(extracted)}] embedded ({time.time() - t0:.1f}s elapsed)")
        except Exception as e:
            failed += 1
            print(f"  ERROR embedding {code}: {e}")

    print(f"Step 4 complete: {refreshed} refreshed, {failed} failed ({time.time() - t0:.1f}s)")
    return refreshed


def verify(driver):
    """Print verification counts."""
    with driver.session(database=NEO4J_DATABASE) as session:
        total = session.run("MATCH (c:Course) RETURN count(c) AS n").single()["n"]
        with_syl = session.run("MATCH (c:Course {has_detailed_syllabus: true}) RETURN count(c) AS n").single()["n"]
        without  = session.run("MATCH (c:Course {has_detailed_syllabus: false}) RETURN count(c) AS n").single()["n"]
        with_co  = session.run("MATCH (c:Course) WHERE size(c.course_outcomes) > 0 RETURN count(c) AS n").single()["n"]
        with_emb = session.run("MATCH (c:Course) WHERE c.embedding IS NOT NULL RETURN count(c) AS n").single()["n"]

    print("\n── Verification ─────────────────────────────────────────")
    print(f"  Total :Course nodes:          {total}")
    print(f"  has_detailed_syllabus=true:   {with_syl}")
    print(f"  has_detailed_syllabus=false:  {without}")
    print(f"  courses with course_outcomes: {with_co}")
    print(f"  courses with embeddings:      {with_emb}")
    print("─────────────────────────────────────────────────────────")


if __name__ == "__main__":
    print(f"Syllabus JSON: {SYLLABUS_JSON}")
    print(f"Courses JSON:  {COURSES_JSON}\n")

    # Load extracted data
    with open(SYLLABUS_JSON, encoding="utf-8") as f:
        extracted = json.load(f)
    print(f"Extracted courses (from PDF):  {len(extracted)}")

    # Load graph courses
    with open(COURSES_JSON, encoding="utf-8") as f:
        graph_courses = json.load(f)
    graph_codes = {c["code"] for c in graph_courses}
    print(f"Graph courses (courses.json):  {len(graph_codes)}")

    # Connect + verify write access
    driver = connect()
    test_write_access(driver)

    # Run updates
    step1_mark_all_no_syllabus(driver)
    step2_update_pdf_courses(driver, extracted, graph_codes)
    step3_add_pdf_only_course(driver, extracted, graph_codes)
    if "--skip-embeddings" not in sys.argv:
        step4_refresh_embeddings(driver, extracted)
    verify(driver)

    driver.close()
    print("\nDone. Neo4j course data and embeddings updated.")
