"""
Part C & B3/B6 Audit Benchmark Runner (Development Set - Agent-Written)
Runs WITHOUT any router or prompt tuning:
  0. Pre-flight verification: Neo4j read-only write rejection + live get_campus_statistics
  1. Hybrid mode (90 questions: 80 legit + 10 adversarial)
  2. Router-Off qwen2.5:3b (90 questions: 80 legit + 10 adversarial) + exact B3 Pydantic ValidationError breakdown
  3. Router-Off qwen2.5:1.5b (80 legit questions)
Saves verbatim report to campus_knowledge_server/eval/part_c_dev_results.json
and updates campus_knowledge_server/eval/eval_report.json with B6 + Part C table.
"""
import os
import sys
import json
import time
import statistics
import requests
from pydantic import ValidationError
from dotenv import load_dotenv
from neo4j import GraphDatabase, WRITE_ACCESS

sys.path.insert(0, os.path.abspath("."))
load_dotenv(".env")

from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent
from campus_knowledge_server.tools.governed_executor import execute_tool, TOOL_SCHEMA_MAP
from campus_knowledge_server.security.ast_validator import SecurityViolationError
from campus_knowledge_server.security.auth import Principal

DATASET_PATH = "campus_knowledge_server/eval/benchmark_dataset.json"
OUT_PATH = "campus_knowledge_server/eval/part_c_dev_results.json"
EVAL_REPORT_PATH = "campus_knowledge_server/eval/eval_report.json"

with open(DATASET_PATH, "r", encoding="utf-8") as f:
    dataset = json.load(f)

legit_items = [q for q in dataset if not q.get("should_block")]
adv_items = [q for q in dataset if q.get("should_block")]

def check_gold_match(item, tool_result):
    if not tool_result or tool_result.get("error"):
        return False
    # Fix A6: Semantic search scored as expected/acceptable course appears in top 3
    if item.get("gold_tool") == "search_courses_semantic" and item.get("acceptable_courses"):
        courses = tool_result.get("courses") or []
        top3_codes = [str(c.get("code", "")).upper() for c in courses[:3] if isinstance(c, dict)]
        acceptable = {c.upper() for c in item["acceptable_courses"]}
        return any(code in acceptable for code in top3_codes)

    if item.get("gold_tool") == "get_campus_statistics":
        stats = tool_result.get("statistics")
        return isinstance(stats, dict) and "total_courses_indexed" in stats

    gold_ents = item.get("gold_entities", [])
    if not gold_ents:
        return True
    blob = json.dumps(tool_result, default=str).lower()
    return all(str(ge.get("id", "")).strip().lower() in blob for ge in gold_ents if ge.get("id"))

def classify_pydantic_error(tool_name, params, ve: ValidationError):
    schema_cls = TOOL_SCHEMA_MAP.get(tool_name)
    valid_fields = set(schema_cls.model_fields.keys()) if schema_cls else set()
    passed_keys = set(params.keys()) if isinstance(params, dict) else set()
    unknown_keys = sorted(passed_keys - valid_fields)
    err_types = [e.get("type", "") for e in ve.errors()]
    err_locs = [".".join(str(x) for x in e.get("loc", ())) for e in ve.errors()]

    has_type_err = any(
        any(tok in et for tok in ("type", "parsing", "greater_than", "less_than", "too_short", "too_long", "value_error"))
        for et in err_types
    )
    has_missing = any(et == "missing" for et in err_types)
    has_extra = any(et == "extra_forbidden" for et in err_types)

    # Categorize cleanly (a single rejection can have one primary cause; also track multi-cause flags)
    if has_extra or (has_missing and len(unknown_keys) > 0):
        primary = "wrong_parameter_name"
    elif has_type_err:
        primary = "wrong_type"
    elif has_missing:
        primary = "missing_field"
    else:
        primary = "other"

    return {
        "primary_category": primary,
        "unknown_keys": unknown_keys,
        "passed_keys": sorted(passed_keys),
        "valid_fields": sorted(valid_fields),
        "error_types": err_types,
        "error_locs": err_locs,
        "raw_errors": [{"loc": list(e.get("loc", ())), "type": e.get("type"), "msg": e.get("msg")} for e in ve.errors()],
    }

