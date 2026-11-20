"""
Interactive Live Neo4j Seeder for SRMIST Campus Knowledge Graph
Connects to local Neo4j Desktop / Server and ingests all courses, faculty,
rooms, prerequisites, and programs into the graph database.
"""

import os
import sys
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from campus_knowledge_server.database.neo4j_client import CampusGraphClient

def main():
    print("=" * 65)
    print(" SRMIST Campus Knowledge Graph - Live Neo4j Database Seeder")
    print("=" * 65)

    uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "")
    db = os.getenv("NEO4J_DATABASE", "neo4j")

    print(f"\n[+] Target URI      : {uri}")
    print(f"[+] User            : {user}")
    print(f"[+] Database        : {db}")
    print(f"[+] Connecting to Neo4j...")

    client = CampusGraphClient(uri=uri, user=user, password=pwd, database=db)

    if not client.is_connected:
        print("\n[!] Could not connect to Neo4j on port 7687.")
        print("[*] Note: We detected Neo4j Desktop is installed on your PC.")
        print("[*] To connect:")
        print("    1. Open Neo4j Desktop.")
        print("    2. Click the green 'Start' button next to your project/DBMS.")
        print("    3. Ensure NEO4J_PASSWORD in '.env' matches your DBMS credentials.")
        print("    4. Run: python seed.py\n")
        return

    print("\n[✔] Connected successfully to live Neo4j instance!")
    print("[+] Seeding nodes, relationships, and constraints into Neo4j...")

    result = client.seed_live_neo4j()

    if result.get("status") == "success":
        counts = result.get("counts", {})
        print("\n" + "=" * 65)
        print(" [✔] SEEDING COMPLETE! GRAPH IS LIVE IN NEO4J")
        print("=" * 65)
        print(f" * Courses Seeded          : {counts.get('courses', 0)}")
        print(f" * Faculty Members Seeded  : {counts.get('faculty', 0)}")
        print(f" * Rooms & Buildings Seeded: {counts.get('rooms', 0)}")
        print(f" * Prerequisite Edges      : {counts.get('prereqs', 0)}")
        print(f" * Academic Programs Seeded: {counts.get('programs', 0)}")
        print(f" * Curriculum Edges Seeded : {counts.get('curriculum_allocations', 0)}")
        print("=" * 65)
        print("\nOpen http://localhost:7474 in your browser to view and explore the graph visually!\n")
    else:
        print(f"\n[!] Seeding failed: {result.get('message')}")

    client.close()

if __name__ == "__main__":
    main()

