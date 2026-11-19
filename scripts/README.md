# Scripts Inventory & Operational Utilities

This directory contains standalone operational scripts, benchmark runners, offline token generators, and data synchronization utilities for the SRMIST Campus Knowledge System.

---

## 1. Benchmarking & Evaluation

| Script | Purpose |
|---|---|
| `run_part_c_dev_benchmark.py` | Official development-set benchmark runner (80 legitimate + 10 adversarial queries). Computes tool accuracy, gold entity match, invalid query rate, latency distributions, and generates JSON audit reports. |
| `run_final_dual_benchmark.py` | Comparative benchmark runner for dual-mode evaluation (Hybrid Router vs. Router-Off LLM Intent). |
| `build_benchmark_dataset.py` | Generates the canonical development benchmark dataset (`campus_knowledge_server/eval/benchmark_dataset.json`). |
| `fix_benchmark_gold_labels.py` | Utility to normalize gold entity identifiers and acceptable aliases in benchmark definitions. |
| `inspect_gold_mismatches.py` | Diagnostics tool to inspect and categorize query prediction mismatches during evaluation. |
| `test_qwen_fast_eval.py` | Fast offline test harness for local Ollama Qwen 2.5 latency and function-calling verification. |

> **Note on Evaluation Protocols:**
> Never execute files in `benchmarktesting question/` (e.g., `independent_questions.json`, `independent_attacks.json`). All development benchmarks strictly evaluate against `campus_knowledge_server/eval/benchmark_dataset.json`.

---

## 2. Security, Authentication & Verification

| Script | Purpose |
|---|---|
| `make_demo_tokens.py` | Generates short-lived offline JWT tokens for `student`, `faculty`, and `admin` roles to inspect RBAC policies and audit logs. |
| `verify_full_system.py` | Automated end-to-end integration verifier testing FastAPI server health, SHA-256 audit ledger verification, and live agent query endpoints. |
| `verify_audit_part1.py` | Audits hash-chain continuity and cryptographic integrity of `audit_telemetry.jsonl`. |
| `verify_audit_part2_qwen_full.py` | Validates streaming and tool execution telemetry across multi-turn Qwen agent sessions. |
| `verify_faculty_chat_path.py` | Verifies faculty disambiguation, multi-faculty name splitting, and cabin location lookups. |

---

## 3. Data Extraction & Syllabus Processing

| Script | Purpose |
|---|---|
| `extract_syllabus_structured.py` | Extracts structured course attributes (L-T-P-C, prerequisites, descriptions) from official Regulations-2021 curriculum PDFs. |
| `extract_semantic_gold_sets.py` | Generates ground-truth semantic search relevance pairings from extracted course syllabi. |
| `inspect_course_descriptions.py` | Inspects extracted course catalog text for quality and completeness. |
| `merge_stub_programs.py` | Consolidates academic program identifiers across campus curricula. |
| `fix_two_bad_merges.py` | Corrects legacy curriculum merges for MBBS and specialized degree mappings. |

---

## 4. Graph Maintenance & Vector Indexes

| Script | Purpose |
|---|---|
| `update_buildings_and_embeddings.py` | Recomputes vector embeddings (`nomic-embed-text`) for buildings, courses, and programs when Neo4j is in read-write maintenance mode. |
| `update_courses_neo4j.py` | Synchronizes course syllabus properties and descriptions into Neo4j nodes. |
| `inspect_graph_faculty_cabins.py` | Verifies faculty cabin numbers and department links across the live graph. |
| `test_agent_buildings.py` | Tests building resolution and classroom timetable queries against live graph entities. |
| `test_building_search.py` | Validates fuzzy and vector-based building lookups. |
| `capture_part_b1_b2.py` | Captures intermediate data snapshots during multi-stage ingestion. |
