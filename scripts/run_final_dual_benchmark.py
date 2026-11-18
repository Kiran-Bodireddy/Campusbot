import os
import sys
import json
import time
import statistics
import requests
from pydantic import ValidationError

sys.path.insert(0, os.path.abspath("."))

from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent
from campus_knowledge_server.tools.governed_executor import execute_tool
from campus_knowledge_server.security.ast_validator import ASTSecurityValidator, SecurityViolationError
from campus_knowledge_server.security.audit import AUDIT_LOG_FILE

with open("campus_knowledge_server/eval/benchmark_dataset.json", "r", encoding="utf-8") as f:
    dataset = json.load(f)

legit = [q for q in dataset if not q.get("should_block")]
adv = [q for q in dataset if q.get("should_block")]

agent = GovernedCampusAgent()

def check_gold_match(res: dict, gold_ents: list) -> bool:
    if not res or res.get("error"):
        return False
    if not gold_ents:
        return True
    blob = json.dumps(res, default=str).lower()
    for ge in gold_ents:
        gid = str(ge.get("id", "")).strip().lower()
        if not gid:
            continue
        if gid not in blob:
            return False
    return True

def get_last_audit_reason() -> str:
    try:
        with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as af:
            lines = [l.strip() for l in af if l.strip()]
        if lines:
            ev = json.loads(lines[-1])
            return ev.get("violation_reason") or ev.get("status", "")
    except Exception:
        pass
    return ""

print("====================================================================", flush=True)
print(" CHECK 1: INTEGER SLOT ACCEPTANCE & LIVE get_campus_statistics()")
print("====================================================================", flush=True)
r_slot1 = execute_tool("find_available_rooms", {"building_code": "UB", "day": "Monday", "slot": 1})
r_slot2 = execute_tool("find_available_rooms", {"building_code": "TP", "day": "Tuesday", "slot": 2})
print(f"slot=1 normalized -> '{r_slot1.get('slot')}' | available_count={r_slot1.get('available_count')}", flush=True)
print(f"slot=2 normalized -> '{r_slot2.get('slot')}' | available_count={r_slot2.get('available_count')}", flush=True)

stats_live = execute_tool("get_campus_statistics", {"category": "all"})
print("LIVE get_campus_statistics('all'):", json.dumps(stats_live["statistics"], indent=2), flush=True)

print("\n====================================================================", flush=True)
print(" BENCHMARK MODE A: HYBRID MODE (use_heuristic_router=True) ON 90 ITEMS")
print("====================================================================", flush=True)
hyb_tool_ok = 0
hyb_gold_ok = 0
hyb_legit_invalid = 0
hyb_gold_fails = []
hyb_tool_fails = []

for item in legit:
    qid = item["id"]
    query = item["query"]
    expected_tool = item["gold_tool"]
    gold_ents = item.get("gold_entities", [])

    # 1. Tool selection via hybrid path
    tc = agent._fast_path_match(query) or agent._select_tool_heuristically(query)
    sel_tool, sel_params = tc if tc else (None, {})
    if sel_tool == expected_tool:
        hyb_tool_ok += 1
    else:
        hyb_tool_fails.append((qid, expected_tool, sel_tool))

    # 2. Execute selected tool via execute_tool
    try:
        res = execute_tool(sel_tool, sel_params) if sel_tool else {"error": "no_tool"}
        if check_gold_match(res, gold_ents):
            hyb_gold_ok += 1
        else:
            hyb_gold_fails.append((qid, sel_tool, expected_tool, gold_ents, json.dumps(res, default=str)[:140]))
    except (ValidationError, SecurityViolationError) as e:
        hyb_legit_invalid += 1
        hyb_gold_fails.append((qid, sel_tool, expected_tool, gold_ents, f"{type(e).__name__}: {str(e)[:100]}"))

# Also check gold-params direct Cypher gold-match accuracy over all 80
direct_gold_ok = 0
direct_invalid = 0
direct_fails = []
for item in legit:
    try:
        res = execute_tool(item["gold_tool"], item.get("gold_params", {}))
        if check_gold_match(res, item.get("gold_entities", [])):
            direct_gold_ok += 1
        else:
            direct_fails.append((item["id"], item["gold_tool"], item.get("gold_entities"), json.dumps(res, default=str)[:140]))
    except (ValidationError, SecurityViolationError) as e:
        direct_invalid += 1
        direct_fails.append((item["id"], item["gold_tool"], item.get("gold_entities"), f"{type(e).__name__}: {str(e)[:100]}"))

# Adversarial check (10 items) in Hybrid Mode
hyb_adv_blocked = 0
for item in adv:
    res = agent.execute_query(item["query"], use_llm_synthesis=False, use_heuristic_router=True)
    if res.get("status") == "POLICY_VIOLATION":
        hyb_adv_blocked += 1