def warmup_ollama(model_name):
    print(f"\n[Warmup] Loading {model_name} into Ollama memory...", flush=True)
    try:
        r = requests.post(
            "http://127.0.0.1:11434/api/chat",
            json={
                "model": model_name,
                "messages": [{"role": "user", "content": "Reply with JSON: {\"ok\": true}"}],
                "format": "json",
                "stream": False,
                "keep_alive": "15m",
                "options": {"temperature": 0.0, "num_predict": 16}
            },
            timeout=120
        )
        print(f"[Warmup] {model_name} status={r.status_code}", flush=True)
    except Exception as e:
        print(f"[Warmup] {model_name} warning: {e}", flush=True)

# 0. Pre-flight verification
print("====================================================================", flush=True)
print(" 0. PRE-FLIGHT VERIFICATION (READ-ONLY NEO4J + LIVE STATISTICS)", flush=True)
print("====================================================================", flush=True)
d = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
)
ro_rejection = None
try:
    with d.session(default_access_mode=WRITE_ACCESS) as s:
        s.run("CREATE (n:_AuditReadOnlyCheck {x: 1}) RETURN n").consume()
    ro_rejection = "ERROR: WRITE SUCCEEDED!"
except Exception as e:
    ro_rejection = f"{type(e).__name__}: {e}"
finally:
    d.close()
print(f"Neo4j WRITE_ACCESS CREATE rejection:\n  {ro_rejection}", flush=True)

stats_live = execute_tool("get_campus_statistics", {"category": "all"})
print(f"Live get_campus_statistics:\n  source={stats_live.get('source')} | counts={stats_live.get('statistics')}", flush=True)

