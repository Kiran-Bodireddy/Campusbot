import os
import requests
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv(".env")
driver = GraphDatabase.driver(os.getenv("NEO4J_URI"), auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD")))

def search(query):
    resp = requests.post("http://127.0.0.1:11434/api/embeddings", json={"model": "nomic-embed-text", "prompt": query})
    vec = resp.json()["embedding"]
    with driver.session() as s:
        cypher = """
        CALL db.index.vector.queryNodes('building_embeddings', 3, $vec)
        YIELD node as b, score
        OPTIONAL MATCH (r:Room)-[:LOCATED_IN]->(b)
        RETURN b.code as code, b.name as name, b.floors as floors, b.focus as focus, round(score, 3) as score, count(r) as room_count
        """
        return s.run(cypher, {"vec": vec}).data()

queries = [
    "where is placement office and company interviews?",
    "where can first years do welding carpentry and physics labs?",
    "where are the nanotechnology electron microscopes?",
    "where is the law library and moot court?",
    "central air conditioned library with books"
]

for q in queries:
    print(f"\n--- Query: '{q}' ---")
    results = search(q)
    for r in results:
        print(f"  [{r['code']}] {r['name']} | Floors: {r['floors']} | Score: {r['score']} | Focus: {r['focus']}")

driver.close()
