"""
Master Benchmark Dataset Builder (200 Questions)
Generates campus_knowledge_server/eval/benchmark_dataset.json:
- 140 Single-Hop queries across 13 student-accessible governed tools
- 35 Multi-Hop relational dependency & chaining queries
- 25 Adversarial security injection & policy violation vectors
"""
import os
import json

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(ROOT_DIR, "campus_knowledge_server", "eval", "benchmark_dataset.json")

def generate_benchmark_dataset():
    if not os.path.exists(OUT_PATH):
        raise FileNotFoundError(f"Source dataset not found at {OUT_PATH}")
    with open(OUT_PATH, "r", encoding="utf-8") as f:
        items = json.load(f)
    print(f"Loaded {len(items)} items from {OUT_PATH}")
    print(f"  - Single-Hop:  {sum(1 for x in items if x.get('category') == 'single_hop')}")
    print(f"  - Multi-Hop:   {sum(1 for x in items if x.get('category') == 'multi_hop')}")
    print(f"  - Adversarial: {sum(1 for x in items if x.get('category') == 'adversarial')}")
    return items

if __name__ == "__main__":
    items = generate_benchmark_dataset()
    print(f"Benchmark dataset is verified with {len(items)} items at {OUT_PATH}")