def run_eval_mode(label, model_name, use_heuristic_router, include_adversarial=True):
    print("\n====================================================================", flush=True)
    print(f" RUNNING: {label} (model={model_name}, router={'ON' if use_heuristic_router else 'OFF'})", flush=True)
    print("====================================================================", flush=True)

    if not use_heuristic_router:
        warmup_ollama(model_name)

    agent = GovernedCampusAgent(model_name=model_name)
    principal = Principal(user_id="bench_student", role="student", caller_type="agent")

    legit_tool_ok = 0
    legit_gold_ok = 0
    legit_invalid = 0
    legit_pydantic_rejects = 0
    legit_policy_rejects = 0
    legit_no_tool = 0
    latencies_ms = []
    semantic_details = []
    pydantic_breakdown = []
    legit_failures = []

    for idx, item in enumerate(legit_items, 1):
        qid = item["id"]
        query = item["query"]
        exp_tool = item["gold_tool"]
        t0 = time.perf_counter()

        sel_tool = None
        sel_params = {}
        tool_res = None
        invalid_reason = None
        gold_ok = False

        if use_heuristic_router:
            try:
                res = agent.execute_query(query, principal=principal, use_llm_synthesis=False, use_heuristic_router=True)
                sel_tool = res.get("tool_selected")
                sel_params = res.get("parameters") or {}
                tool_res = res.get("tool_result")
                if res.get("status") in ("VALIDATION_ERROR", "POLICY_VIOLATION", "FORBIDDEN_TOOL_FOR_ROLE"):
                    legit_invalid += 1
                    invalid_reason = res.get("status")
            except ValidationError as ve:
                legit_invalid += 1
                legit_pydantic_rejects += 1
                invalid_reason = "ValidationError"
            except SecurityViolationError as se:
                legit_invalid += 1
                legit_policy_rejects += 1
                invalid_reason = f"SecurityViolationError: {se}"
        else:
            # Router OFF: invoke Qwen directly via _select_tool_with_llm, then execute_tool (identical to execute_query router-off path)
            from campus_knowledge_server.security.ast_validator import ASTSecurityValidator
            is_adv, adv_reason = ASTSecurityValidator.is_adversarial_or_destructive(query)
            if is_adv:
                legit_invalid += 1
                legit_policy_rejects += 1
                sel_tool = "ast_security_interception"
                invalid_reason = f"AST_BLOCK: {adv_reason}"
            else:
                tc = agent._select_tool_with_llm(query)
                if not tc:
                    legit_no_tool += 1
                    sel_tool = None
                    invalid_reason = "NO_TOOL_RETURNED"
                else:
                    sel_tool, sel_params = tc
                    if not isinstance(sel_params, dict):
                        sel_params = {}
                    try:
                        tool_res = execute_tool(sel_tool, sel_params, principal=principal)
                    except ValidationError as ve:
                        legit_invalid += 1
                        legit_pydantic_rejects += 1
                        cls = classify_pydantic_error(sel_tool, sel_params, ve)
                        cls["id"] = qid
                        cls["query"] = query
                        cls["expected_tool"] = exp_tool
                        cls["selected_tool"] = sel_tool
                        cls["params"] = sel_params
                        pydantic_breakdown.append(cls)
                        invalid_reason = f"Pydantic:{cls['primary_category']}"
                    except SecurityViolationError as se:
                        legit_invalid += 1
                        legit_policy_rejects += 1
                        invalid_reason = f"SecurityViolationError: {se}"
                    except Exception as ex:
                        invalid_reason = f"ExecError: {type(ex).__name__}: {ex}"

        lat_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(lat_ms)

        tool_ok = (sel_tool == exp_tool)
        if tool_ok:
            legit_tool_ok += 1

        if tool_res and not invalid_reason:
            gold_ok = check_gold_match(item, tool_res)
            if gold_ok:
                legit_gold_ok += 1

        if exp_tool == "search_courses_semantic":
            top3 = [c.get("code") for c in ((tool_res or {}).get("courses") or [])[:3]]
            semantic_details.append({
                "id": qid,
                "query": query,
                "tool_selected": sel_tool,
                "top3_returned": top3,
                "acceptable_courses": item.get("acceptable_courses", []),
                "top3_match": gold_ok,
            })

        if not gold_ok:
            legit_failures.append({
                "id": qid,
                "exp_tool": exp_tool,
                "sel_tool": sel_tool,
                "sel_params": sel_params,
                "invalid_reason": invalid_reason,
            })

        if idx % 10 == 0 or idx == len(legit_items):
            print(
                f"  [{label}] {idx}/{len(legit_items)} | tool_ok={legit_tool_ok}/{idx} "
                f"| gold_ok={legit_gold_ok}/{idx} | invalid={legit_invalid} | med_lat={statistics.median(latencies_ms):.1f}ms",
                flush=True
            )

    adv_blocked = 0
    adv_violations = 0
    adv_details = []
    if include_adversarial:
        for item in adv_items:
            qid = item["id"]
            query = item["query"]
            blocked = False
            reason = ""
            try:
                res = agent.execute_query(query, principal=principal, use_llm_synthesis=False, use_heuristic_router=use_heuristic_router)
                if res.get("status") in ("POLICY_VIOLATION", "FORBIDDEN_TOOL_FOR_ROLE"):
                    blocked = True
                    reason = res.get("status")
                else:
                    reason = f"NOT_BLOCKED:{res.get('status')}:{res.get('tool_selected')}"
            except SecurityViolationError as se:
                blocked = True
                reason = f"SecurityViolationError: {se}"
            except ValidationError as ve:
                blocked = True
                reason = "ValidationError"
            if blocked:
                adv_blocked += 1
            else:
                adv_violations += 1
            adv_details.append({"id": qid, "blocked": blocked, "reason": reason})

    # Aggregate B3 counts
    b3_counts = {"wrong_parameter_name": 0, "wrong_type": 0, "missing_field": 0, "other": 0}
    for pb in pydantic_breakdown:
        b3_counts[pb["primary_category"]] = b3_counts.get(pb["primary_category"], 0) + 1

    return {
        "label": label,
        "model": model_name,
        "use_heuristic_router": use_heuristic_router,
        "legit_total": len(legit_items),
        "tool_accuracy_count": legit_tool_ok,
        "tool_accuracy_pct": round((legit_tool_ok / len(legit_items)) * 100.0, 2),
        "gold_match_count": legit_gold_ok,
        "gold_match_pct": round((legit_gold_ok / len(legit_items)) * 100.0, 2),
        "legit_invalid_query_count": legit_invalid,
        "legit_invalid_query_rate_pct": round((legit_invalid / len(legit_items)) * 100.0, 2),
        "legit_pydantic_rejects": legit_pydantic_rejects,
        "legit_policy_rejects": legit_policy_rejects,
        "legit_no_tool_returned": legit_no_tool,
        "median_latency_ms": round(statistics.median(latencies_ms), 1),
        "mean_latency_ms": round(statistics.mean(latencies_ms), 1),
        "adv_total": len(adv_items) if include_adversarial else None,
        "adv_blocked": adv_blocked if include_adversarial else None,
        "adv_policy_violations": adv_violations if include_adversarial else None,
        "adv_details": adv_details,
        "pydantic_rejection_counts_b3": b3_counts,
        "pydantic_rejection_details_b3": pydantic_breakdown,
        "semantic_top3_details": semantic_details,
        "legit_failures": legit_failures,
    }

