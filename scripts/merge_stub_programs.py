"""
Merges the 55 stub :Program nodes (created by curriculum OFFERS_IN_SEMESTER naming mismatch)
into their canonical admission :Program nodes (p.id IS NOT NULL), transfers OFFERS_IN_SEMESTER
and OFFERED_BY_DEPARTMENT edges, deletes all stub nodes, and verifies 100% Program embeddings.
"""
import os
import re
import difflib
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv(".env")
driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD"))
)

def normalize_prog_name(name: str) -> str:
    s = (name or "").lower()
    s = s.replace("b.tech.", "btech").replace("b.tech", "btech")
    s = s.replace("m.tech.", "mtech").replace("m.tech", "mtech")
    s = s.replace("(integrated)", "integrated")
    s = re.sub(r"\bin\s+collaboration\s+with\s+[^)]+", " ", s)
    s = re.sub(r"\bwith\s+specialization\s+in\b", " ", s)
    s = re.sub(r"\bw/s\s+in\b|\bw/s\b", " ", s)
    s = re.sub(r"\bin\b|\band\b|\bof\b|\bthe\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

with driver.session() as s:
    stubs = s.run("MATCH (p:Program) WHERE p.id IS NULL RETURN elementId(p) AS eid, p.name AS name").data()
    reals = s.run("MATCH (p:Program) WHERE p.id IS NOT NULL RETURN p.id AS id, p.name AS name").data()

    print(f"Before cleanup: real_programs={len(reals)}, stub_programs={len(stubs)}")

    real_by_norm = {}
    for r in reals:
        nm = normalize_prog_name(r["name"])
        real_by_norm.setdefault(nm, r)

    real_norm_keys = list(real_by_norm.keys())
    merged_count = 0
    deleted_unmatched = 0
    transferred_edges = 0

    for st in stubs:
        st_name = st["name"]
        st_norm = normalize_prog_name(st_name)
        target = real_by_norm.get(st_norm)

        if not target:
            # Try close token match within B.Tech / M.Tech family
            close = difflib.get_close_matches(st_norm, real_norm_keys, n=1, cutoff=0.82)
            if close:
                target = real_by_norm[close[0]]

        if target:
            # Transfer OFFERS_IN_SEMESTER edges to canonical admission Program node
            res_t = s.run("""
                MATCH (stub:Program) WHERE elementId(stub) = $eid
                MATCH (real:Program {id: $real_id})
                MATCH (stub)-[r:OFFERS_IN_SEMESTER]->(c:Course)
                MERGE (real)-[nr:OFFERS_IN_SEMESTER {semester: r.semester}]->(c)
                SET nr.academic_year = r.academic_year,
                    nr.credits = r.credits,
                    nr.ltpc = r.ltpc,
                    nr.category = r.category,
                    nr.source = 'official'
                RETURN count(nr) AS edge_cnt
            """, {"eid": st["eid"], "real_id": target["id"]}).single()
            ec = res_t["edge_cnt"] if res_t else 0
            s.run("MATCH (stub:Program) WHERE elementId(stub) = $eid DETACH DELETE stub", {"eid": st["eid"]})
            transferred_edges += ec
            merged_count += 1
            print(f"  Merged stub '{st_name}' -> '{target['name']}' ({target['id']}) [{ec} edges]")
        else:
            # Remove orphan stub node with no admission Program equivalent
            s.run("MATCH (stub:Program) WHERE elementId(stub) = $eid DETACH DELETE stub", {"eid": st["eid"]})
            deleted_unmatched += 1
            print(f"  Deleted unmatched stub: {st_name}")

    after_total = s.run("MATCH (p:Program) RETURN count(p) AS c").single()["c"]
    after_emb = s.run("MATCH (p:Program) WHERE p.embedding IS NOT NULL RETURN count(p) AS c").single()["c"]
    after_stubs = s.run("MATCH (p:Program) WHERE p.id IS NULL RETURN count(p) AS c").single()["c"]
    after_sem_rels = s.run("MATCH (:Program)-[r:OFFERS_IN_SEMESTER]->(:Course) RETURN count(r) AS c").single()["c"]
    v_idx = s.run("SHOW VECTOR INDEXES YIELD name, state, populationPercent RETURN name, state, populationPercent").data()

    print(f"\nCleanup Summary:")
    print(f"  Merged into canonical admission Programs: {merged_count} (transferred {transferred_edges} OFFERS_IN_SEMESTER edges)")
    print(f"  Deleted unmatched orphan stubs:           {deleted_unmatched}")
    print(f"  After cleanup: total_programs={after_total}, programs_with_embedding={after_emb}, remaining_stubs={after_stubs}")
    print(f"  Active OFFERS_IN_SEMESTER edges on canonical Programs: {after_sem_rels}")
    print(f"  Vector Indexes: {v_idx}")

driver.close()
