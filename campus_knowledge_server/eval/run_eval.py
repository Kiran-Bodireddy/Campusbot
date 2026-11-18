"""
Standard evaluation runner delegating to the 90-item comprehensive benchmark suite.
"""

from campus_knowledge_server.eval.eval_benchmark import run_benchmark

if __name__ == "__main__":
    run_benchmark(run_qwen_semantic_mode=False)