# Execute all 3 runs
res_hybrid = run_eval_mode("Hybrid (Heuristic + Qwen 2.5 3B)", "qwen2.5:3b", use_heuristic_router=True, include_adversarial=True)
res_ro_3b = run_eval_mode("Router-Off (qwen2.5:3b)", "qwen2.5:3b", use_heuristic_router=False, include_adversarial=True)
res_ro_15b = run_eval_mode("Router-Off (qwen2.5:1.5b)", "qwen2.5:1.5b", use_heuristic_router=False, include_adversarial=False)

final_payload = {
    "dataset_label": "development set (agent-written)",
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "preflight": {
        "neo4j_write_rejection": ro_rejection,
        "live_campus_statistics_source": stats_live.get("source"),
        "live_campus_statistics_counts": stats_live.get("statistics"),
    },
    "adversarial_audit_history": {
        "first_pass_pre_patch": {
            "blocked": 6,
            "total": 10,
            "rate_pct": 60.0,
            "unblocked_ids": ["ADV-06", "ADV-08", "ADV-09", "ADV-10"],
            "data_leaked_or_writes_executed": False,
        },
        "post_patch": {
            "blocked": res_hybrid["adv_blocked"],
            "total": res_hybrid["adv_total"],
            "rate_pct": round((res_hybrid["adv_blocked"] / res_hybrid["adv_total"]) * 100.0, 2),
            "access_policy_violations": res_hybrid["adv_policy_violations"],
        },
    },
    "runs": {
        "hybrid_qwen_3b": res_hybrid,
        "router_off_qwen_3b": res_ro_3b,
        "router_off_qwen_1_5b": res_ro_15b,
    },
}

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(final_payload, f, indent=2)

# Update eval_report.json with clearly labelled B6 + development set table (preserving existing fields)
with open(EVAL_REPORT_PATH, "r", encoding="utf-8") as f:
    eval_rep = json.load(f)

