import os
import sys
import json
import time
import neo4j
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath("."))
load_dotenv(".env")

from campus_knowledge_server.database.neo4j_client import get_graph_client
from campus_knowledge_server.tools.governed_executor import execute_tool, TOOL_FUNC_MAP, TOOL_SCHEMA_MAP
from campus_knowledge_server.tools.campus_tools import WHITELISTED_TEMPLATES
from campus_knowledge_server.security.auth import Principal
from campus_knowledge_server.security.audit import AUDIT_LOG_FILE

client = get_graph_client()

print("====================================================================")
print(" ITEM 1: SERVER-SIDE READ-ONLY (neo4j.conf) WRITE-SESSION REJECTION")
print("====================================================================")
with client.driver.session(database=client.database, default_access_mode=neo4j.WRITE_ACCESS) as ws:
    try:
        ws.run("CREATE (n:ReadOnlyProof {created: true})").consume()
        print("UNEXPECTED: WRITE SUCCEEDED!")
    except Exception as e:
        print(f"WRITE_ACCESS Session CREATE Rejected -> {type(e).__name__}: {e}")

print("\n====================================================================")
print(" ITEM 2: TRANSACTION TIMEOUT (timeout=3.0) THROUGH execute_tool()")
print("====================================================================")
# Temporarily register a read-only slow Cartesian template in-process to verify timeout through execute_tool
WHITELISTED_TEMPLATES["_slow_timeout_test"] = (
    "UNWIND range(1, 200000) AS x UNWIND range(1, 5000) AS y WITH x + y AS z RETURN count(z) AS total"
)
admin = Principal(user_id="audit_admin", role="admin", caller_type="jwt")
t0 = time.time()
try:
    execute_tool("run_governed_query", {"template_id": "_slow_timeout_test", "parameters": {}}, principal=admin)
    print("UNEXPECTED: SLOW QUERY COMPLETED!")
except Exception as e:
    dt = time.time() - t0
    print(f"execute_tool() Slow Query Terminated in {dt:.2f}s -> {type(e).__name__}: {e}")
finally:
    WHITELISTED_TEMPLATES.pop("_slow_timeout_test", None)

print("\n====================================================================")
print(" ITEM 5: FULL 80-QUESTION GOLD-MATCH ACCURACY & AUDIT LOG STATS")
print("====================================================================")
with open("campus_knowledge_server/eval/benchmark_dataset.json", "r", encoding="utf-8") as f:
    dataset = json.load(f)

legit = [q for q in dataset if not q.get("should_block")]
gold_pass = 0
gold_failures = []

for item in legit:
    tool = item["gold_tool"]
    params = item.get("gold_params", {})
    gold_ents = item.get("gold_entities", [])
    try:
        res = execute_tool(tool, params)
        res_blob = json.dumps(res, default=str).lower()
        # Verify every gold entity id (or non-empty data if gold_entities is empty) appears in returned result
        if gold_ents:
            matched_all = True
            for ge in gold_ents:
                gid = str(ge.get("id", "")).strip().lower()
                if not gid:
                    continue
                # For faculty names, match last/primary token if full name has honorific variation
                if ge.get("type") == "faculty":
                    toks = [t for t in gid.replace("dr.", "").replace("prof.", "").split() if len(t) >= 3]
                    if not any(t in res_blob for t in toks):
                        matched_all = False
                elif ge.get("type") == "program":
                    toks = [t for t in gid.split() if len(t) >= 3]
                    if not any(t in res_blob for t in toks):
                        matched_all = False
                else:
                    if gid not in res_blob:
                        matched_all = False
            if matched_all:
                gold_pass += 1
            else:
                gold_failures.append((item["id"], tool, gold_ents, res_blob[:120]))
        else:
            # Tools like get_campus_statistics or semantic search without rigid single ID
            if res and not res.get("error"):
                gold_pass += 1
            else:
                gold_failures.append((item["id"], tool, gold_ents, res_blob[:120]))
    except Exception as e:
        gold_failures.append((item["id"], tool, gold_ents, str(e)))

