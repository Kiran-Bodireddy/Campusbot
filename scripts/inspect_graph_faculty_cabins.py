import os, re
from collections import Counter
from dotenv import load_dotenv
from neo4j import GraphDatabase, READ_ACCESS

load_dotenv(".env")
d = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
)
with d.session(default_access_mode=READ_ACCESS) as s:
    bldgs = s.run("MATCH (b:Building) RETURN b.code AS code, b.name AS name ORDER BY b.code").data()
    print(f"Buildings in Neo4j ({len(bldgs)}):")
    for b in bldgs:
        print(f"  {b['code']}: {b['name']}")

    cabins = s.run("MATCH (f:FacultyMember) RETURN f.cabin AS cabin").data()
    print(f"\nTotal FacultyMember nodes: {len(cabins)}")
    codes = sorted([b["code"].upper() for b in bldgs if b.get("code")], key=len, reverse=True)
    # Check unambiguous pattern: building code at start or word boundary followed by an explicit separator (-, /, space)
    sep_pat = re.compile(r"^(?:" + "|".join(re.escape(c) for c in codes) + r")(?=\s*[-/\s])", re.IGNORECASE)
    unambig = 0
    ambig = 0
    empty_or_na = 0
    sample_ambig = Counter()
    sample_unambig = Counter()
    for row in cabins:
        c = (row.get("cabin") or "").strip()
        if not c or c.lower() in ("n/a", "none", "unknown"):
            empty_or_na += 1
            continue
        if sep_pat.match(c):
            unambig += 1
            sample_unambig[c] += 1
        else:
            ambig += 1
            sample_ambig[c] += 1
    print(f"Cabins: unambiguous={unambig}, ambiguous={ambig}, empty/na={empty_or_na}")
    print("Top 15 unambiguous cabins:", sample_unambig.most_common(15))
    print("Top 25 ambiguous cabins:", sample_ambig.most_common(25))

    # Also check shared exact names (case-insensitive)
    dups = s.run("""
        MATCH (f:FacultyMember)
        WITH toLower(trim(f.name)) AS lname, collect(f.name) AS names, count(f) AS cnt
        WHERE cnt > 1
        RETURN names[0] AS name, cnt ORDER BY cnt DESC LIMIT 10
    """).data()
    print(f"\nTop duplicate exact names in Neo4j: {dups}")
d.close()
