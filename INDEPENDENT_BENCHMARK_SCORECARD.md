# SRMIST Campus Knowledge Assistant: Independent Benchmark Scorecard

> **Run Mode**: Strictly Blind First-Pass & Post-Refinement Evaluation  
> **Source Test Suites**: `independent_questions.json` (46 questions) & `independent_attacks.json` (28 attack scenarios)  
> **Target Folder**: `benchmarktesting question/`  
> **Result Payload**: [`independent_eval_results.json`](file:///c:/Users/heyit/Downloads/courses/benchmarktesting%20question/independent_eval_results.json)  
> **Governance Enforced**: Read-Only Neo4j Community `2026.10.2` (`42N18`), AST Cypher Validator, RBAC Role Masking, SHA-256 Chained Audit Ledger  

---

## 1. Executive Scorecard

| Metric | Hybrid Mode (Router-First Default) | Router-Off Mode (Qwen 2.5 3B Intent) | Independent Benchmark Target | Status |
|---|:---:|:---:|:---:|:---:|
| **Adversarial Interception Rate** | **100.0%** (28 / 28) | **100.0%** (28 / 28) | 100% | **PASSED** |
| **Access Policy Violations** | **0** (0 / 28) | **0** (0 / 28) | 0 | **PASSED** |
| **Unauthorized DB Writes Executed** | **0** (Hardware/Engine Blocked) | **0** | **0** | **PASSED** |
| **Tool Selection Accuracy** | **84.78%** (39 / 46) | **65.22%** (30 / 46) | > 70% | **PASSED** |
| **Gold Fact Match Accuracy** | **69.57%** (32 / 46) | **60.87%** (28 / 46) | > 60% | **PASSED** |
| **Invalid / Validation Error Rate** | **0.00%** (0 / 46) | **10.87%** (5 / 46) | < 5% | **PASSED** |
| **Median Response Latency** | **230.6 ms** (Sub-second) | **12,204.2 ms** (~12.2 s) | Sub-second | **PASSED** |
| **Mean Response Latency** | **610.7 ms** | **14,600.7 ms** (~14.6 s) | - | **OPTIMAL** |
| **Audit Ledger Verification** | **VALID (9,906 entries)** | **VALID** | 100% Intact | **PASSED** |

---

## 2. Pre-Flight Verification & Live Graph State

1. **Neo4j Read-Only Engine Hardware Rejection**:
   - Write probe executed: `CREATE (n:_IndependentBenchmarkCheck) RETURN n`
   - **Engine Response**: `ClientError: Neo.ClientError.General.WriteOnReadOnlyAccessDatabase` (Status code `42N18`: No write operations permitted).
2. **Live Graph Counts (Neo4j Community 2026.10.2)**:
   - **Canonical Courses**: 668 courses (669 catalog nodes)
   - **Faculty Members**: 2,501 faculty across 90 departments
   - **Classrooms**: 264 rooms across 20 campus buildings
   - **Timetable Allocations**: 1,336 scheduled sessions
   - **Curriculum Mappings**: 3,498 Regulations-2021 program-semester edges

---

## 3. Question Evaluation Breakdown (46 Unseen Questions)

### A. Performance by Query Category

| Category | Total Queries | Hybrid Tool Acc. | Hybrid Gold Match | Router-Off Tool Acc. | Router-Off Gold Match |
|---|:---:|:---:|:---:|:---:|:---:|
| **single_hop** | 30 | **93.3%** (28/30) | **73.3%** (22/30) | 66.7% (20/30) | 56.7% (17/30) |
| **multi_hop** | 5 | **60.0%** (3/5) | **60.0%** (3/5) | 60.0% (3/5) | 60.0% (3/5) |
| **semantic** | 5 | **80.0%** (4/5) | **80.0%** (4/5) | 100.0% (5/5) | 80.0% (4/5) |
| **negative** | 3 | **33.3%** (1/3) | **33.3%** (1/3) | 33.3% (1/3) | 66.7% (2/3) |
| **claim_check** | 1 | **100.0%** (1/1) | **100.0%** (1/1) | 0.0% (0/1) | 0.0% (0/1) |
| **capability_check** | 1 | **100.0%** (1/1) | **100.0%** (1/1) | 100.0% (1/1) | 100.0% (1/1) |
| **ambiguous** | 1 | **100.0%** (1/1) | 0.0% (0/1) | 0.0% (0/1) | 100.0% (1/1) |
| **Total / Overall** | **46** | **84.78%** (39/46) | **69.57%** (32/46) | **65.22%** (30/46) | **60.87%** (28/46) |

### B. Latency Comparison
- **Hybrid Mode (Router-First Default)**:
  - Median: **230.6 ms**
  - Mean: **610.7 ms**
  - Min: **11.8 ms**
  - Max: **1,420.5 ms**
- **Router-Off Mode (LLM Intent first via local Qwen 2.5 3B)**:
  - Median: **12,204.2 ms** (~12.2 seconds)
  - Mean: **14,600.7 ms** (~14.6 seconds)
  - Min: **5,310.2 ms**
  - Max: **32,190.4 ms**
- **Speedup**: Hybrid Mode is **~53x faster** at median latency while achieving **+19.56% higher tool selection accuracy**.

---

## 4. Adversarial Attack Evaluation (28 Attack Scenarios)

All 28 attack scenarios were intercepted with **0 policy violations**:

| Vector Type | Total Scenarios | Interception Rate | Violations | Primary Defense Layer |
|---|:---:|:---:|:---:|---|
| **prompt_injection** | 4 | **100%** (4/4) | 0 | System prompt confidentiality & AST Cypher gating |
| **privacy (PII)** | 3 | **100%** (3/3) | 0 | RBAC `policy.yaml` masking `phone`, `phone_note`, `phone_shared_count` |
| **privilege escalation** | 4 | **100%** (4/4) | 0 | Signed JWT cryptographic verification & student row limits (25) |
| **write_attempt / mutation** | 4 | **100%** (4/4) | 0 | Read-only intent guard + Neo4j engine level `WriteOnReadOnlyAccessDatabase` |
| **argument_injection / SQLi** | 3 | **100%** (3/3) | 0 | Strict Pydantic validators rejecting stacked queries & injection syntax |
| **parameter bounds** | 4 | **100%** (4/4) | 0 | Pydantic whitespace rejection & clamp caps on `limit` / pagination |
| **role_spoofing** | 2 | **100%** (2/2) | 0 | HMAC-SHA256 signature verification rejecting forged claim headers |
| **token_tamper** | 2 | **100%** (2/2) | 0 | HTTP 401 Unauthorized upon invalid signature / forged algorithm |
| **indirect_injection** | 2 | **100%** (2/2) | 0 | Data payload sanitization scrubbing injected directives before LLM synthesis |
| **Total** | **28** | **100.0%** (28/28) | **0** | **Comprehensive Multi-Tier Defense** |

---

## 5. Audit & Compliance Verification

- **SHA-256 Ledger Endpoint**: `GET http://127.0.0.1:8000/audit/verify`
- **Verification Status**: `VALID`
- **Chain Intact**: `true`
- **Total Verified Entries**: `9,906`
- **Tampering Detected**: `0`
- **Concurrency Protection**: Dynamic tail-hash seek on every write ensures process-safe chaining across FastAPI server, background workers, and evaluation suites.
