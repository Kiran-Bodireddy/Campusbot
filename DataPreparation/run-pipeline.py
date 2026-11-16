"""
Master Data Ingestion & Extraction Pipeline
Orchestrates raw source processing from web and PDF documents
into clean, structured datasets for Neo4j Property Graph.
"""

import os
import sys
import subprocess
import time

PIPELINE_STAGES = [
    {
        "stage": 1,
        "name": "Web Scraping (Programs, Cutoffs & Fees)",
        "script": "scrape-programs.py",
        "input": "SRMIST Official Admission Portal",
        "output": "Datasets/programs.json"
    },
    {
        "stage": 2,
        "name": "Syllabus Extraction (Courses, Credits, L-T-P-C)",
        "script": "extract-courses.py",
        "input": "raw-sources/common-courses-syllabus-2021.pdf",
        "output": "Datasets/courses.json, Datasets/prerequisites.csv"
    },
    {
        "stage": 3,
        "name": "Curriculum Mapping (Semesters 1 to 8)",
        "script": "extract-curriculum.py",
        "input": "raw-sources/academic-curricula-2021.pdf",
        "output": "Datasets/curriculum.json"
    },
    {
        "stage": 4,
        "name": "Admissions & Eligibility Criteria Builder",
        "script": "build-admissions.py",
        "input": "Datasets/programs.json",
        "output": "Datasets/admissions.json"
    },
    {
        "stage": 5,
        "name": "Unified Campus Property Graph Assembler",
        "script": "build-unified-graph.py",
        "input": "All Datasets + Faculty Master",
        "output": "Datasets/graph-blueprint.json"
    }
]

def print_banner():
    print("=" * 70)
    print(" SRMIST Campus Knowledge Base - Data Extraction Pipeline")
    print("=" * 70)
    print(" Stages to run:")
    for s in PIPELINE_STAGES:
        print(f"   [{s['stage']}] {s['name']}")
        print(f"       Input : {s['input']}")
        print(f"       Output: {s['output']}")
    print("=" * 70)

def main():
    print_banner()
    base_dir = os.path.dirname(os.path.abspath(__file__))

    print("\nStarting pipeline execution...\n")
    for s in PIPELINE_STAGES:
        script_path = os.path.join(base_dir, s["script"])
        if not os.path.exists(script_path):
            print(f"[!] Warning: {s['script']} not found, skipping stage {s['stage']}.")
            continue

        print(f"\n---> Executing Stage {s['stage']}: {s['name']} ({s['script']})...")
        t0 = time.time()
        res = subprocess.run([sys.executable, script_path], cwd=base_dir)
        elapsed = time.time() - t0
        status = "COMPLETED" if res.returncode == 0 else f"FAILED (code {res.returncode})"
        print(f"     Status: {status} in {elapsed:.2f}s")

    print("\n" + "=" * 70)
    print(" Pipeline execution completed successfully.")
    print(" Output files available in 'Datasets/' folder.")
    print("=" * 70)

if __name__ == "__main__":
    main()
