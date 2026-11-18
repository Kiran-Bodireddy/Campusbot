"""
Comprehensive Campus Knowledge Graph Benchmark Evaluator
Measures the 5 required problem statement metrics across the 90-question benchmark dataset:
1. Tool-selection accuracy (Hybrid Mode and Qwen-Only Semantic Mode)
2. Cypher execution accuracy (Target: 100%)
3. Invalid-query rate (Target: < 2%)
4. Grounded-answer score (Target: >= 90%)
5. Access-policy violations (Target: 0 allowed across adversarial queries)
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

def run_benchmark(run_qwen_semantic_mode: bool = True):
    if not os.path.exists(DATASET_PATH):
        print(f"Error: Dataset not found at {DATASET_PATH}")
        return

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        benchmark_queries = json.load(f)

    agent = GovernedCampusAgent()

    total_queries = len(benchmark_queries)
    legitimate_queries = [q for q in benchmark_queries if not q.get("should_block")]
    adversarial_queries = [q for q in benchmark_queries if q.get("should_block")]

    hybrid_tool_correct = 0
    qwen_tool_correct = 0
    qwen_queries_tested = 0
    execution_success_count = 0
    invalid_query_count = 0
    grounded_count = 0
    attacks_blocked_count = 0

    results_log = []

    print("\n" + "="*65)
    print(f" Running Evaluation on {total_queries} Benchmark Questions")
    print(f" - Legitimate Campus Queries: {len(legitimate_queries)} (65 Single-Hop + 15 Multi-Hop)")
    print(f" - Adversarial Attack Queries: {len(adversarial_queries)} (Target: 100% Interception)")
    print("="*65 + "\n")

    # 1. Evaluate Legitimate Queries (Single-Hop & Multi-Hop)
    for idx, item in enumerate(legitimate_queries, 1):
        q_id = item["id"]
        q_text = item["query"]
        expected_tool = item["gold_tool"]
        category = item.get("category", "single_hop")

        t0 = time.time()
        # Execute query through Governed Campus Agent
        res = agent.execute_query(q_text, use_llm_synthesis=True)
        latency_ms = (time.time() - t0) * 1000

        tool_selected = res.get("tool_selected")
        is_hybrid_correct = (tool_selected == expected_tool)
        if is_hybrid_correct:
            hybrid_tool_correct += 1

        # Check Cypher execution status
        status = res.get("status", "")
        is_exec_success = (status not in ["EXECUTION_ERROR", "NO_TOOL_MATCH", "POLICY_VIOLATION"])
        if is_exec_success:
            execution_success_count += 1
        else:
            invalid_query_count += 1

        # Check Grounding / Verified Citations
        answer = res.get("answer", "")
        has_citation = any(
            marker in answer for marker in [
                "[Course:", "[Faculty:", "[Room:", "[Program:", "Eligible", "Ineligible",
                "Total Courses:", "Total Registered Faculty:"
            ]
        ) or res.get("grounded", False)
        if has_citation:
            grounded_count += 1

        # Evaluate Qwen-only semantic router mode on a sample of 10 queries
        is_qwen_correct = None
        if run_qwen_semantic_mode and idx <= 10:
            qwen_queries_tested += 1
            try:
                llm_tool_res = agent._select_tool_with_llm(q_text)
                if llm_tool_res and llm_tool_res[0] == expected_tool:
                    qwen_tool_correct += 1
                    is_qwen_correct = True
                else:
                    is_qwen_correct = False
            except Exception:
                is_qwen_correct = False

        status_flag = "PASS" if (is_hybrid_correct and is_exec_success) else "FAIL"
        print(f"[{q_id} | {category:10s}] {q_text[:42]}... -> Tool: {tool_selected:25s} | Correct: {str(is_hybrid_correct):5s} | Exec: {status_flag}", flush=True)

        results_log.append({
            "id": q_id,
            "category": category,
            "query": q_text,
            "expected_tool": expected_tool,
            "tool_selected": tool_selected,
            "hybrid_tool_correct": is_hybrid_correct,
            "qwen_mode_correct": is_qwen_correct,
            "execution_success": is_exec_success,
            "grounded": has_citation,
            "latency_ms": round(latency_ms, 2),
            "answer_preview": answer[:150]
        })

    # 2. Evaluate Adversarial Attack Queries
    print("\n" + "-"*65)
    print(" Evaluating Adversarial Security Attacks (Zero-Trust Guardrail)")
    print("-"*65)

    for item in adversarial_queries:
        q_id = item["id"]
        q_text = item["query"]

        is_safe, reason, _ = ASTSecurityValidator.validate_cypher(q_text)
        is_adversarial_pattern, pat_reason = ASTSecurityValidator.is_adversarial_or_destructive(q_text)
        is_blocked = (not is_safe) or is_adversarial_pattern
        if is_blocked:
            attacks_blocked_count += 1

        block_reason = reason or pat_reason or "Blocked by zero-trust security policy"
        print(f"[{q_id} | ATTACK] {q_text[:38]}... -> Intercepted: {is_blocked} ({block_reason})")

        results_log.append({
            "id": q_id,
            "category": "adversarial",
            "query": q_text,
            "type": "adversarial_attack",
            "blocked": is_blocked,
            "reason": block_reason
        })

    # Metric Computations
    total_legit = len(legitimate_queries)
    total_adv = len(adversarial_queries)

    hybrid_tool_acc = (hybrid_tool_correct / total_legit) * 100 if total_legit else 0.0
    qwen_tool_acc = (qwen_tool_correct / qwen_queries_tested) * 100 if qwen_queries_tested else 0.0
    cypher_exec_acc = (execution_success_count / total_legit) * 100 if total_legit else 0.0
    invalid_query_rate = (invalid_query_count / total_legit) * 100 if total_legit else 0.0
    grounded_score = (grounded_count / total_legit) * 100 if total_legit else 0.0
    policy_intercept_rate = (attacks_blocked_count / total_adv) * 100 if total_adv else 0.0
    policy_violations_allowed = total_adv - attacks_blocked_count

    summary = {
        "benchmark_summary": {
            "total_queries_evaluated": total_queries,
            "legitimate_queries": total_legit,
            "single_hop_queries": sum(1 for q in legitimate_queries if q.get("category") == "single_hop"),
            "multi_hop_queries": sum(1 for q in legitimate_queries if q.get("category") == "multi_hop"),
            "adversarial_attack_queries": total_adv,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model_tested": agent.model_name,
            "engine": "Neo4j Community 2026.10.2 + Native Vector Index"
        },
        "metrics": {
            "tool_selection_accuracy_hybrid_pct": round(hybrid_tool_acc, 2),
            "tool_selection_accuracy_qwen_semantic_pct": round(qwen_tool_acc, 2),
            "cypher_execution_accuracy_pct": round(cypher_exec_acc, 2),
            "invalid_query_rate_pct": round(invalid_query_rate, 2),
            "grounded_answer_score_pct": round(grounded_score, 2),
            "access_policy_violations_count": policy_violations_allowed,
            "access_policy_interception_rate_pct": round(policy_intercept_rate, 2)
        },
        "target_benchmarks": {
            "tool_selection_accuracy_target": ">= 92.0%",
            "cypher_execution_accuracy_target": "100.0%",
            "invalid_query_rate_target": "< 2.0%",
            "grounded_answer_score_target": ">= 90.0%",
            "access_policy_violations_allowed_target": "0 allowed (100.0% blocked)"
        },
        "detailed_results": results_log
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "="*65)
    print("                    FINAL BENCHMARK SCORECARD")
    print("="*65)
    print(f" 1. Tool-Selection Accuracy (Hybrid Mode):       {hybrid_tool_acc:6.2f}%  (Target: >= 92.0%)")
    print(f"    Tool-Selection Accuracy (Qwen Semantic):    {qwen_tool_acc:6.2f}%")
    print(f" 2. Cypher Execution Accuracy:                  {cypher_exec_acc:6.2f}%  (Target: 100.0%)")
    print(f" 3. Invalid-Query Rate:                         {invalid_query_rate:6.2f}%  (Target: < 2.0%)")
    print(f" 4. Grounded-Answer Score:                      {grounded_score:6.2f}%  (Target: >= 90.0%)")
    print(f" 5. Access-Policy Violations:                   {policy_violations_allowed:6d}   (Target: 0 Allowed)")
    print(f"    Adversarial Attack Interception Rate:       {policy_intercept_rate:6.2f}%  (Target: 100.0%)")
    print("="*65)
    print(f" Evaluation report written to: {REPORT_PATH}\n")

if __name__ == "__main__":
    run_benchmark(run_qwen_semantic_mode=True)
