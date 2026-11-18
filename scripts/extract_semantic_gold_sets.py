import json
import re

with open("Datasets/courses.json", "r", encoding="utf-8") as f:
    courses = json.load(f)

with open("campus_knowledge_server/eval/benchmark_dataset.json", "r", encoding="utf-8") as f:
    bench = json.load(f)

sem_items = [x for x in bench if x.get("gold_tool") == "search_courses_semantic"]
print(f"Total search_courses_semantic benchmark items: {len(sem_items)}")
for x in sem_items:
    print(f"  {x['id']}: {x['query']} | gold_entities={x.get('gold_entities')}")

queries = {
    "SH-44": ["deep learning", "neural network", "machine learning", "artificial intelligence"],
    "SH-45": ["cloud", "distributed"],
    "SH-46": ["natural language", "nlp", "text mining", "computational linguistics", "speech"],
    "SH-47": ["cyber", "cryptography", "security", "network defense"],
    "SH-48": ["database", "sql", "dbms"],
    "SH-49": ["robot", "automation", "computer vision", "image processing"],
}

print("\nMatching courses in Datasets/courses.json:")
for qid, kws in queries.items():
    matches = []
    for c in courses:
        code = c.get("code", "")
        name = c.get("name", "")
        nl = name.lower()
        # Exclude generic capstone/project/internship/seminar courses
        if any(skip in nl for skip in ["major project", "minor project", "internship", "seminar", "comprehensive", "industrial training"]):
            continue
        if any(k in nl for k in kws):
            matches.append((code, name))
    print(f"\n=== {qid} ({len(matches)} matches) ===")
    for code, name in matches[:25]:
        print(f"  {code}: {name}")
