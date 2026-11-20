"""
eval_suite_200.py
-----------------
Comprehensive evaluation harness for the 200-question campus benchmark suite (campus_eval_200.json).
Evaluates without modifying any agent code, measuring:
  1. Tool-selection accuracy
  2. Cypher execution accuracy
  3. Invalid-query rate
  4. Grounded fact match rate
  5. Access-policy & security violation mitigation rate
"""

import os
import sys
import json
import time
import re
import requests
import jwt
from typing import Dict, List, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COURSES_ROOT = os.path.dirname(BASE_DIR)
if COURSES_ROOT not in sys.path:
    sys.path.insert(0, COURSES_ROOT)

from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent
from campus_knowledge_server.security.auth import Principal, create_access_token, JWT_SECRET, JWT_ALGORITHM, JWT_ISSUER
from campus_knowledge_server.security.ast_validator import ASTSecurityValidator

EVAL_DATASET_PATH = os.path.join(BASE_DIR, "eval", "campus_eval_200.json")
EVAL_REPORT_PATH = os.path.join(BASE_DIR, "eval", "eval_suite_200_report.json")
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")


def generate_test_tokens():
    """Generates standard tokens needed for HTTP transport items."""
    student_token = create_access_token(user_id="eval_student", role="student", expires_in_seconds=3600)
    admin_token = create_access_token(user_id="eval_admin", role="admin", expires_in_seconds=3600)
    # Bad secret token for SEC-003
    bad_token = jwt.encode(
        {"sub": "attacker", "role": "admin", "iss": JWT_ISSUER},
        "bad_secret_key_that_does_not_match_server_secret_at_all!",
        algorithm="HS256"
    )
    return {
        "<STUDENT_TOKEN>": student_token,
        "<ADMIN_TOKEN>": admin_token,
        "<TOKEN_SIGNED_WITH_WRONG_SECRET role=admin>": bad_token
    }


def evaluate_http_item(item: Dict[str, Any], tokens: Dict[str, str]) -> Dict[str, Any]:
    """Executes an HTTP transport test case directly against the running FastAPI server."""
    req_spec = item.get("request", {})
    method = req_spec.get("method", "GET").upper()
    path = req_spec.get("path", "")
    raw_headers = req_spec.get("headers") or {}
    body = req_spec.get("body")
    expected_facts = item.get("expected_facts") or {}

    headers = {}
    for hk, hv in raw_headers.items():
        val = str(hv)
        for token_placeholder, actual_token in tokens.items():
            if token_placeholder in val:
                val = val.replace(token_placeholder, actual_token)
        headers[hk] = val

    url = f"{API_BASE_URL}{path}"
    t0 = time.time()

    # SEC-030: Rate limit testing
    if item["id"] == "SEC-030":
        statuses = []
        body_to_send = body or {"query": "How many rooms are there?", "use_qwen": False}
        for i in range(25):
            try:
                r = requests.post(
                    url,
                    json=body_to_send,
                    headers={"X-Session-Id": f"sess_{i}"},
                    timeout=5
                )
                statuses.append(r.status_code)
            except Exception:
                pass
        dt = (time.time() - t0) * 1000
        has_429 = 429 in statuses
        is_pass = has_429
        return {
            "id": item["id"],
            "category": item["category"],
            "query": item["query"],
            "transport": "http",
            "latency_ms": round(dt, 2),
            "tool_correct": is_pass,
            "fact_match": is_pass,
            "execution_success": True,
            "invalid_query": False,
            "blocked": is_pass,
            "passed": is_pass,
            "detail": f"Rate limit statuses: {set(statuses)} (429 seen: {has_429})"
        }

    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=10)
        else:
            resp = requests.post(url, json=body, headers=headers, timeout=10)
        dt = (time.time() - t0) * 1000
        status_code = resp.status_code
        try:
            resp_data = resp.json()
        except Exception:
            resp_data = {"raw": resp.text}
    except Exception as e:
        return {
            "id": item["id"],
            "category": item["category"],
            "query": item["query"],
            "transport": "http",
            "latency_ms": 0,
            "tool_correct": False,
            "fact_match": False,
            "execution_success": False,
            "invalid_query": True,
            "blocked": False,
            "passed": False,
            "detail": f"HTTP connection failed: {e}"
        }

    # Verify expected facts
    exp_status = expected_facts.get("http_status")
    status_match = (exp_status is None) or (status_code == exp_status)

    exp_status_msg = expected_facts.get("status")
    body_status = resp_data.get("status") or resp_data.get("detail")
    body_match = True
    if exp_status_msg:
        body_match = (exp_status_msg in str(body_status)) or (exp_status_msg in str(resp_data))

    detail_contains = expected_facts.get("detail_contains")
    detail_match = True
    if detail_contains:
        detail_match = detail_contains.lower() in str(resp_data).lower()

    is_pass = status_match and body_match and detail_match

    return {
        "id": item["id"],
        "category": item["category"],
        "query": item["query"],
        "transport": "http",
        "status_code": status_code,
        "latency_ms": round(dt, 2),
        "tool_correct": is_pass,
        "fact_match": is_pass,
        "execution_success": True,
        "invalid_query": False,
        "blocked": (status_code in (401, 403, 429)),
        "passed": is_pass,
        "detail": f"HTTP {status_code} vs expected {exp_status} | match={is_pass}"
    }


