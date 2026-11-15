"""
Interactive CLI for SRMIST Campus Knowledge Assistant
Governed Agent (Qwen 2.5 + Neo4j + ChromaDB)
"""

import sys
import os
import json
import time

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent
from campus_knowledge_server.security.ast_validator import ASTSecurityValidator
from campus_knowledge_server.security.audit import AUDIT_LOG_FILE
from campus_knowledge_server.database.neo4j_client import get_graph_client

BANNER = """
======================================================================
       🏛️  SRMIST CAMPUS KNOWLEDGE ASSISTANT (TERMINAL CLI)
       Powered by Local Qwen 2.5 (Ollama) + Neo4j + ChromaDB
======================================================================
"""

HELP_TEXT = """
Commands:
  • Ask any question naturally (admissions, faculty, rooms, prerequisites)
  • 'mode'        : Toggle between Instant Governed Mode (~20ms) and Qwen Generative Mode
  • 'role'        : Switch active governance role ('student', 'faculty', 'admin')
  • 'verify'      : Cryptographically verify SHA-256 hash chain of the audit log
  • 'tools'       : List all 9 authorized governed tools
  • 'status'      : Check live connection status (Neo4j, Ollama, Vector DB)
  • 'audit'       : Display the last 10 security audit telemetry events
  • 'test'        : Run automated benchmark evaluation suite
  • 'exit'/'quit' : Exit terminal session
"""

def print_status(agent: GovernedCampusAgent):
    client = get_graph_client()
    neo_status = "Connected (bolt://127.0.0.1:7687)" if client.is_connected else "In-Memory Fallback"
    ollama_status = f"Active ({agent.model_name})" if agent.ollama_active else "Offline (Using Deterministic Synthesizer)"
    
    print("\n--- System Connection Status ---")
    print(f" • Neo4j Database : {neo_status}")
    print(f" • Ollama Agent   : {ollama_status}")
    print(f" • AST Guardrail  : Active (Zero-Trust Enforcement)")
    print(f" • Course Catalog : 430 Degree Programs Indexed")
    print(f" • Faculty Master : 513 Verified Professors Indexed")
    print(f" • Infrastructure : 10 Buildings, 264 Rooms Indexed\n")

def list_tools():
    print("\n--- Authorized Governed Tools (9) ---")
    tools = [
        ("check_admission_eligibility", "Evaluate cutoffs, stream requirements, and exams (SRMJEEE, NEET, etc.)"),
        ("lookup_faculty_profile", "Find professor designations, cabins, departments, and research"),
        ("find_faculty_for_course", "Find faculty assigned to instruct a specific course"),
        ("verify_prerequisites", "Verify whether a student qualifies to take an advanced course"),
        ("get_prerequisite_tree", "Traverse curriculum dependency chain"),
        ("lookup_course", "Get course description, credits, and offering department"),
        ("find_available_rooms", "Locate vacant rooms in Tech Park, UB, or Bio-Engg buildings"),
        ("find_room_schedule", "View timetable and class bookings for a specific room"),
        ("search_courses_semantic", "Semantic curriculum discovery using ChromaDB vector store")
    ]
    for name, desc in tools:
        print(f"  • {name:<28} : {desc}")
    print()

def show_audit_logs():
    print("\n--- Recent Security Audit Telemetry Logs ---")
    if not os.path.exists(AUDIT_LOG_FILE):
        print("No audit logs found yet.\n")
        return
    with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines[-10:]:
        try:
            ev = json.loads(line.strip())
            ts = ev.get("timestamp", "").split("T")[-1][:8]
            tool = ev.get("tool", "unknown")
            status = ev.get("status", "UNKNOWN")
            caller = ev.get("caller", "local")
            lat = ev.get("latency_ms", 0)
            print(f" [{ts}] {status:<8} | Tool: {tool:<26} | Caller: {caller:<10} | Latency: {lat}ms")
        except:
            pass
    print()