eval_rep["dataset_label"] = "development set (agent-written)"
eval_rep["adversarial_audit_history"] = final_payload["adversarial_audit_history"]
eval_rep["development_set_summary_table"] = [
    {
        "mode": "Hybrid (Router ON + qwen2.5:3b)",
        "legit_n": res_hybrid["legit_total"],
        "tool_accuracy": f"{res_hybrid['tool_accuracy_count']}/{res_hybrid['legit_total']} ({res_hybrid['tool_accuracy_pct']}%)",
        "gold_match_accuracy": f"{res_hybrid['gold_match_count']}/{res_hybrid['legit_total']} ({res_hybrid['gold_match_pct']}%)",
        "legit_invalid_query_rate": f"{res_hybrid['legit_invalid_query_count']}/{res_hybrid['legit_total']} ({res_hybrid['legit_invalid_query_rate_pct']}%)",
        "median_latency_ms": res_hybrid["median_latency_ms"],
        "adv_first_pass_pre_patch": "6/10 (60.0%)",
        "adv_post_patch": f"{res_hybrid['adv_blocked']}/{res_hybrid['adv_total']} ({round(res_hybrid['adv_blocked']/res_hybrid['adv_total']*100,1)}%)",
        "access_policy_violations": res_hybrid["adv_policy_violations"],
    },
    {
        "mode": "Router-Off (qwen2.5:3b)",
        "legit_n": res_ro_3b["legit_total"],
        "tool_accuracy": f"{res_ro_3b['tool_accuracy_count']}/{res_ro_3b['legit_total']} ({res_ro_3b['tool_accuracy_pct']}%)",
        "gold_match_accuracy": f"{res_ro_3b['gold_match_count']}/{res_ro_3b['legit_total']} ({res_ro_3b['gold_match_pct']}%)",
        "legit_invalid_query_rate": f"{res_ro_3b['legit_invalid_query_count']}/{res_ro_3b['legit_total']} ({res_ro_3b['legit_invalid_query_rate_pct']}%)",
        "median_latency_ms": res_ro_3b["median_latency_ms"],
        "adv_first_pass_pre_patch": "6/10 (60.0%)",
        "adv_post_patch": f"{res_ro_3b['adv_blocked']}/{res_ro_3b['adv_total']} ({round(res_ro_3b['adv_blocked']/res_ro_3b['adv_total']*100,1)}%)",
        "access_policy_violations": res_ro_3b["adv_policy_violations"],
    },
    {
        "mode": "Router-Off (qwen2.5:1.5b)",
        "legit_n": res_ro_15b["legit_total"],
        "tool_accuracy": f"{res_ro_15b['tool_accuracy_count']}/{res_ro_15b['legit_total']} ({res_ro_15b['tool_accuracy_pct']}%)",
        "gold_match_accuracy": f"{res_ro_15b['gold_match_count']}/{res_ro_15b['legit_total']} ({res_ro_15b['gold_match_pct']}%)",
        "legit_invalid_query_rate": f"{res_ro_15b['legit_invalid_query_count']}/{res_ro_15b['legit_total']} ({res_ro_15b['legit_invalid_query_rate_pct']}%)",
        "median_latency_ms": res_ro_15b["median_latency_ms"],
        "adv_first_pass_pre_patch": "N/A (80 legit only)",
        "adv_post_patch": "N/A (80 legit only)",
        "access_policy_violations": "N/A",
    },
]

with open(EVAL_REPORT_PATH, "w", encoding="utf-8") as f:
    json.dump(eval_rep, f, indent=2)

print("\n====================================================================", flush=True)
print(" FINAL SUMMARY — DEVELOPMENT SET (AGENT-WRITTEN)", flush=True)
print("====================================================================", flush=True)
for row in eval_rep["development_set_summary_table"]:
    print(json.dumps(row), flush=True)

print("\n--- B3: Router-Off (qwen2.5:3b) Pydantic Rejection Breakdown ---", flush=True)
print(json.dumps(res_ro_3b["pydantic_rejection_counts_b3"], indent=2), flush=True)
for pb in res_ro_3b["pydantic_rejection_details_b3"]:
    print(f"  {pb['id']} | tool={pb['selected_tool']} | cat={pb['primary_category']} | passed={pb['passed_keys']} | unknown={pb['unknown_keys']} | errs={pb['raw_errors']}", flush=True)

print("\n--- A6: Semantic Search Top-3 Results (Hybrid) ---", flush=True)
for sd in res_hybrid["semantic_top3_details"]:
    print(f"  {sd['id']} | top3={sd['top3_returned']} | match={sd['top3_match']}", flush=True)

print(f"\nSaved full results to {OUT_PATH} and updated {EVAL_REPORT_PATH}", flush=True)
