"""
Neo4j Program Vector Index Generator (High-Performance Batched)
Precomputes 768-dimensional embeddings for all 485 Academic Programs using
Ollama 'POST /api/embed' (nomic-embed-text), writes them onto Program.embedding
in Neo4j Community, and creates the native vector index 'program_embeddings'.
"""

import os
import sys
import json
import time
import requests
import logging
from typing import List, Dict, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from campus_knowledge_server.database.neo4j_client import CampusGraphClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("seed_program_vector_index")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = "nomic-embed-text"
VECTOR_DIM = 768
BATCH_SIZE = 30

PROGRAMS_JSON_PATH = os.path.join(BASE_DIR, "campus_knowledge_server", "data", "courses", "srmist_programs_master.json")
if not os.path.exists(PROGRAMS_JSON_PATH):
    PROGRAMS_JSON_PATH = os.path.join(BASE_DIR, "srmist_programs_master.json")

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

def seed_program_vector_index():
    client = CampusGraphClient()
    if not client.is_connected or not client.driver:
        logger.error("Neo4j is not connected.")
        sys.exit(1)

    # Load 'about' text mapping if available
    about_map = {}
    if os.path.exists(PROGRAMS_JSON_PATH):
        try:
            with open(PROGRAMS_JSON_PATH, "r", encoding="utf-8") as f:
                raw_progs = json.load(f)
            for p in raw_progs:
                name_key = p.get("program_name", "").strip().lower()
                about_map[name_key] = p.get("about_program", "")
        except Exception as e:
            logger.warning(f"Could not load programs json: {e}")

    with client.driver.session(database=client.database) as session:
        # 1. Create Vector Index for Programs
        logger.info("Ensuring native Neo4j vector index 'program_embeddings' exists...")
        session.run(f"""
            CREATE VECTOR INDEX program_embeddings IF NOT EXISTS
            FOR (p:Program) ON (p.embedding)
            OPTIONS {{indexConfig: {{`vector.dimensions`: {VECTOR_DIM}, `vector.similarity_function`: 'cosine'}}}}
        """)

        # 2. Enrich 'about' property on Program nodes if not present
        if about_map:
            logger.info("Enriching Program nodes with 'about' text...")
            for name_key, about_text in about_map.items():
                if about_text:
                    session.run("""
                        MATCH (p:Program)
                        WHERE toLower(trim(p.name)) = $name
                        SET p.about = $about
                    """, {"name": name_key, "about": about_text})

        # 3. Fetch programs needing embeddings
        programs = session.run("""
            MATCH (p:Program)
            RETURN p.id as id, p.name as name, p.department as department,
                   p.faculty as faculty, p.degree_level as degree_level,
                   p.about as about, p.official_eligibility_text as eligibility
        """).data()

        total = len(programs)
        logger.info(f"Found {total} Program nodes to embed.")

        t0 = time.time()
        for start_idx in range(0, total, BATCH_SIZE):
            chunk = programs[start_idx:start_idx + BATCH_SIZE]
            texts = [
                f"Degree Program: {p['name']}. "
                f"Level: {p.get('degree_level') or ''}. "
                f"Faculty: {p.get('faculty') or ''}. "
                f"Department: {p.get('department') or ''}. "
                f"About: {p.get('about') or ''}. "
                f"Eligibility Criteria: {p.get('eligibility') or ''}"
                for p in chunk
            ]

            vectors = get_embeddings_batch(texts)
            batch_data = [
                {"id": chunk[j]["id"], "embedding": vectors[j]}
                for j in range(len(chunk))
            ]

            session.run("""
                UNWIND $batch as row
                MATCH (p:Program {id: row.id})
                SET p.embedding = row.embedding
            """, {"batch": batch_data})

            done = min(start_idx + BATCH_SIZE, total)
            elapsed = round(time.time() - t0, 1)
            print(f"Progress: {done}/{total} programs embedded and written ({elapsed}s elapsed)...", flush=True)

        logger.info(f"Program vector embedding complete! Total elapsed: {round(time.time() - t0, 2)}s.")

        # 4. Test Program Vector Search
        logger.info("Testing native Neo4j program vector search...")
        test_query = "renewable energy electric vehicles autonomous driving"
        test_vec = get_single_embedding(test_query)
        test_res = session.run("""
            CALL db.index.vector.queryNodes('program_embeddings', 3, $vec)
            YIELD node, score
            RETURN node.id as id, node.name as name, node.degree_level as level, score
        """, {"vec": test_vec}).data()

        print("\n=== PROGRAM VECTOR SEARCH TEST RESULTS ===", flush=True)
        print(f"Query: '{test_query}'", flush=True)
        for r in test_res:
            print(f"- [{r['id']}] {r['name']} ({r['level']}) -> Score: {round(r['score'], 4)}", flush=True)

if __name__ == "__main__":
    seed_program_vector_index()
