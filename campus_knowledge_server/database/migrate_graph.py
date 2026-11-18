"""
Campus Graph Database Migration Script
Executes G1-G4 schema and graph fixes against live Neo4j Community instance:
- G1: Remove Course label from 430 Program nodes (Course=668, Program=485)
- G2: Create Department nodes and connect IN_DEPARTMENT and OFFERED_BY_DEPARTMENT edges
- G3: Write email and cabin onto FacultyMember nodes, clean specialization trailing commas
- G4: Tag synthetic nodes/edges with source='synthetic' and official data with source='official'
"""

import os
import sys
import logging
from typing import Dict, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from campus_knowledge_server.database.neo4j_client import CampusGraphClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("graph_migration")

def migrate_database():
    client = CampusGraphClient()
    if not client.is_connected or not client.driver:
        logger.error("Failed to connect to Neo4j. Migration aborted.")
        sys.exit(1)

    with client.driver.session(database=client.database) as session:
        # -------------------------------------------------------------
        # G1: Remove Course label from Program nodes
        # -------------------------------------------------------------
        logger.info("G1: Removing Course label from Program nodes...")
        g1_res = session.run("""
            MATCH (p:Program:Course)
            REMOVE p:Course
            RETURN count(p) as count
        """).single()
        logger.info(f"G1 completed: Removed :Course label from {g1_res['count']} Program nodes.")

        # -------------------------------------------------------------
        # G2: Create Department nodes and connect edges
        # -------------------------------------------------------------
        logger.info("G2: Creating Department nodes and connecting relationships...")
        # Constraint on Department name
        session.run("CREATE CONSTRAINT dept_name IF NOT EXISTS FOR (d:Department) REQUIRE d.name IS UNIQUE")
        
        # 1. Departments from Faculty
        session.run("""
            MATCH (f:FacultyMember)
            WHERE f.department IS NOT NULL AND trim(f.department) <> ''
            MERGE (d:Department {name: trim(f.department)})
        """)

        # 2. Departments from Courses
        session.run("""
            MATCH (c:Course)
            WHERE c.department IS NOT NULL AND trim(c.department) <> ''
            MERGE (d:Department {name: trim(c.department)})
        """)

        # 3. Connect Faculty -> Department
        session.run("""
            MATCH (f:FacultyMember)
            WHERE f.department IS NOT NULL AND trim(f.department) <> ''
            MATCH (d:Department {name: trim(f.department)})
            MERGE (f)-[:IN_DEPARTMENT]->(d)
        """)

        # 4. Connect Course -> Department
        session.run("""
            MATCH (c:Course)
            WHERE c.department IS NOT NULL AND trim(c.department) <> ''
            MATCH (d:Department {name: trim(c.department)})
            MERGE (c)-[:OFFERED_BY_DEPARTMENT]->(d)
        """)

        # 5. Connect Program -> Department
        session.run("""
            MATCH (p:Program)
            WHERE p.department IS NOT NULL AND trim(p.department) <> ''
            MERGE (d:Department {name: trim(p.department)})
            MERGE (p)-[:OFFERED_BY_DEPARTMENT]->(d)
        """)

        g2_dept_count = session.run("MATCH (d:Department) RETURN count(d) as count").single()["count"]
        g2_f_unlinked = session.run("MATCH (f:FacultyMember) WHERE NOT (f)-[:IN_DEPARTMENT]->() RETURN count(f) as count").single()["count"]
        g2_c_unlinked = session.run("MATCH (c:Course) WHERE NOT (c)-[:OFFERED_BY_DEPARTMENT]->() RETURN count(c) as count").single()["count"]
        logger.info(f"G2 completed: {g2_dept_count} Department nodes created. Unlinked faculty: {g2_f_unlinked}, unlinked courses: {g2_c_unlinked}.")

        # -------------------------------------------------------------
        # G3: Write email, cabin, and clean specialization on FacultyMember
        # -------------------------------------------------------------
        logger.info("G3: Writing email and cabin to FacultyMember nodes...")
        fac_batch = client.in_memory_data.get("faculty", [])
        cleaned_batch = []
        for fac in fac_batch:
            raw_spec = fac.get("specialization") or ""
            clean_spec = raw_spec.strip().rstrip(",").strip()
            cleaned_batch.append({
                "id": fac["id"],
                "email": fac.get("email", ""),
                "cabin": fac.get("cabin", "Staff Room (TBA)"),
                "specialization": clean_spec
            })

        for i in range(0, len(cleaned_batch), 500):
            chunk = cleaned_batch[i:i + 500]
            session.run("""
                UNWIND $batch as row
                MATCH (f:FacultyMember {id: row.id})
                SET f.email = row.email,
                    f.cabin = row.cabin,
                    f.specialization = row.specialization
            """, {"batch": chunk})

        sample_fac = session.run("""
            MATCH (f:FacultyMember)
            WHERE f.cabin IS NOT NULL AND f.email IS NOT NULL
            RETURN f.id, f.name, f.cabin, f.email, f.specialization
            LIMIT 1
        """).single()
        logger.info(f"G3 completed: Sample updated faculty: {dict(sample_fac)}")

        # -------------------------------------------------------------
        # G4: Tag synthetic vs official provenance
        # -------------------------------------------------------------
        logger.info("G4: Tagging provenance (synthetic vs official)...")
        session.run("MATCH (r:Room) SET r.source = 'synthetic'")
        session.run("MATCH ()-[r:TEACHES]->() SET r.source = 'synthetic'")
        session.run("MATCH ()-[r:OCCUPIES]->() SET r.source = 'synthetic'")

        session.run("MATCH (c:Course) SET c.source = 'official'")
        session.run("MATCH (p:Program) SET p.source = 'official'")
        session.run("MATCH (d:Department) SET d.source = 'official'")
        session.run("MATCH ()-[r:REQUIRES_PREREQUISITE]->() SET r.source = 'official'")
        session.run("MATCH ()-[r:OFFERS_IN_SEMESTER]->() SET r.source = 'official'")
        session.run("MATCH ()-[r:IN_DEPARTMENT]->() SET r.source = 'official'")
        session.run("MATCH ()-[r:OFFERED_BY_DEPARTMENT]->() SET r.source = 'official'")

        logger.info("G4 completed: Provenance tags updated.")

        # -------------------------------------------------------------
        # Verification Summary
        # -------------------------------------------------------------
        labels = [r.data() for r in session.run("MATCH (n) RETURN labels(n) as labels, count(*) as count ORDER BY count DESC")]
        rels = [r.data() for r in session.run("MATCH ()-[r]->() RETURN type(r) as rel, count(*) as count ORDER BY count DESC")]
        sources = [r.data() for r in session.run("MATCH (n) RETURN n.source as source, count(*) as count")]
        
        print("\n=== FINAL MIGRATION VERIFICATION ===")
        print("Node Labels:", labels)
        print("Relationships:", rels)
        print("Node Provenance:", sources)

if __name__ == "__main__":
    migrate_database()
