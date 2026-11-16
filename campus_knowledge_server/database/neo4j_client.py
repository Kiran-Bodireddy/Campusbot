"""
Neo4j Graph Database Client with Hybrid In-Memory Fallback
Provides governed read-only access to Neo4j with vector index support,
plus a high-performance in-memory graph representation loaded from
the unified campus catalog for offline testing & rapid evaluation.
"""

import os
import re
import json
import logging
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from neo4j import GraphDatabase, RoutingControl, Driver

load_dotenv()

logger = logging.getLogger("campus_graph.database")
logging.basicConfig(level=logging.INFO)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIFIED_JSON_PATH = os.path.join(BASE_DIR, "data", "campus_graph_unified.json")
ADMISSION_JSON_PATH = os.path.join(BASE_DIR, "data", "courses", "admission_eligibility_master.json")
CURRICULA_JSON_PATH = os.path.join(BASE_DIR, "data", "courses", "curricula_semester_master.json")

class CampusGraphClient:
    def __init__(self, uri: Optional[str] = None, user: Optional[str] = None, password: Optional[str] = None, database: Optional[str] = None):
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "Jeevan@223")
        self.database = database or os.getenv("NEO4J_DATABASE", "rai")
        self.driver: Optional[Driver] = None
        self.is_connected = False

        # In-memory graph indices for high-speed fallback & test harness
        self.in_memory_data: Dict[str, Any] = {}
        self._course_by_code: Dict[str, Dict[str, Any]] = {}
        self._course_by_id: Dict[str, Dict[str, Any]] = {}
        self._faculty_by_id: Dict[str, Dict[str, Any]] = {}
        self._faculty_by_name: Dict[str, List[Dict[str, Any]]] = {}
        self._faculty_by_token: Dict[str, List[Dict[str, Any]]] = {}
        self._room_by_id: Dict[str, Dict[str, Any]] = {}
        self._prereqs_by_target: Dict[str, List[Dict[str, Any]]] = {}
        self._schedules_by_room: Dict[str, List[Dict[str, Any]]] = {}
        self._schedules_by_course: Dict[str, List[Dict[str, Any]]] = {}
        self._teaching_by_course: Dict[str, List[Dict[str, Any]]] = {}
        self._teaching_by_faculty: Dict[str, List[Dict[str, Any]]] = {}
        self.admission_eligibility: List[Dict[str, Any]] = []
        self._admission_by_id: Dict[str, Dict[str, Any]] = {}
        self.curricula_master: Dict[str, Any] = {}
        self._curriculum_allocations: List[Dict[str, Any]] = []
        self._curriculum_by_program: Dict[str, List[Dict[str, Any]]] = {}
        self._curriculum_by_prog_sem: Dict[tuple, List[Dict[str, Any]]] = {}
        self._curriculum_by_course: Dict[str, List[Dict[str, Any]]] = {}

        self._load_in_memory_graph()
        self._init_neo4j_connection()

    def _load_in_memory_graph(self):
        """Loads and indexes the synthesized campus graph from JSON."""
        if not os.path.exists(UNIFIED_JSON_PATH):
            logger.warning(f"Unified graph JSON not found at {UNIFIED_JSON_PATH}")
            return

        with open(UNIFIED_JSON_PATH, "r", encoding="utf-8") as f:
            self.in_memory_data = json.load(f)

        # Index courses
        for c in self.in_memory_data.get("courses", []):
            self._course_by_id[c["id"]] = c
            self._course_by_code[c["code"].upper()] = c

        # Index faculty
        HONORIFICS = {"dr", "dr.", "prof", "prof.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "hod", "dean"}
        for fac in self.in_memory_data.get("faculty", []):
            self._faculty_by_id[fac["id"]] = fac
            norm_name = fac["name"].lower().strip()
            self._faculty_by_name.setdefault(norm_name, []).append(fac)
            # Index significant name tokens (e.g. "godfrey", "winster")
            tokens = [re.sub(r"[^\w]", "", w) for w in norm_name.split()]
            for t in tokens:
                if len(t) >= 3 and t not in HONORIFICS:
                    self._faculty_by_token.setdefault(t, []).append(fac)

        # Index rooms
        for r in self.in_memory_data.get("rooms", []):
            self._room_by_id[r["id"]] = r

        # Index prerequisites
        for p in self.in_memory_data.get("prerequisites", []):
            target = p["target_course_code"].upper()
            self._prereqs_by_target.setdefault(target, []).append(p)

        # Index schedules
        for s in self.in_memory_data.get("schedules", []):
            self._schedules_by_room.setdefault(s["room_id"], []).append(s)
            self._schedules_by_course.setdefault(s["course_code"].upper(), []).append(s)

        # Index teaching assignments
        for t in self.in_memory_data.get("teaching_assignments", []):
            self._teaching_by_course.setdefault(t["course_code"].upper(), []).append(t)
            self._teaching_by_faculty.setdefault(t["faculty_id"], []).append(t)

        # Index admission eligibility and enrich with fees, duration, and campuses
        prog_meta_map = {}
        if os.path.exists(UNIFIED_JSON_PATH):
            try:
                with open(UNIFIED_JSON_PATH, "r", encoding="utf-8") as uf:
                    u_data = json.load(uf)
                for up in u_data.get("programs", []):
                    prog_meta_map[up["name"].strip().lower()] = up
            except Exception as e:
                logger.warning(f"Could not load unified program metadata: {e}")

        if os.path.exists(ADMISSION_JSON_PATH):
            with open(ADMISSION_JSON_PATH, "r", encoding="utf-8") as f:
                self.admission_eligibility = json.load(f)
            for prog in self.admission_eligibility:
                up_info = prog_meta_map.get(prog["program_name"].strip().lower(), {})
                prog["annual_fee_inr"] = up_info.get("annual_fee_inr", 0)
                prog["duration"] = up_info.get("duration", "4 Years")
                prog["campuses"] = up_info.get("campuses", ["Kattankulathur Main Campus"])
                prog["about"] = up_info.get("about", "")
                self._admission_by_id[prog["program_id"]] = prog

        # Index curriculum allocations from unified graph or master JSON
        raw_allocs = self.in_memory_data.get("curriculum_allocations", [])
        if os.path.exists(CURRICULA_JSON_PATH):
            try:
                with open(CURRICULA_JSON_PATH, "r", encoding="utf-8") as f:
                    self.curricula_master = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load curricula master: {e}")

        for ca in raw_allocs:
            self._curriculum_allocations.append(ca)
            p_name_norm = ca.get("program_name", "").strip().lower()
            sem = ca.get("semester", 1)
            c_code = ca.get("course_code", "").upper()

            self._curriculum_by_program.setdefault(p_name_norm, []).append(ca)
            self._curriculum_by_prog_sem.setdefault((p_name_norm, sem), []).append(ca)
            self._curriculum_by_course.setdefault(c_code, []).append(ca)

        logger.info(
            f"In-Memory Graph Indexed: {len(self._course_by_code)} Courses, "
            f"{len(self._faculty_by_id)} Faculty, {len(self._room_by_id)} Rooms, "
            f"{len(self.admission_eligibility)} Program Admission Requirements, "
            f"{len(self._curriculum_allocations)} Curriculum Semester Allocations."
        )

    def _init_neo4j_connection(self):
        """Attempts connection to Neo4j database."""
        try:
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                connection_timeout=0.5
            )
            self.driver.verify_connectivity()
            self.is_connected = True
            logger.info(f"Connected successfully to Neo4j instance at {self.uri}")
        except Exception as e:
            self.is_connected = False
            self.driver = None
            logger.info(f"Neo4j instance offline or not reachable ({e}). Operating in High-Speed In-Memory Graph Mode.")

    def close(self):
        if self.driver:
            self.driver.close()

    def find_entities(self, query: str, max_per_type: int = 5) -> Dict[str, List[Dict[str, Any]]]:
        """
        Federated cross-entity graph scanner.
        Scans all 4 campus entity domains (Faculty, Courses, Rooms/Buildings, Programs)
        simultaneously and returns matched entities ranked by relevance.
        """
        import re
        q_raw = query.strip()
        q_lower = q_raw.lower()
        NOISE = {
            "who", "is", "where", "what", "which", "are", "tell", "me", "about",
            "the", "a", "an", "in", "at", "for", "does", "do", "find", "show",
            "search", "can", "you", "please", "details", "info", "give", "get"
        }
        raw_tokens = re.findall(r"\w+", q_lower)
        sig_tokens = [t for t in raw_tokens if len(t) >= 2 and t not in NOISE]

        results: Dict[str, List[Dict[str, Any]]] = {
            "faculty": [],
            "courses": [],
            "rooms": [],
            "programs": [],
            "buildings": []
        }

        # 1. Faculty matching
        matched_faculty_ids = set()
        for t in sig_tokens:
            if t in self._faculty_by_token:
                for fac in self._faculty_by_token[t]:
                    if fac["id"] not in matched_faculty_ids:
                        matched_faculty_ids.add(fac["id"])
                        results["faculty"].append(fac)
                    if len(results["faculty"]) >= max_per_type:
                        break
            if len(results["faculty"]) >= max_per_type:
                break

        if len(results["faculty"]) < max_per_type:
            for fac in self.in_memory_data.get("faculty", []):
                if fac["id"] in matched_faculty_ids:
                    continue
                fac_name = fac.get("name", "").lower()
                fac_spec = fac.get("specialization", "").lower()
                fac_cabin = fac.get("cabin", "").lower()
                if q_lower in fac_name or q_lower in fac_cabin:
                    matched_faculty_ids.add(fac["id"])
                    results["faculty"].append(fac)
                elif sig_tokens and any(t in fac_spec for t in sig_tokens if len(t) >= 3):
                    matched_faculty_ids.add(fac["id"])
                    results["faculty"].append(fac)
                if len(results["faculty"]) >= max_per_type:
                    break

        # 2. Courses matching
        matched_course_codes = set()
        q_norm = q_raw.upper()
        if q_norm in self._course_by_code:
            matched_course_codes.add(q_norm)
            results["courses"].append(self._course_by_code[q_norm])

        for c in self.in_memory_data.get("courses", []):
            code = c.get("code", "").upper()
            if code in matched_course_codes:
                continue
            name = c.get("name", "").lower()
            if q_lower in name or q_lower in code.lower():
                matched_course_codes.add(code)
                results["courses"].append(c)
            elif sig_tokens and any(t in name for t in sig_tokens if len(t) >= 3):
                matched_course_codes.add(code)
                results["courses"].append(c)
            if len(results["courses"]) >= max_per_type:
                break

        # 3. Rooms & Buildings matching
        matched_room_ids = set()
        if q_norm in self._room_by_id:
            matched_room_ids.add(q_norm)
            results["rooms"].append(self._room_by_id[q_norm])

        for r in self.in_memory_data.get("rooms", []):
            rid = r.get("id", "")
            if rid in matched_room_ids:
                continue
            if q_lower in rid.lower():
                matched_room_ids.add(rid)
                results["rooms"].append(r)
            if len(results["rooms"]) >= max_per_type:
                break

        for b in self.in_memory_data.get("buildings", []):
            b_code = b.get("code", "").lower()
            b_name = b.get("name", "").lower()
            if q_lower in b_code or q_lower in b_name or (sig_tokens and any(t in b_name for t in sig_tokens if len(t) >= 3)):
                results["buildings"].append(b)

        # 4. Programs / Admissions matching
        matched_prog_ids = set()
        for p in self.admission_eligibility:
            pid = p.get("program_id", "")
            pname = p.get("program_name", "").lower()
            deg = p.get("degree", "").lower()
            if q_lower in pname or q_lower in deg:
                if pid not in matched_prog_ids:
                    matched_prog_ids.add(pid)
                    results["programs"].append(p)
            elif sig_tokens and any(t in pname for t in sig_tokens if len(t) >= 3):
                if pid not in matched_prog_ids:
                    matched_prog_ids.add(pid)
                    results["programs"].append(p)
            if len(results["programs"]) >= max_per_type:
                break

        return results

    # Governed Query Primitives
    def query_read(self, cypher: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Executes a governed read-only Cypher query against Neo4j if online."""
        if not self.is_connected or not self.driver:
            raise ConnectionError("Live Neo4j instance not connected.")

        with self.driver.session(database=self.database) as session:
            result = session.run(cypher, parameters or {}, routing=RoutingControl.READ)
            return [record.data() for record in result]

    def seed_live_neo4j(self) -> Dict[str, Any]:
        """Seeds nodes and relationships into the live Neo4j database."""
        if not self.is_connected or not self.driver:
            return {"status": "error", "message": "Neo4j is not connected."}

        logger.info(f"Seeding nodes and relationships into Neo4j database '{self.database}'...")
        counts = {"courses": 0, "faculty": 0, "rooms": 0, "prereqs": 0, "programs": 0}
        with self.driver.session(database=self.database) as session:
            # 1. Constraints
            session.run("CREATE CONSTRAINT course_code IF NOT EXISTS FOR (c:Course) REQUIRE c.code IS UNIQUE")
            session.run("CREATE CONSTRAINT faculty_id IF NOT EXISTS FOR (f:FacultyMember) REQUIRE f.id IS UNIQUE")
            session.run("CREATE CONSTRAINT room_id IF NOT EXISTS FOR (r:Room) REQUIRE r.id IS UNIQUE")
            session.run("CREATE CONSTRAINT program_id IF NOT EXISTS FOR (p:Program) REQUIRE p.id IS UNIQUE")
            session.run("CREATE INDEX program_name_idx IF NOT EXISTS FOR (p:Program) ON (p.name)")

            # 2. Batch Ingest Courses
            course_batch = self.in_memory_data.get("courses", [])
            session.run("""
                UNWIND $batch AS row
                MERGE (c:Course {code: row.code})
                SET c.id = row.id, c.name = row.name, c.credits = row.credits,
                    c.level = row.level, c.department = row.department, c.description = row.description,
                    c.category = row.category, c.ltpc = row.ltpc, c.regulation = row.regulation,
                    c.is_official = row.is_official
            """, {"batch": course_batch})
            counts["courses"] = len(course_batch)

            # 3. Batch Ingest Faculty
            fac_batch = self.in_memory_data.get("faculty", [])[:500]
            session.run("""
                UNWIND $batch AS row
                MERGE (f:FacultyMember {id: row.id})
                SET f.name = row.name, f.designation = row.designation,
                    f.department = row.department, f.college = row.college,
                    f.specialization = row.specialization, f.experience = row.experience
            """, {"batch": fac_batch})
            counts["faculty"] = len(fac_batch)

            # 4. Batch Ingest Rooms
            room_batch = self.in_memory_data.get("rooms", [])
            session.run("""
                UNWIND $batch AS row
                MERGE (r:Room {id: row.id})
                SET r.room_number = row.room_number, r.building_code = row.building_code,
                    r.type = row.type, r.capacity = row.capacity
            """, {"batch": room_batch})
            counts["rooms"] = len(room_batch)

            # 5. Prerequisites
            prereq_batch = self.in_memory_data.get("prerequisites", [])
            session.run("""
                UNWIND $batch AS row
                MATCH (target:Course {code: row.target_course_code})
                MATCH (prereq:Course {code: row.prerequisite_course_code})
                MERGE (target)-[:REQUIRES_PREREQUISITE {condition: row.condition}]->(prereq)
            """, {"batch": prereq_batch})
            counts["prereqs"] = len(prereq_batch)

            # 6. Batch Ingest Academic Programs & Admission Requirements
            if self.admission_eligibility:
                prog_batch = self.admission_eligibility
                session.run("""
                    UNWIND $batch AS row
                    MERGE (p:Course:Program {id: row.program_id})
                    SET p:Course, p:Program,
                        p.name = row.program_name,
                        p.faculty = row.faculty,
                        p.department = row.department,
                        p.degree_level = row.degree_level,
                        p.min_education = row.min_education,
                        p.mandatory_subjects = row.mandatory_subjects,
                        p.min_percentage_general = row.min_percentage_general,
                        p.min_percentage_reserved = row.min_percentage_reserved,
                        p.required_entrance_exam = row.required_entrance_exam,
                        p.official_eligibility_text = row.official_eligibility_text
                """, {"batch": prog_batch})
                counts["programs"] = len(prog_batch)

            # 7. Batch Ingest Semester Curriculum Allocations (:Program)-[:OFFERS_IN_SEMESTER]->(:Course)
            alloc_batch = self._curriculum_allocations
            if alloc_batch:
                batch_size = 500
                for i in range(0, len(alloc_batch), batch_size):
                    chunk = alloc_batch[i:i + batch_size]
                    session.run("""
                        UNWIND $batch AS row
                        MERGE (p:Program {name: row.program_name})
                        MERGE (c:Course {code: row.course_code})
                        MERGE (p)-[r:OFFERS_IN_SEMESTER {semester: row.semester}]->(c)
                        SET r.academic_year = row.academic_year,
                            r.credits = row.credits,
                            r.ltpc = row.ltpc,
                            r.category = row.category
                    """, {"batch": chunk})
                counts["curriculum_allocations"] = len(alloc_batch)

        return {"status": "success", "counts": counts}

# Global singleton client instance
_client_instance: Optional[CampusGraphClient] = None

def get_graph_client() -> CampusGraphClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = CampusGraphClient()
    return _client_instance