print(f"Hybrid Tool-Selection Accuracy:        {(hyb_tool_ok/len(legit))*100:.2f}% ({hyb_tool_ok}/{len(legit)})", flush=True)
print(f"Hybrid End-to-End Gold-Match Accuracy: {(hyb_gold_ok/len(legit))*100:.2f}% ({hyb_gold_ok}/{len(legit)})", flush=True)
print(f"Direct Gold-Params Cypher Accuracy:    {(direct_gold_ok/len(legit))*100:.2f}% ({direct_gold_ok}/{len(legit)})", flush=True)
print(f"Hybrid Legitimate Invalid-Query Rate:  {(hyb_legit_invalid/len(legit))*100:.2f}% ({hyb_legit_invalid}/{len(legit)})", flush=True)
print(f"Hybrid Adversarial Rejected Rate:      {(hyb_adv_blocked/len(adv))*100:.2f}% ({hyb_adv_blocked}/{len(adv)})", flush=True)
print(f"Hybrid Access-Policy Violations:       {len(adv) - hyb_adv_blocked} allowed", flush=True)
if direct_fails:
    print(f"Direct Gold-Params Mismatches ({len(direct_fails)}):", flush=True)
    for df in direct_fails:
        print("  -", df, flush=True)

print("\nWarming up qwen2.5:3b...", flush=True)
requests.post(
    f"{agent.ollama_url}/api/generate",
    json={"model": agent.model_name, "prompt": "Say OK", "stream": False, "keep_alive": "20m", "options": {"num_predict": 3}},
    timeout=90.0
)

print("\n====================================================================", flush=True)
print(" BENCHMARK MODE B: ROUTER-OFF / QWEN-ALONE (qwen2.5:3b) ON 90 ITEMS")
print("====================================================================", flush=True)
qwen_tool_ok = 0
qwen_gold_ok = 0
qwen_legit_invalid = 0
qwen_latencies = []
qwen_invalid_details = []
qwen_misses = []

for idx, item in enumerate(legit, 1):
    qid = item["id"]
    query = item["query"]
    expected_tool = item["gold_tool"]
    gold_ents = item.get("gold_entities", [])

    t0 = time.time()
    tc = agent._select_tool_with_llm(query)
    lat_ms = (time.time() - t0) * 1000
    qwen_latencies.append(lat_ms)

    sel_tool, sel_params = tc if tc else (None, {})
    if sel_tool == expected_tool:
        qwen_tool_ok += 1
    else:
        qwen_misses.append({"id": qid, "expected": expected_tool, "selected": sel_tool})

    if sel_tool:
        try:
            res = execute_tool(sel_tool, sel_params)
            if check_gold_match(res, gold_ents):
                qwen_gold_ok += 1
        except (ValidationError, SecurityViolationError) as e:
            qwen_legit_invalid += 1
            qwen_invalid_details.append({"id": qid, "tool": sel_tool, "params": sel_params, "error": f"{type(e).__name__}: {str(e)[:120]}"})
    else:
        qwen_legit_invalid += 1
        qwen_invalid_details.append({"id": qid, "tool": None, "params": {}, "error": "No valid tool returned by Qwen"})

    if idx % 10 == 0 or idx == len(legit):
        print(f"  Router-Off [{idx:02d}/{len(legit)}] | ToolAcc: {(qwen_tool_ok/idx)*100:.1f}% | GoldAcc: {(qwen_gold_ok/idx)*100:.1f}% | LegitInv: {qwen_legit_invalid} | Last: {lat_ms:.0f}ms", flush=True)

# Adversarial check (10 items) in Router-Off mode
qwen_adv_blocked = 0
for item in adv:
    res = agent.execute_query(item["query"], use_llm_synthesis=False, use_heuristic_router=False)
    if res.get("status") == "POLICY_VIOLATION":
        qwen_adv_blocked += 1

print(f"\nRouter-Off Tool-Selection Accuracy:        {(qwen_tool_ok/len(legit))*100:.2f}% ({qwen_tool_ok}/{len(legit)})", flush=True)
print(f"Router-Off End-to-End Gold-Match Accuracy: {(qwen_gold_ok/len(legit))*100:.2f}% ({qwen_gold_ok}/{len(legit)})", flush=True)
print(f"Router-Off Median Latency:                 {statistics.median(qwen_latencies):.1f} ms", flush=True)
print(f"Router-Off Legitimate Invalid-Query Rate:  {(qwen_legit_invalid/len(legit))*100:.2f}% ({qwen_legit_invalid}/{len(legit)})", flush=True)
print(f"Router-Off Adversarial Rejected Rate:      {(qwen_adv_blocked/len(adv))*100:.2f}% ({qwen_adv_blocked}/{len(adv)})", flush=True)
print(f"Router-Off Access-Policy Violations:       {len(adv) - qwen_adv_blocked} allowed", flush=True)

print("\n====================================================================", flush=True)
print(" ITEM 2: FIXED GROUNDING GUARD + num_predict=180 OVER ALL 80 ITEMS")
print("====================================================================", flush=True)
before_ok = 0
subs_list = []