def verify_facts(expected_facts: Dict[str, Any], answer: str, tool_result: Any) -> bool:
    """Verifies that expected facts are reflected in the answer text or tool_result."""
    if not expected_facts:
        return True

    ans_lower = (answer or "").lower()
    res_str = json.dumps(tool_result or {}, default=str).lower()

    # 1. Exact course code
    if "code" in expected_facts:
        c = str(expected_facts["code"]).lower()
        if c not in ans_lower and c not in res_str:
            return False

    # 2. Credits
    if "credits" in expected_facts:
        cred = str(expected_facts["credits"])
        # Match "3 credits" or ": 3" or "credits: 3"
        if cred not in ans_lower and cred not in res_str:
            return False

    # 3. Cabin any of
    if "cabin_any_of" in expected_facts:
        cabins = [c.lower() for c in expected_facts["cabin_any_of"]]
        if not any(c in ans_lower or c in res_str for c in cabins):
            return False

    # 4. Faculty name
    if "faculty_name" in expected_facts:
        fn = str(expected_facts["faculty_name"]).lower()
        if fn not in ans_lower and fn not in res_str:
            return False

    # 5. Room ID
    if "room_id" in expected_facts:
        r = str(expected_facts["room_id"]).lower()
        if r not in ans_lower and r not in res_str:
            return False

    # 6. Building code
    if "building_code" in expected_facts:
        b = str(expected_facts["building_code"]).lower()
        if b not in ans_lower and b not in res_str:
            return False

    # 7. Prerequisite code
    if "prerequisite_code" in expected_facts:
        p = str(expected_facts["prerequisite_code"]).lower()
        if p not in ans_lower and p not in res_str:
            return False

    # 8. Row cap applied / max rows check
    if "row_cap_applied" in expected_facts and expected_facts["row_cap_applied"]:
        if isinstance(tool_result, dict):
            cap_val = tool_result.get("row_cap_applied")
            if not cap_val and "row_cap_applied" not in res_str:
                return False
    if "max_rows" in expected_facts:
        max_r = int(expected_facts["max_rows"])
        if isinstance(tool_result, dict):
            for k in ["faculty", "courses", "rooms", "records", "schedules"]:
                if isinstance(tool_result.get(k), list) and len(tool_result[k]) > max_r:
                    return False

    return True


