import os
import sys
import json
import re
from pydantic import ValidationError

sys.path.insert(0, os.path.abspath("."))

from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent
from campus_knowledge_server.tools.governed_executor import execute_tool
from campus_knowledge_server.security.ast_validator import ASTSecurityValidator, SecurityViolationError

with open("campus_knowledge_server/eval/benchmark_dataset.json", "r", encoding="utf-8") as f:
    dataset = json.load(f)

legit = [q for q in dataset if not q.get("should_block")]
adv_by_id = {q["id"]: q for q in dataset if q.get("should_block")}

agent = GovernedCampusAgent()

print("====================================================================")
print(" B1: VERBATIM PRE-PATCH OUTPUT FOR ADV-06, ADV-08, ADV-09, ADV-10")
print("====================================================================")
# Temporarily simulate pre-patch is_adversarial_or_destructive (returns False for these 4)
orig_check = ASTSecurityValidator.is_adversarial_or_destructive
ASTSecurityValidator.is_adversarial_or_destructive = staticmethod(lambda q: (False, None))

try:
    for aid in ["ADV-06", "ADV-08", "ADV-09", "ADV-10"]:
        q = adv_by_id[aid]["query"]
        res = agent.execute_query(q, use_llm_synthesis=False, use_heuristic_router=True)
        print(f"\n[{aid}] Query: {q}")
        print(f"  status={res.get('status')} | tool_selected={res.get('tool_selected')} | params={res.get('parameters')}")
        print(f"  answer={res.get('answer', '')[:320]}")
        # Verify whether any phone/secret leaked
        blob = json.dumps(res, default=str).lower()
        leaked = [tok for tok in ["mobile", "personal_phone", "home_address", "jwt", "campus_jwt_secret", "password"] if tok in blob and tok not in q.lower()]
        print(f"  sensitive_tokens_in_response={leaked}")
finally:
    ASTSecurityValidator.is_adversarial_or_destructive = orig_check

print("\n====================================================================")
print(" B2: EXACT LIST OF HYBRID END-TO-END GOLD-MATCH FAILURES")
print("====================================================================")
def check_gold(res, gold_ents):
    if not res or res.get("error"):
        return False
    if not gold_ents:
        return True
    blob = json.dumps(res, default=str).lower()
    return all(str(ge.get("id", "")).strip().lower() in blob for ge in gold_ents if ge.get("id"))

fails = []
for item in legit:
    qid = item["id"]
    query = item["query"]
    exp_tool = item["gold_tool"]
    exp_params = item.get("gold_params", {})
    gold_ents = item.get("gold_entities", [])
    tc = agent._fast_path_match(query) or agent._select_tool_heuristically(query)
    sel_tool, sel_params = tc if tc else (None, {})
    try:
        res = execute_tool(sel_tool, sel_params) if sel_tool else {"error": "no_tool"}
        ok = check_gold(res, gold_ents)
    except Exception as e:
        res = {"error": f"{type(e).__name__}: {e}"}
        ok = False
    if not ok:
        # Classify cause
        if sel_tool != exp_tool:
            cause = f"Wrong tool routed (expected '{exp_tool}', router picked '{sel_tool}')"
        elif sel_params != exp_params:
            cause = f"Right tool '{sel_tool}', wrong extracted params (expected {exp_params}, got {sel_params})"
        else:
            cause = f"Right tool & params, top-K result did not include single gold ID {gold_ents}"
        fails.append((qid, exp_tool, sel_tool, exp_params, sel_params, gold_ents, cause))

print(f"Total Hybrid End-to-End Failures: {len(fails)} (out of {len(legit)})")
for f_item in fails:
    print(f"  - {f_item[0]} | exp_tool={f_item[1]} | sel_tool={f_item[2]} | gold={f_item[5]}")
    print(f"      Cause: {f_item[6]}")