def process_query(agent: GovernedCampusAgent, query: str, use_qwen: bool = False, role: str = "student"):
    q = query.strip()
    if not q:
        return

    # Check if input is a raw Cypher query or adversarial injection attempt
    is_cypher_pattern = any(kw in q.upper() for kw in ["MATCH ", "CALL ", "DROP ", "DELETE", "CREATE ", "MERGE ", "ALTER ", "LOAD CSV", ";"])
    if is_cypher_pattern:
        is_safe, reason, _ = ASTSecurityValidator.validate_cypher(q)
        if not is_safe:
            print("\n🚨 [AST SECURITY GUARDRAIL INTERCEPTED]")
            print(f"   Violation Detected : {reason}")
            print("   Policy Enforcement : 403 Forbidden. Raw write/drop commands blocked.\n")
            return

    print(f"\n[Agent] Thinking & querying campus knowledge (Role: {role})...")
    t0 = time.time()
    res = agent.execute_query(q, use_llm_synthesis=use_qwen, role=role)
    latency = round((time.time() - t0) * 1000)

    tool_used = res.get("tool_selected", "unknown")
    synthesizer = res.get("synthesizer", "Deterministic Governed Synthesizer")
    answer = res.get("answer", "No response generated.")

    print(f"\n" + "=" * 65)
    print(f"🔧 Tool Invoked : {tool_used}")
    print(f"⚡ Synthesized By: {synthesizer} ({latency}ms)")
    print(f"🛡️ Active Role   : {role.upper()} (policy.yaml enforced)")
    print(f"📦 Source Data  : {res.get('source', 'Governed Campus Database')}")
    print("=" * 65)
    print(f"\n{answer}\n")

def main():
    agent = GovernedCampusAgent()
    use_qwen = False
    current_role = "student"

    # CLI argument mode
    args = sys.argv[1:]
    if "--qwen" in args:
        use_qwen = True
        args.remove("--qwen")

    if args:
        query_arg = " ".join(args)
        process_query(agent, query_arg, use_qwen=use_qwen, role=current_role)
        return

    # Interactive Shell Mode
    print(BANNER)
    print_status(agent)
    print(HELP_TEXT)

    while True:
        try:
            mode_badge = "⚡ Fast Mode (~20ms)" if not use_qwen else "🤖 Qwen 2.5 Generative"
            user_input = input(f"campus [{current_role} | {mode_badge}]> ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit", "q"]:
                print("Goodbye!")
                break
            elif user_input.lower() == "help":
                print(HELP_TEXT)
            elif user_input.lower() in ["mode", "fast", "qwen", "toggle"]:
                use_qwen = not use_qwen
                new_mode = "🤖 Qwen 2.5 Generative (via Ollama)" if use_qwen else "⚡ Fast Governed Mode (~20ms)"
                print(f"\n>>> Switched Synthesizer Mode to: {new_mode}\n")
            elif user_input.lower().startswith("role"):
                parts = user_input.split()
                if len(parts) > 1 and parts[1].lower() in ["student", "faculty", "admin"]:
                    current_role = parts[1].lower()
                else:
                    roles = ["student", "faculty", "admin"]
                    next_idx = (roles.index(current_role) + 1) % len(roles)
                    current_role = roles[next_idx]
                print(f"\n>>> Switched Active Governance Role to: {current_role.upper()} (policy.yaml enforced)\n")
            elif user_input.lower() in ["verify", "chain"]:
                from campus_knowledge_server.security.audit import get_audit_logger
                logger = get_audit_logger()
                is_intact, count, msg = logger.verify_chain()
                print(f"\n--- Cryptographic Audit Verification ---")
                print(f" • Status      : {'VALID (Chain Intact)' if is_intact else 'CORRUPTED'}")
                print(f" • Blocks      : {count} SHA-256 chained log entries verified")
                print(f" • Detail      : {msg}\n")
            elif user_input.lower() == "status":
                print_status(agent)
            elif user_input.lower() == "tools":
                list_tools()
            elif user_input.lower() == "audit":
                show_audit_logs()
            elif user_input.lower() == "test":
                print("\nRunning automated benchmark evaluation suite...")
                from campus_knowledge_server.eval.run_eval import evaluate_campus_system
                evaluate_campus_system()
                print()
            else:
                process_query(agent, user_input, use_qwen=use_qwen, role=current_role)
        except (KeyboardInterrupt, EOFError):
            print("\nSession ended.")
            break

if __name__ == "__main__":
    main()