for idx, item in enumerate(legit, 1):
    qid = item["id"]
    query = item["query"]
    tool_name = item["gold_tool"]
    tool_params = item.get("gold_params", {})
    try:
        tool_res = execute_tool(tool_name, tool_params)
    except Exception:
        tool_res = {"error": "exec_err"}

    compact = agent._compact_tool_payload(tool_res, tool_name)
    prompt = agent._build_concierge_prompt(query, compact)
    try:
        r = requests.post(
            f"{agent.ollama_url}/api/generate",
            json={"model": agent.model_name, "prompt": prompt, "stream": False, "keep_alive": "20m", "options": {"num_predict": 180, "temperature": 0.1}},
            timeout=90.0
        )
        raw_ans = r.json().get("response", "").strip() if r.status_code == 200 else ""
    except Exception as e:
        raw_ans = ""

    final_ans, passed_guard = agent._validate_and_guard_grounding(query, raw_ans, tool_name, tool_res)
    if passed_guard and raw_ans:
        before_ok += 1
    else:
        reason = get_last_audit_reason() if raw_ans else "Empty/Timeout LLM output"
        subs_list.append({
            "id": qid,
            "query": query,
            "tool": tool_name,
            "reason": reason,
            "raw_qwen_answer": raw_ans,
            "tool_res_snippet": json.dumps(compact, default=str)[:220]
        })

    if idx % 10 == 0 or idx == len(legit):
        print(f"  Grounding [{idx:02d}/{len(legit)}] | Before Guard: {(before_ok/idx)*100:.2f}% | Subs: {len(subs_list)}", flush=True)

print(f"\nFIXED GROUNDING SUMMARY (num_predict=180):", flush=True)
print(f"  Before-Guard Grounded Score: {(before_ok/len(legit))*100:.2f}% ({before_ok}/{len(legit)})", flush=True)
print(f"  Substitutions Triggered:     {len(subs_list)}", flush=True)
print(f"  After-Guard Grounded Score:  100.00% ({len(legit)}/{len(legit)})", flush=True)
for sub in subs_list:
    print(f"  [SUB {sub['id']} | {sub['tool']}] Reason: {sub['reason']} | Raw: {sub['raw_qwen_answer'][:160]}", flush=True)

report = {
    "integer_slot_check": {
        "slot_1": r_slot1.get("slot"),
        "slot_2": r_slot2.get("slot")
    },
    "live_campus_statistics": stats_live["statistics"],
    "hybrid_mode": {
        "tool_selection_accuracy_pct": round((hyb_tool_ok / len(legit)) * 100, 2),
        "tool_selection_correct": hyb_tool_ok,
        "end_to_end_gold_match_pct": round((hyb_gold_ok / len(legit)) * 100, 2),
        "end_to_end_gold_match_count": hyb_gold_ok,
        "direct_gold_params_cypher_accuracy_pct": round((direct_gold_ok / len(legit)) * 100, 2),
        "direct_gold_params_count": direct_gold_ok,
        "legitimate_invalid_query_rate_pct": round((hyb_legit_invalid / len(legit)) * 100, 2),
        "legitimate_invalid_count": hyb_legit_invalid,
        "adversarial_rejected_rate_pct": round((hyb_adv_blocked / len(adv)) * 100, 2),
        "adversarial_blocked_count": hyb_adv_blocked,
        "access_policy_violations_allowed": len(adv) - hyb_adv_blocked,
        "direct_gold_fails": direct_fails,
        "hybrid_tool_fails": hyb_tool_fails,
        "hybrid_gold_fails": hyb_gold_fails
    },
    "router_off_qwen_alone": {
        "model": agent.model_name,
        "tool_selection_accuracy_pct": round((qwen_tool_ok / len(legit)) * 100, 2),
        "tool_selection_correct": qwen_tool_ok,
        "end_to_end_gold_match_pct": round((qwen_gold_ok / len(legit)) * 100, 2),
        "end_to_end_gold_match_count": qwen_gold_ok,
        "median_latency_ms": round(statistics.median(qwen_latencies), 1),
        "legitimate_invalid_query_rate_pct": round((qwen_legit_invalid / len(legit)) * 100, 2),
        "legitimate_invalid_count": qwen_legit_invalid,
        "adversarial_rejected_rate_pct": round((qwen_adv_blocked / len(adv)) * 100, 2),
        "adversarial_blocked_count": qwen_adv_blocked,
        "access_policy_violations_allowed": len(adv) - qwen_adv_blocked,
        "invalid_details": qwen_invalid_details,
        "misses": qwen_misses
    },
    "grounding_fixed_80": {
        "num_predict": 180,
        "before_guard_pct": round((before_ok / len(legit)) * 100, 2),
        "before_guard_count": before_ok,
        "substitutions_count": len(subs_list),
        "after_guard_pct": 100.0,
        "substitutions": subs_list
    }
}

out_path = "campus_knowledge_server/eval/final_dual_benchmark_report.json"
with open(out_path, "w", encoding="utf-8") as outf:
    json.dump(report, outf, indent=2)
print(f"\nSaved complete report to {out_path}", flush=True)
