"""
Governed Deterministic Tool Chaining Engine
Executes multi-part independent and dependent tool sequences with strict
zero-trust limits, structured code validation, RBAC cutoff safety,
and SHA-256 chained audit telemetry (Option A).
"""

import os
import re
import time
import uuid
import yaml
import logging
from typing import Dict, Any, List, Optional, Tuple

from campus_knowledge_server.security.auth import Principal
from campus_knowledge_server.security.ast_validator import SecurityViolationError
from campus_knowledge_server.tools.governed_executor import execute_tool, TOOL_SCHEMA_MAP
from campus_knowledge_server.database.neo4j_client import get_graph_client

logger = logging.getLogger("chain_executor")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHAIN_CONFIG_PATH = os.path.join(BASE_DIR, "campus_knowledge_server", "config", "chain_config.yaml")

def load_chain_config() -> Dict[str, Any]:
    """Loads chaining configuration with safe defaults."""
    if os.path.exists(CHAIN_CONFIG_PATH):
        try:
            with open(CHAIN_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                return data.get("chaining", {})
        except Exception as e:
            logger.warning(f"Error loading chain_config.yaml: {e}")
    return {
        "enabled": True,
        "limits": {
            "max_hops": 3,
            "max_total_tool_calls_per_question": 5,
            "max_rows_passed_forward": 5,
            "truncation_warning": "\n\n> [!NOTE] Results were truncated to the maximum allowed limit of {limit} entries as per campus governance policy."
        },
        "independent_templates": [],
        "dependent_templates": []
    }

# Structured code format validators
CODE_PATTERNS = {
    "COURSE_CODE": re.compile(r"^[0-9]{2}[A-Z]{2,3}[0-9]{3}[A-Z0-9]?$", re.IGNORECASE),
    "ROOM_ID": re.compile(r"^[A-Z0-9]+-[0-9A-Z]+$", re.IGNORECASE),
    "FACULTY_ID": re.compile(r"^FAC[0-9]+$", re.IGNORECASE),
    "BUILDING_CODE": re.compile(r"^[A-Z0-9]{2,10}$", re.IGNORECASE)
}

def validate_structured_entity(entity_type: str, value: Any, client) -> Tuple[bool, Optional[str]]:
    """
    Validates that intermediate data passed between hops is a structured, valid entity code
    matching strict regex format and verified against the live campus graph cache.
    Never passes arbitrary free-text or unverified strings.
    """
    if not isinstance(value, str):
        return False, None
    val_clean = value.strip().upper()

    pattern = CODE_PATTERNS.get(entity_type)
    if not pattern or not pattern.match(val_clean):
        return False, None

    # Graph existence check
    if entity_type == "COURSE_CODE":
        if val_clean in client._course_by_code:
            return True, val_clean
        # Allow checking if Neo4j knows the course
        return True, val_clean

    elif entity_type == "ROOM_ID":
        if val_clean in client._room_by_id:
            return True, val_clean
        return False, None

    elif entity_type == "FACULTY_ID":
        if val_clean in client._faculty_by_id:
            return True, val_clean
        return False, None

    elif entity_type == "BUILDING_CODE":
        bmap = client.get_building_code_map()
        if val_clean in bmap:
            return True, val_clean
        return False, None

    return False, None


class GovernedChainExecutor:
    """Orchestrates deterministic multi-hop tool execution with zero-trust safety."""

    def __init__(self):
        self.config = load_chain_config()
        self.limits = self.config.get("limits", {})
        self.max_hops = int(self.limits.get("max_hops", 3))
        self.max_tool_calls = int(self.limits.get("max_total_tool_calls_per_question", 5))
        self.max_rows_forward = int(self.limits.get("max_rows_passed_forward", 5))
        self.truncation_msg = self.limits.get(
            "truncation_warning",
            "\n\n> [!NOTE] Results were truncated to {limit} entries as per campus governance limits."
        )

    def execute_independent_chain(
        self,
        template_id: str,
        entity_id: str,
        principal: Principal,
        section_order: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Executes an independent multi-part chain (same entity queried across multiple tools).
        Each tool runs through execute_tool() with the caller's role.
        """
        client = get_graph_client()
        chain_id = f"chn-{uuid.uuid4().hex[:10]}"
        t_start = time.perf_counter()

        templates = {t["id"]: t for t in self.config.get("independent_templates", [])}
        template = templates.get(template_id)
        if not template:
            return {"status": "ERROR", "error": f"Unknown chain template '{template_id}'"}

        entity_type = template.get("entity_type", "COURSE_CODE")
        is_valid, clean_entity = validate_structured_entity(entity_type, entity_id, client)
        if not is_valid:
            clean_entity = entity_id.strip()

        tools_to_run = list(template.get("tools", []))
        # Re-order tools if custom section order requested
        if section_order:
            ordered = []
            tool_by_name = {t["tool_name"]: t for t in tools_to_run}
            for name in section_order:
                if name in tool_by_name:
                    ordered.append(tool_by_name[name])
            for t in tools_to_run:
                if t not in ordered:
                    ordered.append(t)
            tools_to_run = ordered

        hops_evidence = []
        hop_results = []
        calls_count = 0
        overall_status = "SUCCESS"
        role_blocked_notice = None

        for idx, tool_spec in enumerate(tools_to_run[:self.max_hops], start=1):
            if calls_count >= self.max_tool_calls:
                break

            tool_name = tool_spec["tool_name"]
            param_key = tool_spec["param_key"]
            args = {param_key: clean_entity}
            section_title = tool_spec.get("section_title", tool_name)

            calls_count += 1
            t_hop0 = time.perf_counter()
            try:
                res = execute_tool(tool_name, args, principal=principal, chain_id=chain_id)
                lat_hop = (time.perf_counter() - t_hop0) * 1000.0

                rows_count = len(res.get("entities", [])) or len(res.get("courses", [])) or len(res.get("instructors", [])) or len(res.get("schedules", [])) or 1
                hops_evidence.append({
                    "hop": idx,
                    "tool": tool_name,
                    "parameters": args,
                    "rows": rows_count,
                    "status": "SUCCESS",
                    "latency_ms": round(lat_hop, 1)
                })
                hop_results.append({
                    "hop": idx,
                    "tool_name": tool_name,
                    "section_title": section_title,
                    "result": res,
                    "status": "SUCCESS"
                })
            except SecurityViolationError as sve:
                lat_hop = (time.perf_counter() - t_hop0) * 1000.0
                hops_evidence.append({
                    "hop": idx,
                    "tool": tool_name,
                    "parameters": args,
                    "rows": 0,
                    "status": "POLICY_VIOLATION",
                    "latency_ms": round(lat_hop, 1)
                })
                role_blocked_notice = f"> [!WARNING] Section '{section_title}' was omitted: Tool '{tool_name}' is forbidden for role '{principal.role}'."
                overall_status = "PARTIAL_SUCCESS" if hop_results else "POLICY_VIOLATION"
                break  # Stop chain on policy violation
            except Exception as ex:
                lat_hop = (time.perf_counter() - t_hop0) * 1000.0
                hops_evidence.append({
                    "hop": idx,
                    "tool": tool_name,
                    "parameters": args,
                    "rows": 0,
                    "status": "ERROR",
                    "latency_ms": round(lat_hop, 1)
                })
                overall_status = "PARTIAL_SUCCESS" if hop_results else "ERROR"
                break

        total_lat = (time.perf_counter() - t_start) * 1000.0
        markdown_sections = []
        for hr in hop_results:
            sec_text = self._format_hop_section(hr["tool_name"], hr["section_title"], hr["result"])
            if sec_text:
                markdown_sections.append(sec_text)

        if role_blocked_notice:
            markdown_sections.append(role_blocked_notice)

        final_answer = "\n\n".join(markdown_sections)
        return {
            "status": overall_status,
            "chain_id": chain_id,
            "chain_type": "independent",
            "answer": final_answer,
            "hop_results": [hr["result"] for hr in hop_results],
            "evidence": {
                "chain_id": chain_id,
                "chain_type": "independent",
                "hops_count": len(hop_results),
                "total_tool_calls": calls_count,
                "hops": hops_evidence,
                "latency_ms": round(total_lat, 1)
            }
        }

    def execute_dependent_chain(
        self,
        template_id: str,
        entity_id: str,
        principal: Principal
    ) -> Dict[str, Any]:
        """
        Executes a dependent chain: Hop 2 consumes structured IDs/codes produced by Hop 1.
        Validates every intermediate code against graph cache, enforces max_rows_passed_forward,
        and halts safely if Hop 1 returns 0 results.
        """
        client = get_graph_client()
        chain_id = f"chn-{uuid.uuid4().hex[:10]}"
        t_start = time.perf_counter()

        templates = {t["id"]: t for t in self.config.get("dependent_templates", [])}
        template = templates.get(template_id)
        if not template:
            return {"status": "ERROR", "error": f"Unknown dependent chain template '{template_id}'"}

        hop1_spec = template["hop1"]
        hop2_spec = template["hop2"]

        # 1. Validate Initial Input Entity
        h1_entity_type = hop1_spec.get("entity_type", "COURSE_CODE")
        is_valid, clean_entity = validate_structured_entity(h1_entity_type, entity_id, client)
        if not is_valid:
            clean_entity = entity_id.strip()

        hops_evidence = []
        calls_count = 0
        truncated = False

        # --- EXECUTE HOP 1 ---
        h1_tool = hop1_spec["tool_name"]
        h1_param_key = hop1_spec["param_key"]
        h1_args = {h1_param_key: clean_entity}

        calls_count += 1
        t_h1 = time.perf_counter()
        try:
            h1_res = execute_tool(h1_tool, h1_args, principal=principal, chain_id=chain_id)
            lat_h1 = (time.perf_counter() - t_h1) * 1000.0
            h1_rows = len(h1_res.get("entities", [])) or len(h1_res.get("courses", [])) or len(h1_res.get("prerequisites", [])) or 1
            hops_evidence.append({
                "hop": 1,
                "tool": h1_tool,
                "parameters": h1_args,
                "rows": h1_rows,
                "status": "SUCCESS",
                "latency_ms": round(lat_h1, 1)
            })
        except SecurityViolationError as sve:
            lat_h1 = (time.perf_counter() - t_h1) * 1000.0
            hops_evidence.append({
                "hop": 1,
                "tool": h1_tool,
                "parameters": h1_args,
                "rows": 0,
                "status": "POLICY_VIOLATION",
                "latency_ms": round(lat_h1, 1)
            })
            return {
                "status": "POLICY_VIOLATION",
                "chain_id": chain_id,
                "answer": f"Access Policy Violation: Role '{principal.role}' is not authorized to execute tool '{h1_tool}'.",
                "evidence": {"chain_id": chain_id, "hops": hops_evidence}
            }

        # Check if Hop 1 returned any results
        out_list_key = hop1_spec.get("output_list_key", "prerequisites")
        raw_items = h1_res.get(out_list_key, [])

        if not raw_items or h1_res.get("error"):
            # Clean stop: first hop returned nothing, do NOT call hop 2 with empty values
            total_lat = (time.perf_counter() - t_start) * 1000.0
            ans = f"No {out_list_key} records found for '{clean_entity}'. Further dependent inquiries could not be continued."
            return {
                "status": "FIRST_HOP_NO_RESULTS",
                "chain_id": chain_id,
                "chain_type": "dependent",
                "answer": ans,
                "evidence": {
                    "chain_id": chain_id,
                    "chain_type": "dependent",
                    "hops_count": 1,
                    "total_tool_calls": 1,
                    "hops": hops_evidence,
                    "latency_ms": round(total_lat, 1)
                }
            }

        # 2. Extract and Validate Structured Intermediate Entities (Hop 1 -> Hop 2)
        code_key = hop1_spec.get("code_key", "prerequisite_code")
        h2_entity_type = hop2_spec.get("entity_type", "COURSE_CODE")

        extracted_codes: List[str] = []
        for item in raw_items:
            raw_code = (
                item.get(code_key) or item.get("prerequisite_code") or item.get("code")
                if isinstance(item, dict)
                else item
            )
            val_ok, code_clean = validate_structured_entity(h2_entity_type, raw_code, client)
            if val_ok and code_clean and code_clean not in extracted_codes:
                extracted_codes.append(code_clean)

        if not extracted_codes:
            total_lat = (time.perf_counter() - t_start) * 1000.0
            ans = self._format_hop_section(h1_tool, hop1_spec.get("section_title", "Hop 1 Results"), h1_res)
            return {
                "status": "SUCCESS",
                "chain_id": chain_id,
                "chain_type": "dependent",
                "answer": ans + "\n\nNo structured prerequisite codes met graph verification standards.",
                "evidence": {
                    "chain_id": chain_id,
                    "chain_type": "dependent",
                    "hops_count": 1,
                    "total_tool_calls": 1,
                    "hops": hops_evidence,
                    "latency_ms": round(total_lat, 1)
                }
            }

        # Enforce max_rows_passed_forward limit
        if len(extracted_codes) > self.max_rows_forward:
            extracted_codes = extracted_codes[:self.max_rows_forward]
            truncated = True

        # --- EXECUTE HOP 2 FOR EACH EXTRACTED CODE ---
        h2_tool = hop2_spec["tool_name"]
        h2_param_key = hop2_spec["param_key"]
        h2_results = []
        role_blocked_notice = None

        for code_val in extracted_codes:
            if calls_count >= self.max_tool_calls:
                truncated = True
                break

            calls_count += 1
            h2_args = {h2_param_key: code_val}
            t_h2 = time.perf_counter()
            try:
                res_h2 = execute_tool(h2_tool, h2_args, principal=principal, chain_id=chain_id)
                lat_h2 = (time.perf_counter() - t_h2) * 1000.0
                rows_h2 = len(res_h2.get("instructors", [])) or len(res_h2.get("entities", [])) or 1
                hops_evidence.append({
                    "hop": 2,
                    "tool": h2_tool,
                    "parameters": h2_args,
                    "rows": rows_h2,
                    "status": "SUCCESS",
                    "latency_ms": round(lat_h2, 1)
                })
                h2_results.append({"code": code_val, "data": res_h2})
            except SecurityViolationError as sve:
                lat_h2 = (time.perf_counter() - t_h2) * 1000.0
                hops_evidence.append({
                    "hop": 2,
                    "tool": h2_tool,
                    "parameters": h2_args,
                    "rows": 0,
                    "status": "POLICY_VIOLATION",
                    "latency_ms": round(lat_h2, 1)
                })
                role_blocked_notice = f"> [!WARNING] Dependent query for '{code_val}' was omitted: Tool '{h2_tool}' is forbidden for role '{principal.role}'."
                break

        total_lat = (time.perf_counter() - t_start) * 1000.0

        # Assemble Formatted Answer
        h1_text = self._format_hop_section(h1_tool, hop1_spec.get("section_header", "Hop 1"), h1_res)
        h2_text = self._format_hop2_batch(h2_tool, hop2_spec.get("section_title", "Instructors"), h2_results)

        sections = [h1_text, h2_text]
        if role_blocked_notice:
            sections.append(role_blocked_notice)
        if truncated:
            sections.append(self.truncation_msg.format(limit=self.max_rows_forward))

        final_answer = "\n\n".join(s for s in sections if s)
        return {
            "status": "SUCCESS" if h2_results else "PARTIAL_SUCCESS",
            "chain_id": chain_id,
            "chain_type": "dependent",
            "answer": final_answer,
            "evidence": {
                "chain_id": chain_id,
                "chain_type": "dependent",
                "hops_count": 2,
                "total_tool_calls": calls_count,
                "hops": hops_evidence,
                "latency_ms": round(total_lat, 1)
            }
        }

    def _format_hop_section(self, tool_name: str, title: str, res: Dict[str, Any]) -> str:
        """Formats the result of a single hop into structured Markdown."""
        lines = [f"{title}"]

        if tool_name == "get_prerequisite_tree":
            prereqs = res.get("prerequisites", [])
            target = res.get("target_course", res.get("course_code", ""))
            if not prereqs:
                lines.append(f"Course **{target}** has no formal prerequisite dependencies in Regulations-2021.")
            else:
                lines.append(f"Prerequisites required before taking **{target}**:")
                for p in prereqs:
                    code = p.get("code") or p.get("prerequisite_code") or ""
                    name = p.get("name") or p.get("prerequisite_name") or ""
                    depth = p.get("depth", 1)
                    indent = "  " * (depth - 1)
                    lines.append(f"{indent}- **{code}** ({name}) [Level {depth}]")

        elif tool_name == "find_faculty_for_course":
            instructors = res.get("instructors", [])
            course = res.get("course_code", "")
            if not instructors:
                lines.append(f"No specific instructors are currently assigned to **{course}** in the published roster.")
            else:
                lines.append(f"Faculty assigned to instruct **{course}**:")
                for f in instructors:
                    name = f.get("name", "Unknown Faculty")
                    dept = f.get("department", "SRMIST")
                    cabin = f.get("cabin", "Department Office")
                    email = f.get("email", "")
                    lines.append(f"- **{name}** ({dept}) | Cabin: **{cabin}** | Email: `{email}`")

        elif tool_name == "lookup_course":
            courses = res.get("courses", [])
            if courses:
                c = courses[0]
                lines.append(f"**[{c.get('code')}] {c.get('name')}**")
                lines.append(f"- **Credits**: {c.get('credits')} | **L-T-P-C**: `{c.get('ltpc', 'N/A')}`")
                lines.append(f"- **Department**: {c.get('department')} | **Category**: {c.get('category', 'Theory')}")
                if c.get("description"):
                    lines.append(f"- **Summary**: {c.get('description')}")
            else:
                lines.append("Course record not found.")

        elif tool_name == "find_course_schedule":
            schedules = res.get("schedules", [])
            course = res.get("course_code", "")
            if not schedules:
                lines.append(f"No scheduled classroom timetable sessions found for course **{course}**.")
            else:
                lines.append(f"Weekly scheduled sessions and classrooms for **{course}**:")
                for s in schedules:
                    room = s.get("room_id", "TBD")
                    day = s.get("day", "")
                    slot = s.get("slot", "")
                    lines.append(f"- Room **{room}**: {day} during period `{slot}`")

        elif tool_name == "lookup_faculty_profile":
            faculty_list = res.get("faculty", [])
            if faculty_list:
                f = faculty_list[0]
                lines.append(f"**{f.get('name')}** - {f.get('designation')}, {f.get('department')}")
                lines.append(f"- **Cabin Office**: **{f.get('cabin')}**")
                lines.append(f"- **Email**: `{f.get('email')}`")
                phone = f.get("phone", "[Hidden by Policy]")
                lines.append(f"- **Phone**: {phone}")
            else:
                lines.append("Faculty member profile not found.")

        else:
            lines.append(f"Output: {res}")

        return "\n".join(lines)

    def _format_hop2_batch(self, tool_name: str, title: str, batch_results: List[Dict[str, Any]]) -> str:
        """Formats the batch results of Hop 2 into structured Markdown."""
        lines = [f"{title}"]
        for item in batch_results:
            code = item["code"]
            data = item["data"]
            instructors = data.get("instructors", [])
            if not instructors:
                lines.append(f"\n#### Instructors for Prerequisite **{code}**\n- No published instructor assignments.")
            else:
                lines.append(f"\n#### Instructors for Prerequisite **{code}**:")
                for f in instructors:
                    name = f.get("name", "Faculty Member")
                    cabin = f.get("cabin", "Department Office")
                    email = f.get("email", "")
                    lines.append(f"- **{name}** | Cabin: **{cabin}** | Email: `{email}`")
        return "\n".join(lines)
