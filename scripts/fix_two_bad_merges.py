import os
from dotenv import load_dotenv
from neo4j import GraphDatabase
from campus_knowledge_server.database.neo4j_client import CampusGraphClient

load_dotenv(".env")
client = CampusGraphClient()
biotech_rows = [
    r for r in client._curriculum_allocations
    if r.get("program_name") == "B.Tech in Biotechnology"
]
print(f"Loaded {len(biotech_rows)} canonical rows for 'B.Tech in Biotechnology'")

d = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
)
with d.session() as s:
    # 1. Remove wrongly transferred B.Tech EV edges from M.Tech PROG-109
    r1 = s.run("MATCH (p:Program {id: 'PROG-109'})-[r:OFFERS_IN_SEMESTER]->() DELETE r RETURN count(r) AS deleted").single()
    print(f"Removed wrongly fuzzy-merged edges from PROG-109 (M.Tech. Electric Vehicle Technology): {r1['deleted']}")

    # 2. Reset PROG-317 (B.Tech. Biotechnology) edges to strictly canonical B.Tech in Biotechnology
    r2 = s.run("MATCH (p:Program {id: 'PROG-317'})-[r:OFFERS_IN_SEMESTER]->() DELETE r RETURN count(r) AS deleted").single()
    s.run("""
        UNWIND $batch AS row
        MATCH (p:Program {id: 'PROG-317'})
        MATCH (c:Course {code: row.course_code})
        MERGE (p)-[r:OFFERS_IN_SEMESTER {semester: row.semester}]->(c)
        SET r.academic_year = row.academic_year,
            r.credits = row.credits,
            r.ltpc = row.ltpc,
            r.category = row.category,
            r.source = 'official'
    """, {"batch": biotech_rows})
    r3 = s.run("MATCH (p:Program {id: 'PROG-317'})-[r:OFFERS_IN_SEMESTER]->() RETURN count(r) AS cnt").single()
    print(f"Reset PROG-317 (B.Tech. Biotechnology): deleted {r2['deleted']} mixed edges, restored {r3['cnt']} canonical edges")

    # 3. Verify final Program & Vector Index counts
    tot = s.run("MATCH (p:Program) RETURN count(p) AS c").single()["c"]
    emb = s.run("MATCH (p:Program) WHERE p.embedding IS NOT NULL RETURN count(p) AS c").single()["c"]
    stubs = s.run("MATCH (p:Program) WHERE p.id IS NULL RETURN count(p) AS c").single()["c"]
    sem_rels = s.run("MATCH (:Program)-[r:OFFERS_IN_SEMESTER]->(:Course) RETURN count(r) AS c").single()["c"]
    v_idx = s.run("SHOW VECTOR INDEXES YIELD name, state, populationPercent RETURN name, state, populationPercent").data()
    print(f"Final Verification: total_programs={tot}, programs_with_embedding={emb}, remaining_stubs={stubs}, offers_in_semester_edges={sem_rels}")
    print(f"Vector Indexes: {v_idx}")

d.close()
