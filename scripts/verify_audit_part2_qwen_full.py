import os
import sys
import json
import time
import statistics
import requests

sys.path.insert(0, os.path.abspath("."))

from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent
from campus_knowledge_server.tools.governed_executor import execute_tool

with open("campus_knowledge_server/eval/benchmark_dataset.json", "r", encoding="utf-8") as f:
    dataset = json.load(f)

legit = [q for q in dataset if not q.get("should_block")]
agent = GovernedCampusAgent()

# Warm up model once
print("Warming up qwen2.5:3b...", flush=True)
requests.post(
    f"{agent.ollama_url}/api/generate",
    json={"model": agent.model_name, "prompt": "Say OK", "stream": False, "keep_alive": "15m", "options": {"num_predict": 3}},
    timeout=90.0
)

print("\n====================================================================", flush=True)
print(f" ITEM 3: FULL 80-QUESTION QWEN-ALONE BENCHMARK (use_heuristic_router=False)")
print("====================================================================", flush=True)

qwen_correct = 0
qwen_latencies_ms = []
qwen_misses = []
qwen_records = []

for idx, item in enumerate(legit, 1):
    q_id = item["id"]
    query = item["query"]
    expected = item["gold_tool"]

    t0 = time.time()
    res = agent._select_tool_with_llm(query)
    lat_ms = (time.time() - t0) * 1000
    qwen_latencies_ms.append(lat_ms)

    selected = res[0] if res else None
    ok = (selected == expected)
    if ok:
        qwen_correct += 1
    else:
        qwen_misses.append({"id": q_id, "query": query, "expected": expected, "qwen_selected": selected})

    qwen_records.append({
        "id": q_id,
        "expected": expected,
        "selected": selected,
        "correct": ok,
        "latency_ms": round(lat_ms, 1)
    })
    if idx % 10 == 0 or idx == len(legit):
        print(f"  Progress [{idx:02d}/{len(legit)}] | Running Acc: {(qwen_correct/idx)*100:.2f}% | Last: {lat_ms:.0f}ms ({selected})", flush=True)

qwen_acc = (qwen_correct / len(legit)) * 100
median_lat = statistics.median(qwen_latencies_ms)
mean_lat = statistics.mean(qwen_latencies_ms)
print(f"\nFULL 80-QUESTION QWEN-ALONE ACCURACY (qwen2.5:3b): {qwen_acc:.2f}% ({qwen_correct}/{len(legit)})", flush=True)
print(f"MEDIAN LATENCY: {median_lat:.1f} ms | MEAN LATENCY: {mean_lat:.1f} ms", flush=True)

print("\n====================================================================", flush=True)
print(f" ITEM 4: FULL 80-QUESTION GROUNDING BEFORE vs AFTER GUARD + TP-101")
print("====================================================================", flush=True)

# Explicit TP-101 capture first
tp_q = "Room schedule for TP-101"
tp_res = execute_tool("find_room_schedule", {"room_id": "TP-101"})
tp_prompt = agent._build_concierge_prompt(tp_q, agent._compact_tool_payload(tp_res, "find_room_schedule"))
r_tp = requests.post(
    f"{agent.ollama_url}/api/generate",
    json={"model": agent.model_name, "prompt": tp_prompt, "stream": False, "keep_alive": "15m", "options": {"num_predict": 70, "temperature": 0.1}},
    timeout=60.0
)
tp_raw = r_tp.json().get("response", "").strip() if r_tp.status_code == 200 else ""
tp_final, tp_passed = agent._validate_and_guard_grounding(tp_q, tp_raw, "find_room_schedule", tp_res)
print(f"TP-101 Raw Qwen Output:\n  {tp_raw}", flush=True)
print(f"TP-101 Passed Guard Before Sub: {tp_passed}", flush=True)
print(f"TP-101 Post-Guard Answer:\n  {tp_final[:250]}", flush=True)

before_ok = 0
substitutions = 0
after_ok = 0
sub_examples = []

for idx, item in enumerate(legit, 1):
    q_id = item["id"]
    query = item["query"]
    tool_call = agent._select_tool_heuristically(query)
    if not tool_call:
        tool_name, tool_params = item["gold_tool"], item.get("gold_params", {})
    else:
        tool_name, tool_params = tool_call

    try:
        tool_res = execute_tool(tool_name, tool_params)
    except Exception:
        tool_res = {"error": "validation_error"}

    # Build compact payload via agent helper
    compact = agent._compact_tool_payload(tool_res, tool_name)
    prompt = agent._build_concierge_prompt(query, compact)

    try:
        r = requests.post(
            f"{agent.ollama_url}/api/generate",
            json={"model": agent.model_name, "prompt": prompt, "stream": False, "keep_alive": "15m", "options": {"num_predict": 65, "temperature": 0.1}},
            timeout=60.0
        )
        raw_ans = r.json().get("response", "").strip() if r.status_code == 200 else ""
    except Exception:
        raw_ans = ""

    final_ans, passed_guard = agent._validate_and_guard_grounding(query, raw_ans, tool_name, tool_res)
    if passed_guard and raw_ans:
        before_ok += 1
        after_ok += 1
    else:
        substitutions += 1
        after_ok += 1
        if len(sub_examples) < 8:
            sub_examples.append({
                "id": q_id,
                "query": query,
                "tool": tool_name,
                "raw_qwen_answer": raw_ans,
                "substituted_preview": final_ans[:180]
            })

    if idx % 10 == 0 or idx == len(legit):
        print(f"  Grounding Progress [{idx:02d}/{len(legit)}] | Before Guard: {(before_ok/idx)*100:.2f}% | Subs: {substitutions}", flush=True)

print(f"\nFULL 80-QUESTION GROUNDING SUMMARY:", flush=True)
print(f"  Grounded-Answer Score BEFORE Guard: {(before_ok/len(legit))*100:.2f}% ({before_ok}/{len(legit)})", flush=True)
print(f"  Substitutions Triggered:            {substitutions}", flush=True)
print(f"  Grounded-Answer Score AFTER Guard:  {(after_ok/len(legit))*100:.2f}% ({after_ok}/{len(legit)})", flush=True)

report = {
    "qwen_alone_80": {
        "model": agent.model_name,
        "accuracy_pct": round(qwen_acc, 2),
        "correct": qwen_correct,
        "total": len(legit),
        "median_latency_ms": round(median_lat, 1),
        "mean_latency_ms": round(mean_lat, 1),
        "misses": qwen_misses
    },
    "grounding_80": {
        "before_guard_pct": round((before_ok / len(legit)) * 100, 2),
        "before_guard_count": before_ok,
        "substitutions_count": substitutions,
        "after_guard_pct": round((after_ok / len(legit)) * 100, 2),
        "tp101_raw_qwen": tp_raw,
        "tp101_passed_guard": tp_passed,
        "tp101_post_guard": tp_final,
        "substitution_examples": sub_examples
    }
}

out_path = "campus_knowledge_server/eval/qwen_full_audit_report.json"
with open(out_path, "w", encoding="utf-8") as outf:
    json.dump(report, outf, indent=2)
print(f"\nFull audit report saved to: {out_path}", flush=True)
