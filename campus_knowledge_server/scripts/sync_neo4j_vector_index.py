"""
Syncs course embeddings directly into Neo4j native vector index 'course_embeddings'.
Uses local Ollama 'nomic-embed-text' (768 dimensions) to populate Course.embedding.
"""
import sys
import os
import time
import requests
from typing import List, Dict, Any

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from campus_knowledge_server.database.neo4j_client import get_graph_client


def sync_course_embeddings(batch_size: int = 50, ollama_url: str = "http://localhost:11434"):
    client = get_graph_client()
    if not client.is_connected or not client.driver:
        print("[ERROR] Cannot sync embeddings: Neo4j is offline.")
        return False

    print("[INFO] Connected to Neo4j. Ensuring vector index 'course_embeddings'...")
    with client.driver.session(database=client.database) as session:
        # Create vector index if not exists (768 dimensions for nomic-embed-text)
        session.run("""
        CREATE VECTOR INDEX course_embeddings IF NOT EXISTS
        FOR (c:Course) ON (c.embedding)
        OPTIONS {indexConfig: {
          `vector.dimensions`: 768,
          `vector.similarity_function`: 'cosine'
        }}
        """)

        # Fetch courses that do not yet have an embedding
        records = list(session.run("""
        MATCH (c:Course)
        WHERE c.embedding IS NULL
        RETURN c.code AS code, c.name AS name, c.department AS department, c.description AS description
        """))
        total_missing = len(records)
        print(f"[INFO] Found {total_missing} courses requiring vector embeddings.")

        if total_missing == 0:
            print("[INFO] All courses in Neo4j already have vector embeddings.")
            return True

        updated_count = 0
        t0 = time.time()
        for i in range(0, total_missing, batch_size):
            batch = records[i:i + batch_size]
            batch_updates = []
            for r in batch:
                code = r["code"]
                name = r["name"] or ""
                dept = r["department"] or ""
                desc = r["description"] or ""
                text = f"{code} {name} {dept} {desc}".strip()
                try:
                    resp = requests.post(
                        f"{ollama_url}/api/embeddings",
                        json={"model": "nomic-embed-text", "prompt": text},
                        timeout=15.0
                    )
                    if resp.status_code == 200:
                        emb = resp.json().get("embedding")
                        if emb and len(emb) == 768:
                            batch_updates.append({"code": code, "embedding": emb})
                except Exception as e:
                    print(f"[WARN] Failed embedding for {code}: {e}")

            if batch_updates:
                session.run("""
                UNWIND $updates AS u
                MATCH (c:Course {code: u.code})
                SET c.embedding = u.embedding
                """, {"updates": batch_updates})
                updated_count += len(batch_updates)
                elapsed = time.time() - t0
                print(f"[PROGRESS] Embedded {updated_count}/{total_missing} courses ({updated_count/elapsed:.1f} courses/sec)")

        print(f"[SUCCESS] Finished populating Neo4j vector index with {updated_count} course embeddings in {time.time() - t0:.2f}s.")
        return True


if __name__ == "__main__":
    sync_course_embeddings()