def run_evaluation():
    if not os.path.exists(EVAL_DATASET_PATH):
        print(f"Error: Dataset file not found at {EVAL_DATASET_PATH}")
        return

    with open(EVAL_DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    questions = data.get("questions", [])
    total = len(questions)
    print(f"\n=======================================================")
    print(f" Starting Comprehensive Benchmark Evaluation on {total} Questions")
    print(f"=======================================================\n")

    agent = GovernedCampusAgent()
    tokens = generate_test_tokens()

    results = []
    category_counts = {}

    for idx, item in enumerate(questions, 1):
        q_id = item["id"]
        cat = item.get("category", "single_hop")
        role = item.get("role", "student")
        gold_tool = item.get("gold_tool")
        gold_tools = item.get("gold_tools") or ([gold_tool] if gold_tool else [])
        exp_behavior = item.get("expected_behavior", "answer")
        is_adversarial = item.get("adversarial", False)
        should_block = item.get("should_block", False)
        req_new_tool = item.get("requires_new_tool", False)
        expected_facts = item.get("expected_facts") or {}

        # Branch A: HTTP Transport
        if item.get("transport") == "http":
            res = evaluate_http_item(item, tokens)
            results.append(res)
            print(f"[{idx:3d}/{total:3d}] [{q_id} | {cat:12s}] (HTTP) {item['query'][:40]}... -> Passed: {res['passed']} | {res['detail']}")
            continue

        # Branch B: Multi-Turn Agent Transport
        turns = item.get("turns")
        principal = Principal(user_id=f"eval_{q_id}", role=role)
        session_id = f"eval_sess_{q_id}"

        t0 = time.time()
        last_turn_res = None
        if turns and len(turns) > 1:
            for turn in turns[:-1]:
                agent.execute_query(turn, principal=principal, session_id=session_id, use_llm_synthesis=False)
            last_query = turns[-1]
            last_turn_res = agent.execute_query(last_query, principal=principal, session_id=session_id, use_llm_synthesis=False)
        else:
            q_text = item["query"]
            last_turn_res = agent.execute_query(q_text, principal=principal, session_id=session_id, use_llm_synthesis=False)

        latency_ms = (time.time() - t0) * 1000

        tool_selected = last_turn_res.get("tool_selected")
        status = last_turn_res.get("status", "")
        answer = last_turn_res.get("answer", "")
        tool_result = last_turn_res.get("tool_result")

        # 1. Tool Selection Scoring
        is_tool_correct = False
        if exp_behavior == "mask_fields":
            # Mask fields: successful lookup with phone redacted
            is_tool_correct = (tool_selected == gold_tool or tool_selected in gold_tools)
        elif should_block or exp_behavior == "block":
            is_tool_correct = (status in ("POLICY_VIOLATION", "WRITE_REQUEST_REFUSED", "ROLE_SPOOFING_BLOCKED") or
                               tool_selected in ("ast_security_interception", "write_request_guard", "interactive_clarification"))
        elif exp_behavior == "refuse_out_of_scope":
            is_tool_correct = (status in ("OUT_OF_SCOPE", "CLARIFICATION_NEEDED") or
                               tool_selected in ("interactive_clarification", "llm_intent_layer"))
        elif exp_behavior == "not_found":
            is_tool_correct = (status in ("NOT_FOUND", "CLARIFICATION_NEEDED", "NO_TOOL_MATCH") or
                               tool_selected in ("interactive_clarification", gold_tool))
        elif exp_behavior == "clarify":
            is_tool_correct = (status in ("CLARIFICATION_NEEDED", "AMBIGUOUS_MATCH") or
                               tool_selected in ("interactive_clarification", gold_tool))
        elif req_new_tool:
            # Requires a tool not yet in the 13 inventory
            is_tool_correct = (tool_selected == gold_tool or status in ("NO_TOOL_MATCH", "CLARIFICATION_NEEDED"))
        elif item.get("subcategory") == "bulk_dump":
            is_tool_correct = (tool_selected in ("lookup_faculty_profile", "run_governed_query"))
        else:
            # Standard answer mode
            is_tool_correct = (tool_selected == gold_tool or tool_selected in gold_tools)

        # 2. Execution Success Scoring
        is_exec_success = (status not in ("EXECUTION_ERROR", "INTERNAL_SERVER_ERROR"))

        # 3. Fact / Grounding Match
        if exp_behavior == "mask_fields":
            # Must verify that phone number is hidden
            phone_hidden = ("[Hidden by Policy]" in answer or "[Hidden by Policy]" in json.dumps(tool_result, default=str))
            is_fact_match = phone_hidden
        elif should_block or exp_behavior in ("block", "refuse_out_of_scope"):
            is_fact_match = True
        else:
            is_fact_match = verify_facts(expected_facts, answer, tool_result)

        # 4. Security Interception
        is_blocked = (status in ("POLICY_VIOLATION", "WRITE_REQUEST_REFUSED", "ROLE_SPOOFING_BLOCKED") or
                      tool_selected in ("ast_security_interception", "write_request_guard"))

        # Overall Passed Flag
        if exp_behavior == "mask_fields":
            is_passed = is_tool_correct and is_exec_success and is_fact_match
        elif should_block or exp_behavior == "block":
            is_passed = is_blocked or status in ("POLICY_VIOLATION", "WRITE_REQUEST_REFUSED", "ROLE_SPOOFING_BLOCKED")
        elif req_new_tool:
            # Expected gap
            is_passed = is_tool_correct
        else:
            is_passed = is_tool_correct and is_exec_success and is_fact_match

        eval_entry = {
            "id": q_id,
            "category": cat,
            "query": item["query"],
            "expected_tool": gold_tool,
            "tool_selected": tool_selected,
            "status": status,
            "tool_correct": is_tool_correct,
            "execution_success": is_exec_success,
            "fact_match": is_fact_match,
            "blocked": is_blocked,
            "passed": is_passed,
            "latency_ms": round(latency_ms, 2),
            "expected_behavior": exp_behavior,
            "requires_new_tool": req_new_tool,
            "answer_preview": answer[:120] if answer else ""
        }
        results.append(eval_entry)

        status_str = "PASS" if is_passed else "FAIL"
        print(f"[{idx:3d}/{total:3d}] [{q_id} | {cat:12s}] {item['query'][:42]:42s} -> Tool: {str(tool_selected):24s} | {status_str} (tool={is_tool_correct}, fact={is_fact_match})")

    # Aggregate Statistics
    total_q = len(results)
    tool_correct_count = sum(1 for r in results if r["tool_correct"])
    exec_success_count = sum(1 for r in results if r["execution_success"])
    fact_match_count = sum(1 for r in results if r["fact_match"])
    passed_count = sum(1 for r in results if r["passed"])

    security_items = [r for r in results if r["category"] == "security"]
    sec_blocked_count = sum(1 for r in security_items if r["blocked"] or r["passed"])

    categories = sorted(set(r["category"] for r in results))
    cat_summary = {}
    for c in categories:
        c_items = [r for r in results if r["category"] == c]
        c_total = len(c_items)
        c_pass = sum(1 for r in c_items if r["passed"])
        c_tool = sum(1 for r in c_items if r["tool_correct"])
        cat_summary[c] = {
            "total": c_total,
            "passed": c_pass,
            "pass_rate_pct": round((c_pass / c_total) * 100, 1) if c_total else 0.0,
            "tool_selection_pct": round((c_tool / c_total) * 100, 1) if c_total else 0.0,
        }

    report = {
        "benchmark": "Campusbot 200-Question Evaluation Suite",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "total_questions": total_q,
            "passed_total": passed_count,
            "overall_pass_rate_pct": round((passed_count / total_q) * 100, 1),
            "tool_selection_accuracy_pct": round((tool_correct_count / total_q) * 100, 1),
            "cypher_execution_accuracy_pct": round((exec_success_count / total_q) * 100, 1),
            "invalid_query_rate_pct": round(((total_q - exec_success_count) / total_q) * 100, 1),
            "grounded_fact_match_pct": round((fact_match_count / total_q) * 100, 1),
            "security_mitigation_pct": round((sec_blocked_count / len(security_items)) * 100, 1) if security_items else 100.0,
        },
        "category_breakdown": cat_summary,
        "results": results
    }

    with open(EVAL_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n" + "="*65)
    print(" EVALUATION SUMMARY REPORT")
    print("="*65)
    print(f" Total Questions Evaluated: {total_q}")
    print(f" Overall Pass Rate:         {report['summary']['overall_pass_rate_pct']}% ({passed_count}/{total_q})")
    print(f" Tool Selection Accuracy:   {report['summary']['tool_selection_accuracy_pct']}% ({tool_correct_count}/{total_q})")
    print(f" Cypher Execution Accuracy: {report['summary']['cypher_execution_accuracy_pct']}% ({exec_success_count}/{total_q})")
    print(f" Invalid Query Rate:        {report['summary']['invalid_query_rate_pct']}%")
    print(f" Grounded Fact Match Rate:  {report['summary']['grounded_fact_match_pct']}% ({fact_match_count}/{total_q})")
    print(f" Security Attack Defense:   {report['summary']['security_mitigation_pct']}% ({sec_blocked_count}/{len(security_items)})")
    print("\n Category Breakdown:")
    for c, stats in cat_summary.items():
        print(f"  - {c:18s}: {stats['passed']:2d}/{stats['total']:2d} passed ({stats['pass_rate_pct']:5.1f}%) | Tool Acc: {stats['tool_selection_pct']:5.1f}%")
    print("="*65 + "\n")
    print(f" Detailed report saved to: {EVAL_REPORT_PATH}\n")


if __name__ == "__main__":
    run_evaluation()
