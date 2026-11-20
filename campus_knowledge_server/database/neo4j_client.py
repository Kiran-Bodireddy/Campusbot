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
from neo4j import GraphDatabase, RoutingControl, Driver, Query, READ_ACCESS

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
        self.password = password or os.getenv("NEO4J_PASSWORD", "")
        self.database = database or os.getenv("NEO4J_DATABASE", "neo4j")
        self.driver: Optional[Driver] = None
        self.is_connected = False
        self.neo4j_version: Optional[str] = None
        self.neo4j_edition: Optional[str] = None

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

        # Index faculty (and compute normalized_department & phone_shared_count at load time)
        from collections import Counter
        from campus_knowledge_server.config.matching_config import normalize_department_name
        HONORIFICS = {"dr", "dr.", "prof", "prof.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "hod", "dean"}
        fac_list = self.in_memory_data.get("faculty", [])
        phone_counts = Counter(
            (f.get("phone") or "").strip()
            for f in fac_list
            if (f.get("phone") or "").strip()
        )
        try:
            from campus_knowledge_server.database.directory_reconcile import reconcile_faculty
            n_fixed = reconcile_faculty(fac_list, os.path.dirname(UNIFIED_JSON_PATH), normalize_department_name)
            logger.info(f"Faculty directory reconciliation: {n_fixed} records corrected from official profile pages.")
        except Exception as e:
            logger.warning(f"Faculty directory reconciliation skipped ({e}).")
        for fac in fac_list:
            raw_dept = fac.get("department", "")
            if not fac.get("normalized_department"):
                fac["normalized_department"] = normalize_department_name(raw_dept)
            ph = (fac.get("phone") or "").strip()
            fac["phone"] = ph
            fac["phone_shared_count"] = phone_counts[ph] if ph else 0
            self._faculty_by_id[fac["id"]] = fac
            norm_name = fac["name"].lower().strip()
            self._faculty_by_name.setdefault(norm_name, []).append(fac)
            # Index distinct name tokens across all faculty members
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
        """Attempts connection to Neo4j database and loads graph-derived reference metadata."""
        self._graph_buildings: Dict[str, str] = {}
        self._graph_building_meta: Dict[str, Dict[str, Any]] = {}
        self._graph_departments: List[str] = []
        self._graph_faculty_index: List[Dict[str, str]] = []
        try:
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                connection_timeout=0.5
            )
            self.driver.verify_connectivity()
            self.is_connected = True
            self._detect_neo4j_version()
            logger.info(f"Connected successfully to Neo4j instance at {self.uri}")
            self.refresh_graph_reference_data()
        except Exception as e:
            self.is_connected = False
            self.neo4j_version = None
            self.neo4j_edition = None
            self.driver = None
            logger.info(f"Neo4j instance offline or not reachable ({e}). Operating in High-Speed In-Memory Graph Mode.")

    def _detect_neo4j_version(self):
        """Reads live Neo4j version and edition via dbms.components()."""
        if not self.driver:
            return
        try:
            with self.driver.session(database=self.database, default_access_mode=READ_ACCESS) as s:
                rec = s.run(
                    "CALL dbms.components() YIELD name, versions, edition "
                    "WHERE toLower(name) CONTAINS 'neo4j' "
                    "RETURN versions[0] AS version, edition LIMIT 1"
                ).single()
                if rec:
                    self.neo4j_version = str(rec.get("version") or "").strip() or None
                    ed = str(rec.get("edition") or "Community").strip()
                    self.neo4j_edition = ed.capitalize() if ed else "Community"
        except Exception:
            if not self.neo4j_edition:
                self.neo4j_edition = "Community"

    def get_engine_status(self, probe: bool = True) -> Dict[str, Any]:
        """Returns live Neo4j connectivity, edition/version, and display engine badge string."""
        if probe:
            if self.driver is not None:
                try:
                    self.driver.verify_connectivity()
                    self.is_connected = True
                    if not self.neo4j_version:
                        self._detect_neo4j_version()
                except Exception:
                    self.is_connected = False
                    self.neo4j_version = None
                    try:
                        self.driver.close()
                    except Exception:
                        pass
                    self.driver = None
            else:
                try:
                    drv = GraphDatabase.driver(
                        self.uri,
                        auth=(self.user, self.password),
                        connection_timeout=0.5
                    )
                    drv.verify_connectivity()
                    self.driver = drv
                    self.is_connected = True
                    self._detect_neo4j_version()
                    self.refresh_graph_reference_data()
                except Exception:
                    self.is_connected = False
                    self.neo4j_version = None
                    self.driver = None

        if self.is_connected:
            ed = self.neo4j_edition or "Community"
            ver_part = f"{ed} {self.neo4j_version}".strip() if self.neo4j_version else ed
            engine_label = f"Live Neo4j ({ver_part})"
        else:
            engine_label = "Fallback (not graph data)"

        return {
            "neo4j_connected": self.is_connected,
            "neo4j_version": self.neo4j_version,
            "neo4j_edition": self.neo4j_edition or ("Community" if self.is_connected else None),
            "engine": engine_label,
        }

    def refresh_graph_reference_data(self):
        """Loads canonical Building codes/names/metadata, Department names, and Faculty (id, name) index directly from live Neo4j."""
        if not (self.is_connected and self.driver):
            return
        try:
            b_rows = self.query_read(
                "MATCH (b:Building) WHERE b.code IS NOT NULL "
                "RETURN b.code AS code, b.name AS name, b.focus AS focus, "
                "b.floors AS floors, b.aliases AS aliases, b.campus AS campus LIMIT 500"
            )
            self._graph_buildings = {}
            self._graph_building_meta = {}
            for r in b_rows:
                code = str(r.get("code") or "").strip()
                name = str(r.get("name") or "").strip()
                if code and name:
                    self._graph_buildings[code] = name
                    self._graph_building_meta[code] = {
                        "code": code,
                        "name": name,
                        "focus": str(r.get("focus") or "").strip(),
                        "floors": r.get("floors"),
                        "aliases": [str(a).strip() for a in (r.get("aliases") or []) if a],
                        "campus": str(r.get("campus") or "").strip(),
                    }
            d_rows = self.query_read(
                "MATCH (d:Department) WHERE d.name IS NOT NULL RETURN DISTINCT d.name AS name LIMIT 1000"
            )
            self._graph_departments = [
                str(r["name"]).strip() for r in d_rows if r.get("name")
            ]
            f_rows = self.query_read(
                "MATCH (f:FacultyMember) WHERE f.id IS NOT NULL AND f.name IS NOT NULL "
                "RETURN f.id AS id, f.name AS name LIMIT 5000"
            )
            self._graph_faculty_index = [
                {"id": str(r["id"]).strip(), "name": str(r["name"]).strip()}
                for r in f_rows
                if r.get("id") and r.get("name")
            ]
        except Exception as e:
            logger.warning(f"Failed to load graph reference metadata from Neo4j: {e}")

    def get_graph_faculty_index(self) -> List[Dict[str, str]]:
        """Returns [{id, name}] of all FacultyMember nodes derived from live Neo4j at startup/reload."""
        if self.is_connected and self.driver:
            if not self._graph_faculty_index:
                self.refresh_graph_reference_data()
            return list(self._graph_faculty_index)
        return []

    def get_building_code_map(self) -> Dict[str, str]:
        """Returns {building_code: building_name} derived from live Neo4j Building nodes."""
        if self.is_connected and self.driver:
            if not self._graph_buildings:
                self.refresh_graph_reference_data()
            return dict(self._graph_buildings)
        # Offline fallback from loaded in-memory buildings
        return {
            str(b["code"]).strip(): str(b["name"]).strip()
            for b in self.in_memory_data.get("buildings", [])
            if b.get("code") and b.get("name")
        }

    def get_building_metadata_map(self) -> Dict[str, Dict[str, Any]]:
        """Returns {building_code: {code, name, focus, floors, aliases, campus}} derived from live Neo4j Building nodes."""
        if self.is_connected and self.driver:
            if not self._graph_building_meta:
                self.refresh_graph_reference_data()
            return dict(self._graph_building_meta)
        return {
            str(b["code"]).strip(): {
                "code": str(b["code"]).strip(),
                "name": str(b["name"]).strip(),
                "focus": str(b.get("focus") or "").strip(),
                "floors": b.get("floors"),
                "aliases": [str(a).strip() for a in (b.get("aliases") or []) if a],
                "campus": str(b.get("campus") or "").strip(),
            }
            for b in self.in_memory_data.get("buildings", [])
            if b.get("code") and b.get("name")
        }

    def get_building_alias_map(self) -> Dict[str, str]:
        """
        Derives {lowercase_alias: building_code} dynamically from live Neo4j Building nodes
        (code, name, parenthetical-stripped name, and stored aliases). Longest aliases ordered first.
        """
        meta_map = self.get_building_metadata_map()
        raw_aliases: Dict[str, str] = {}
        for code, info in meta_map.items():
            raw_aliases[code.lower()] = code
            name = info.get("name", "")
            if name:
                raw_aliases[name.lower()] = code
                no_paren = re.sub(r"\s*\([^)]*\)", "", name).strip().lower()
                if no_paren and len(no_paren) >= 3:
                    raw_aliases.setdefault(no_paren, code)
            for al in info.get("aliases") or []:
                al_low = al.strip().lower()
                if al_low:
                    raw_aliases[al_low] = code
        # Return ordered longest-first so multi-word aliases match before shorter substrings
        return dict(sorted(raw_aliases.items(), key=lambda kv: -len(kv[0])))

    def get_department_names(self) -> List[str]:
        """Returns Department names derived from live Neo4j Department nodes."""
        if self.is_connected and self.driver:
            if not self._graph_departments:
                self.refresh_graph_reference_data()
            return list(self._graph_departments)
        return []

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
    def query_read(self, cypher: str, parameters: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> List[Dict[str, Any]]:
        """Executes a governed read-only Cypher query against Neo4j with AST security validation, READ_ACCESS session, and enforced transaction timeout."""
        if not self.is_connected or not self.driver:
            raise ConnectionError("Live Neo4j instance not connected.")

        # Enforce read-only AST safety & bound caps
        from campus_knowledge_server.security.ast_validator import ASTSecurityValidator
        sanitized_cypher = ASTSecurityValidator.assert_safe(cypher)

        with self.driver.session(database=self.database, default_access_mode=READ_ACCESS) as session:
            result = session.run(Query(sanitized_cypher, timeout=timeout), parameters or {})
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
                    c.is_official = row.is_official,
                    c.source = 'official'
            """, {"batch": course_batch})
            counts["courses"] = len(course_batch)

            # 3. Batch Ingest All Faculty Members (All 2,501) with cabin, email, and cleaned specialization
            fac_batch = self.in_memory_data.get("faculty", [])
            for i in range(0, len(fac_batch), 500):
                chunk = fac_batch[i:i + 500]
                session.run("""
                    UNWIND $batch AS row
                    MERGE (f:FacultyMember {id: row.id})
                    SET f.name = row.name, f.designation = row.designation,
                        f.department = row.department, f.college = row.college,
                        f.specialization = trim(replace(row.specialization, ',', ' ')),
                        f.experience = row.experience,
                        f.email = row.email,
                        f.cabin = row.cabin,
                        f.normalized_department = row.normalized_department,
                        f.source = 'official'
                """, {"batch": chunk})
            counts["faculty"] = len(fac_batch)

            # 4. Batch Ingest Rooms (Synthetic)
            room_batch = self.in_memory_data.get("rooms", [])
            session.run("""
                UNWIND $batch AS row
                MERGE (r:Room {id: row.id})
                SET r.room_number = row.room_number, r.building_code = row.building_code,
                    r.type = row.type, r.capacity = row.capacity,
                    r.source = 'synthetic'
            """, {"batch": room_batch})
            counts["rooms"] = len(room_batch)

            # 4b. Ingest Buildings and link to rooms
            bldg_batch = self.in_memory_data.get("buildings", [])
            if bldg_batch:
                session.run("""
                    UNWIND $batch AS row
                    MERGE (b:Building {code: row.code})
                    SET b.name = row.name, b.floors = row.floors,
                        b.source = 'official'
                """, {"batch": bldg_batch})
                session.run("""
                    MATCH (r:Room)
                    MATCH (b:Building {code: r.building_code})
                    MERGE (r)-[:LOCATED_IN]->(b)
                """)
                counts["buildings"] = len(bldg_batch)

            # 5. Prerequisites (Official Regulations 2021)
            prereq_batch = self.in_memory_data.get("prerequisites", [])
            session.run("""
                UNWIND $batch AS row
                MATCH (target:Course {code: row.target_course_code})
                MATCH (prereq:Course {code: row.prerequisite_course_code})
                MERGE (target)-[:REQUIRES_PREREQUISITE {condition: row.condition, source: 'official'}]->(prereq)
            """, {"batch": prereq_batch})
            counts["prereqs"] = len(prereq_batch)

            # 5b. Teaching Assignments (Synthetic Allocation)
            teach_batch = self.in_memory_data.get("teaching_assignments", [])
            if teach_batch:
                for i in range(0, len(teach_batch), 500):
                    chunk = teach_batch[i:i + 500]
                    session.run("""
                        UNWIND $batch AS row
                        MATCH (c:Course {code: row.course_code})
                        MATCH (f:FacultyMember {id: row.faculty_id})
                        MERGE (f)-[:TEACHES {source: 'synthetic'}]->(c)
                    """, {"batch": chunk})
                counts["teaching_assignments"] = len(teach_batch)

            # 5c. Room Schedules (Synthetic Timetable)
            sched_batch = self.in_memory_data.get("schedules", [])
            if sched_batch:
                for i in range(0, len(sched_batch), 500):
                    chunk = sched_batch[i:i + 500]
                    session.run("""
                        UNWIND $batch AS row
                        MATCH (r:Room {id: row.room_id})
                        MATCH (c:Course {code: row.course_code})
                        MERGE (r)-[:OCCUPIES {day: row.day, slot: row.slot, source: 'synthetic'}]->(c)
                    """, {"batch": chunk})
                counts["schedules"] = len(sched_batch)

            # 6. Batch Ingest Academic Programs & Admission Requirements (Official - Program label only)
            if self.admission_eligibility:
                prog_batch = self.admission_eligibility
                session.run("""
                    UNWIND $batch AS row
                    MERGE (p:Program {id: row.program_id})
                    SET p.name = row.program_name,
                        p.faculty = row.faculty,
                        p.department = row.department,
                        p.degree_level = row.degree_level,
                        p.min_education = row.min_education,
                        p.mandatory_subjects = row.mandatory_subjects,
                        p.min_percentage_general = row.min_percentage_general,
                        p.min_percentage_reserved = row.min_percentage_reserved,
                        p.required_entrance_exam = row.required_entrance_exam,
                        p.official_eligibility_text = row.official_eligibility_text,
                        p.source = 'official'
                """, {"batch": prog_batch})
                counts["programs"] = len(prog_batch)

            # 7. Batch Ingest Semester Curriculum Allocations (:Program)-[:OFFERS_IN_SEMESTER]->(:Course)
            # Match canonical admission :Program nodes by normalized name so no orphan stub :Program nodes are created
            alloc_batch = self._curriculum_allocations
            if alloc_batch:
                def _norm_prog(name: str) -> str:
                    s = (name or "").lower().replace("b.tech.", "btech").replace("b.tech", "btech").replace("m.tech.", "mtech").replace("m.tech", "mtech")
                    s = re.sub(r"\bwith\s+specialization\s+in\b|\bw/s\s+in\b|\bw/s\b|\bin\b|\band\b|\bof\b", " ", s)
                    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()

                adm_by_norm = {_norm_prog(p.get("program_name", "")): p.get("program_id") for p in self.admission_eligibility if p.get("program_id")}
                resolved_batch = []
                for row in alloc_batch:
                    pid = adm_by_norm.get(_norm_prog(row.get("program_name", "")))
                    if pid:
                        r_copy = dict(row)
                        r_copy["program_id"] = pid
                        resolved_batch.append(r_copy)

                batch_size = 500
                for i in range(0, len(resolved_batch), batch_size):
                    chunk = resolved_batch[i:i + batch_size]
                    session.run("""
                        UNWIND $batch AS row
                        MATCH (p:Program {id: row.program_id})
                        MATCH (c:Course {code: row.course_code})
                        MERGE (p)-[r:OFFERS_IN_SEMESTER {semester: row.semester}]->(c)
                        SET r.academic_year = row.academic_year,
                            r.credits = row.credits,
                            r.ltpc = row.ltpc,
                            r.category = row.category,
                            r.source = 'official'
                    """, {"batch": chunk})
                counts["curriculum_allocations"] = len(resolved_batch)

            # 8. Department Graph Nodes and Edges (:IN_DEPARTMENT, :OFFERED_BY_DEPARTMENT)
            session.run("CREATE CONSTRAINT dept_name IF NOT EXISTS FOR (d:Department) REQUIRE d.name IS UNIQUE")
            session.run("""
                MATCH (f:FacultyMember) WHERE f.department IS NOT NULL AND trim(f.department) <> ''
                MERGE (d:Department {name: trim(f.department)}) SET d.source = 'official'
                MERGE (f)-[:IN_DEPARTMENT {source: 'official'}]->(d)
            """)
            session.run("""
                MATCH (c:Course) WHERE c.department IS NOT NULL AND trim(c.department) <> ''
                MERGE (d:Department {name: trim(c.department)}) SET d.source = 'official'
                MERGE (c)-[:OFFERED_BY_DEPARTMENT {source: 'official'}]->(d)
            """)
            session.run("""
                MATCH (p:Program) WHERE p.department IS NOT NULL AND trim(p.department) <> ''
                MERGE (d:Department {name: trim(p.department)}) SET d.source = 'official'
                MERGE (p)-[:OFFERED_BY_DEPARTMENT {source: 'official'}]->(d)
            """)

        return {"status": "success", "counts": counts}

# Global singleton client instance
_client_instance: Optional[CampusGraphClient] = None

def get_graph_client() -> CampusGraphClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = CampusGraphClient()
    return _client_instance
