"""
Neo4j Course Vector Index Generator (High-Performance Batched)
Precomputes 768-dimensional embeddings for all 668 courses using Ollama 'POST /api/embed',
writes them onto Course.embedding in Neo4j Community, and tests the native vector index.
"""

import os
import sys
import time
import requests
import logging
from typing import List, Dict, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from campus_knowledge_server.database.neo4j_client import CampusGraphClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("seed_vector_index")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = "nomic-embed-text"
VECTOR_DIM = 768
BATCH_SIZE = 30

def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    resp = requests.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": texts},
        timeout=60
    )
    if resp.status_code == 200:
        return resp.json().get("embeddings", [])
    raise RuntimeError(f"Ollama batch embedding failure ({resp.status_code}): {resp.text}")

def get_single_embedding(text: str) -> List[float]:
    resp = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=30
    )
    if resp.status_code == 200:
        return resp.json().get("embedding", [])
    raise RuntimeError(f"Ollama embedding failure ({resp.status_code}): {resp.text}")

def seed_course_vector_index():
    client = CampusGraphClient()
    if not client.is_connected or not client.driver:
        logger.error("Neo4j is not connected.")
        sys.exit(1)

    with client.driver.session(database=client.database) as session:
        # 1. Create Vector Index
        logger.info("Ensuring native Neo4j vector index 'course_embeddings' exists...")
        session.run(f"""
            CREATE VECTOR INDEX course_embeddings IF NOT EXISTS
            FOR (c:Course) ON (c.embedding)
            OPTIONS {{indexConfig: {{`vector.dimensions`: {VECTOR_DIM}, `vector.similarity_function`: 'cosine'}}}}
        """)

        # 2. Fetch courses needing embeddings
        courses = session.run("""
            MATCH (c:Course)
            WHERE c.embedding IS NULL
            RETURN c.code as code, c.name as name, c.department as department,
                   c.category as category, c.description as description
        """).data()

        total = len(courses)
        logger.info(f"Found {total} Course nodes needing vector embeddings.")
        if total == 0:
            logger.info("All courses already have embeddings.")
        else:
            t0 = time.time()
            for start_idx in range(0, total, BATCH_SIZE):
                chunk = courses[start_idx:start_idx + BATCH_SIZE]
                texts = [
                    f"Course Code: {c['code']}. "
                    f"Title: {c['name']}. "
                    f"Department: {c['department'] or ''}. "
                    f"Category: {c['category'] or ''}. "
                    f"Description: {c['description'] or ''}"
                    for c in chunk
                ]

                vectors = get_embeddings_batch(texts)
                batch_data = [
                    {"code": chunk[j]["code"], "embedding": vectors[j]}
                    for j in range(len(chunk))
                ]

                session.run("""
                    UNWIND $batch as row
                    MATCH (c:Course {code: row.code})
                    SET c.embedding = row.embedding
                """, {"batch": batch_data})

                done = min(start_idx + BATCH_SIZE, total)
                elapsed = round(time.time() - t0, 1)
                print(f"Progress: {done}/{total} courses embedded and written ({elapsed}s elapsed)...", flush=True)

            logger.info(f"Vector embedding complete! Total elapsed: {round(time.time() - t0, 2)}s.")

        # 3. Test Vector Search
        logger.info("Testing native Neo4j vector search...")
        test_query = "deep learning neural networks artificial intelligence"
        test_vec = get_single_embedding(test_query)
        test_res = session.run("""
            CALL db.index.vector.queryNodes('course_embeddings', 3, $vec)
            YIELD node, score
            RETURN node.code as code, node.name as name, node.department as department, score
        """, {"vec": test_vec}).data()

        print("\n=== VECTOR SEARCH TEST RESULTS ===", flush=True)
        print(f"Query: '{test_query}'", flush=True)
        for r in test_res:
            print(f"- [{r['code']}] {r['name']} ({r['department']}) -> Score: {round(r['score'], 4)}", flush=True)

if __name__ == "__main__":
    seed_course_vector_index()