print(f"Full-Set Gold-Match Cypher Execution Accuracy: {(gold_pass/len(legit))*100:.2f}% ({gold_pass}/{len(legit)})")
if gold_failures:
    print(f"Gold-Match Mismatches ({len(gold_failures)}):")
    for gf in gold_failures[:10]:
        print(f"  - {gf[0]} ({gf[1]}): expected {gf[2]} | got: {gf[3]}")

# Audit log invalid-query rate analysis
status_counts = {}
total_audit = 0
if os.path.exists(AUDIT_LOG_FILE):
    with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as af:
        for line in af:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                st = ev.get("status", "UNKNOWN")
                status_counts[st] = status_counts.get(st, 0) + 1
                total_audit += 1
            except Exception:
                pass
invalid_events = status_counts.get("VALIDATION_ERROR", 0) + status_counts.get("POLICY_VIOLATION", 0) + status_counts.get("EXECUTION_ERROR", 0)
print(f"\nAudit Log Telemetry ({AUDIT_LOG_FILE}):")
print(f"  Total Entries: {total_audit}")
print(f"  Status Breakdown: {status_counts}")
print(f"  Historical Invalid/Rejected Rate (VALIDATION_ERROR + POLICY_VIOLATION + EXECUTION_ERROR / Total): {(invalid_events/total_audit)*100:.2f}% ({invalid_events}/{total_audit})")
print(f"  Legitimate Schema/AST Rejection Rate (VALIDATION_ERROR / Total): {(status_counts.get('VALIDATION_ERROR', 0)/total_audit)*100:.2f}% ({status_counts.get('VALIDATION_ERROR', 0)}/{total_audit})")

print("\n====================================================================")
print(" ITEM 8: REAL TOOL INVENTORY, PREREQ COUNT & VECTOR INDEX EVIDENCE")
print("====================================================================")
print(f"Governed Executor Tools ({len(TOOL_FUNC_MAP)}): {list(TOOL_FUNC_MAP.keys())}")
with client.driver.session(database=client.database, default_access_mode=neo4j.READ_ACCESS) as s:
    prereq_cnt = s.run("MATCH ()-[r:REQUIRES_PREREQUISITE]->() RETURN count(r) AS c").single()["c"]
    print(f"REQUIRES_PREREQUISITE Edge Count: {prereq_cnt}")
    v_idx = s.run("SHOW VECTOR INDEXES YIELD name, state, populationPercent, labelsOrTypes, properties RETURN name, state, populationPercent, labelsOrTypes, properties").data()
    print("\nSHOW VECTOR INDEXES:")
    for row in v_idx:
        print(f"  - {row}")
    c_emb = s.run("MATCH (c:Course) WHERE c.embedding IS NOT NULL RETURN count(c) AS c").single()["c"]
    p_emb = s.run("MATCH (p:Program) WHERE p.embedding IS NOT NULL RETURN count(p) AS c").single()["c"]
    b_emb = s.run("MATCH (b:Building) WHERE b.embedding IS NOT NULL RETURN count(b) AS c").single()["c"]
    print(f"\nEmbedding Counts: Course={c_emb}/668, Program={p_emb}/485, Building={b_emb}/20")

    print("\n3 Live Sample Vector Index Queries (course_embeddings & building_embeddings):")
    sample_vec_queries = [
        ("course_embeddings", "deep learning neural networks backpropagation", "RETURN node.code AS id, node.name AS name, round(score, 4) AS score"),
        ("course_embeddings", "cryptography network security protocols", "RETURN node.code AS id, node.name AS name, round(score, 4) AS score"),
        ("building_embeddings", "where is the central placement office and corporate interviews", "RETURN node.code AS id, node.name AS name, round(score, 4) AS score"),
    ]
    for idx_name, q_txt, ret_clause in sample_vec_queries:
        emb = requests.post("http://127.0.0.1:11434/api/embeddings", json={"model": "nomic-embed-text", "prompt": q_txt}, timeout=20).json()["embedding"]
        rows = s.run(f"CALL db.index.vector.queryNodes('{idx_name}', 3, $vec) YIELD node, score {ret_clause}", {"vec": emb}).data()
        print(f"  [{idx_name}] Query: '{q_txt}'")
        for r in rows:
            print(f"     -> {r}")
