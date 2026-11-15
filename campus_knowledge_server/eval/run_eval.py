"""
Automated Evaluation Suite
Measures:
1. Tool-selection accuracy
2. Cypher execution accuracy
3. Invalid-query rate
4. Grounded-answer score
5. Access-policy violations intercepted
"""

import os
import sys
import json
import time
from typing import Dict, List, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COURSES_ROOT = os.path.dirname(BASE_DIR)
if COURSES_ROOT not in sys.path:
    sys.path.insert(0, COURSES_ROOT)

from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent
from campus_knowledge_server.security.ast_validator import ASTSecurityValidator
DATASET_PATH = os.path.join(BASE_DIR, "eval", "benchmark_dataset.json")
REPORT_PATH = os.path.join(BASE_DIR, "eval", "eval_report.json")

def evaluate_campus_system():
    if not os.path.exists(DATASET_PATH):
        print(f"Error: Dataset not found at {DATASET_PATH}")
        return

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        benchmark_queries = json.load(f)

    agent = GovernedCampusAgent()

    total_queries = len(benchmark_queries)
    legitimate_queries = [q for q in benchmark_queries if not q.get("should_block")]
    adversarial_queries = [q for q in benchmark_queries if q.get("should_block")]

    tool_correct_count = 0
    execution_success_count = 0
    invalid_query_count = 0
    grounded_count = 0
    attack_blocked_count = 0

    results_log = []

    print(f"\n=======================================================")
    print(f"Starting Evaluation on {total_queries} Campus Queries...")
    print(f"=======================================================\n")

    # 1. Evaluate Legitimate Queries
    for item in legitimate_queries:
        q_id = item["id"]
        q_text = item["query"]
        expected_tool = item["expected_tool"]

        t0 = time.time()
        res = agent.execute_query(q_text)
        latency = (time.time() - t0) * 1000

        tool_selected = res.get("tool_selected")
        is_tool_correct = (tool_selected == expected_tool)
        if is_tool_correct:
            tool_correct_count += 1

        is_exec_success = (res.get("status") not in ["EXECUTION_ERROR", "NO_TOOL_MATCH"])
        if is_exec_success:
            execution_success_count += 1
        else:
            invalid_query_count += 1

        # Check Grounding / Citation
        answer = res.get("answer", "")
        has_citation = any(marker in answer for marker in ["[Course:", "[Faculty:", "[Room:", "[Program:", "Eligible", "Ineligible"])
        if has_citation:
            grounded_count += 1

        print(f"[{q_id}] {q_text[:40]}... -> Tool: {tool_selected} (Expected: {expected_tool}) | Correct: {is_tool_correct} | Grounded: {has_citation}")

        results_log.append({
            "id": q_id,
            "query": q_text,
            "expected_tool": expected_tool,
            "tool_selected": tool_selected,
            "tool_correct": is_tool_correct,
            "execution_success": is_exec_success,
            "grounded": has_citation,
            "latency_ms": round(latency, 2),
            "answer_preview": answer[:120]
        })

    # 2. Evaluate Adversarial Attacks
    for item in adversarial_queries:
        q_id = item["id"]
        q_text = item["query"]
        is_safe, reason, _ = ASTSecurityValidator.validate_cypher(q_text)
        is_blocked = (not is_safe)
        if is_blocked:
            attack_blocked_count += 1

        print(f"[{q_id}] [ATTACK TEST] {q_text[:35]}... -> Intercepted: {is_blocked} ({reason})")

        results_log.append({
            "id": q_id,
            "query": q_text,
            "type": "adversarial_attack",
            "blocked": is_blocked,
            "reason": reason
        })

    # Metrics Computation
    tool_acc = (tool_correct_count / len(legitimate_queries)) * 100 if legitimate_queries else 0.0
    cypher_exec_acc = (execution_success_count / len(legitimate_queries)) * 100 if legitimate_queries else 0.0
    invalid_rate = (invalid_query_count / len(legitimate_queries)) * 100 if legitimate_queries else 0.0
    grounded_score = (grounded_count / len(legitimate_queries)) * 100 if legitimate_queries else 0.0
    policy_intercept_rate = (attack_blocked_count / len(adversarial_queries)) * 100 if adversarial_queries else 0.0

    summary = {
        "total_evaluated": total_queries,
        "legitimate_queries_count": len(legitimate_queries),
        "adversarial_attacks_count": len(adversarial_queries),
        "metrics": {
            "tool_selection_accuracy_pct": round(tool_acc, 2),
            "cypher_execution_accuracy_pct": round(cypher_exec_acc, 2),
            "invalid_query_rate_pct": round(invalid_rate, 2),
            "grounded_answer_score_pct": round(grounded_score, 2),
            "access_policy_violations_blocked_pct": round(policy_intercept_rate, 2)
        },
        "target_benchmarks": {
            "tool_selection_accuracy_target": ">= 92%",
            "cypher_execution_accuracy_target": "100%",
            "invalid_query_rate_target": "< 2%",
            "grounded_answer_score_target": ">= 90%",
            "access_policy_violations_blocked_target": "100%"
        },
        "detailed_results": results_log
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "="*55)
    print("           FINAL EVALUATION SCORECARD")
    print("="*55)
    print(f" Tool-Selection Accuracy:               {tool_acc:.1f}% (Target: >=92%)")
    print(f" Cypher Execution Accuracy:             {cypher_exec_acc:.1f}% (Target: 100%)")
    print(f" Invalid-Query Rate:                    {invalid_rate:.1f}% (Target: <2%)")
    print(f" Grounded-Answer Score:                 {grounded_score:.1f}% (Target: >=90%)")
    print(f" Access-Policy Violations Blocked:      {policy_intercept_rate:.1f}% (Target: 100%)")
    print("="*55)
    print(f"Full report exported to: {REPORT_PATH}\n")

if __name__ == "__main__":
    evaluate_campus_system()
