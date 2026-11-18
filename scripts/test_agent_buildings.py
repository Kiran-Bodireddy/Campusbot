import sys, os
sys.path.insert(0, os.path.abspath("."))
from campus_knowledge_server.agent.qwen_agent import GovernedCampusAgent

agent = GovernedCampusAgent()

queries = [
    "tp1 building",
    "where is the placement office",
    "tell me about tp2",
    "bel building",
    "what is in c.v. raman"
]

for q in queries:
    print(f"\n==========================================")
    print(f"QUERY: '{q}'")
    print(f"==========================================")
    res = agent.execute_query(q, use_llm_synthesis=False)
    print("Tool Selected:", res.get("tool_selected"))
    print("Status:", res.get("status"))
    print("Answer:\n", res.get("answer"))
