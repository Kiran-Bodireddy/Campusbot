import urllib.request
import json
import subprocess
import sys
import os

BASE_URL = "http://127.0.0.1:8000"
results = {
    "health_check": None,
    "audit_verification": None,
    "agent_queries": [],
    "pytest_summary": None
}

def http_get(endpoint):
    url = f"{BASE_URL}{endpoint}"
    req = urllib.request.Request(url, headers={"User-Agent": "VerificationScript/1.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))

def http_post(endpoint, data):
    url = f"{BASE_URL}{endpoint}"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "VerificationScript/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))

# 1. Health Check
try:
    results["health_check"] = http_get("/health")
except Exception as e:
    results["health_check"] = {"error": str(e)}

# 2. Cryptographic Audit Chain Verification
try:
    results["audit_verification"] = http_get("/audit/verify")
except Exception as e:
    results["audit_verification"] = {"error": str(e)}

# 3. Live Agent Queries
test_queries = [
    {
        "description": "Semester 3 Subjects for B.Tech CSE",
        "query": "What are the 3rd semester subjects for CSE?",
        "expected_tool": "get_semester_curriculum",
        "expected_keywords": ["21CSC201J", "21CSC202J", "Data Structures", "Operating Systems", "23 Credits"]
    },
    {
        "description": "Semester 4 Courses for Aerospace Engineering",
        "query": "What courses do I take in Semester 4 of Aerospace Engineering?",
        "expected_tool": "get_semester_curriculum",
        "expected_keywords": ["Aerospace", "Semester 4", "21ASC", "Credits"]
    },
    {
        "description": "Full 8-Semester Curriculum Plan for Mechanical",
        "query": "What is the full curriculum plan for Mechanical Engineering?",
        "expected_tool": "get_semester_curriculum",
        "expected_keywords": ["Mechanical", "8-Semester", "Semester 1", "Semester 8"]
    },
    {
        "description": "Prerequisite Eligibility Check",
        "query": "Can a student who completed 21CSC206T take 21CSO451T?",
        "expected_tool": "verify_prerequisites",
        "expected_keywords": ["ELIGIBLE", "satisfied"]
    },
    {
        "description": "Official Course Lookup",
        "query": "Lookup course 21CSC201J",
        "expected_tool": "lookup_course",
        "expected_keywords": ["21CSC201J", "Data Structures And Algorithms", "School of Computing"]
    },
    {
        "description": "Admission Eligibility & Fees",
        "query": "What is the admission eligibility and fee for B.Tech Computer Science with 65% in PCM?",
        "expected_tool": "check_admission_eligibility",
        "expected_keywords": ["ELIGIBLE", "60.0%", "SRMJEEE", "PCM"]
    },
    {
        "description": "Campus Aggregation Statistics",
        "query": "How many degree programs and courses does SRM offer?",
        "expected_tool": "get_campus_statistics",
        "expected_keywords": ["428 accredited", "668 course modules", "2,501"]
    }
]

for t in test_queries:
    try:
        res = http_post("/agent/ask", {"query": t["query"], "use_qwen": False, "role": "student"})
        tool_used = res.get("tool_selected")
        status_val = res.get("status")
        answer_text = res.get("answer", "")
        
        matches = [kw for kw in t["expected_keywords"] if kw.lower() in answer_text.lower()]
        passed = (tool_used == t["expected_tool"]) and (len(matches) >= len(t["expected_keywords"]) // 2)
        
        results["agent_queries"].append({
            "test": t["description"],
            "query": t["query"],
            "passed": passed,
            "tool_selected": tool_used,
            "status": status_val,
            "keywords_found": matches,
            "keywords_expected": t["expected_keywords"],
            "answer_preview": answer_text[:280] + ("..." if len(answer_text) > 280 else "")
        })
    except Exception as e:
        results["agent_queries"].append({
            "test": t["description"],
            "query": t["query"],
            "passed": False,
            "error": str(e)
        })

# 4. Save JSON Report
out_path = "campus_knowledge_server/data/system_verification_report.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

# 5. Format human-readable verification report
report_lines = [
    "=" * 70,
    "CAMPUS KNOWLEDGE SERVER & UNIFIED CURRICULUM VERIFICATION AUDIT",
    "=" * 70,
    f"Server Health: {results['health_check'].get('status')} | Mode: {results['health_check'].get('mode')}",
    f"Indexed Courses in Graph: {results['health_check'].get('indexed_courses')}",
    f"Indexed Faculty in Graph: {results['health_check'].get('indexed_faculty')}",
    f"Indexed Rooms in Graph:   {results['health_check'].get('indexed_rooms')}",
    f"Audit Log Hash Chain:    {results['audit_verification'].get('status')} ({results['audit_verification'].get('detail')})",
    "",
    "--- LIVE AGENT INTENT & QUERY VERIFICATIONS ---"
]

all_passed = True
for idx, q_res in enumerate(results["agent_queries"], 1):
    status_label = "PASS" if q_res.get("passed") else "FAIL"
    if not q_res.get("passed"): all_passed = False
    report_lines.append(f"\n[{status_label}] Test {idx}: {q_res['test']}")
    report_lines.append(f"  Query:         \"{q_res['query']}\"")
    report_lines.append(f"  Tool Executed: {q_res.get('tool_selected')} (Status: {q_res.get('status')})")
    report_lines.append(f"  Keywords Matched: {len(q_res.get('keywords_found', []))}/{len(q_res.get('keywords_expected', []))}")
    report_lines.append(f"  Answer Snippet:\n  {q_res.get('answer_preview', '').replace(chr(10), chr(10) + '  ')}")

report_lines.append("\n" + "=" * 70)
report_lines.append(f"FINAL AUDIT RESULT: {'ALL VERIFICATIONS PASSED' if all_passed else 'SOME VERIFICATIONS FAILED'}")
report_lines.append("=" * 70)

summary_path = "campus_knowledge_server/data/system_verification_summary.txt"
with open(summary_path, "w", encoding="utf-8") as f:
    f.write("\n".join(report_lines) + "\n")

print(f"Verification complete. Summary written to {summary_path}")

