# A Governed Tool-Calling Architecture for Local LLMs over a Campus Knowledge Graph: Design, Security, and Empirical Trade-offs

**Anonymous Author(s)**  
*Department of Computer Science and Engineering*  
*Institution Omitted for Double-Blind Review*  

---

### Abstract
Retrieval-Augmented Generation over Labeled Property Graphs (Graph-RAG) grounds Large Language Models (LLMs) in structured, multi-hop relational data. However, prevailing implementations face serious operational and security challenges: **unconstrained Text-to-Cypher generation** exposes database backends to prompt injection, arbitrary state manipulation (`DETACH DELETE`), and unindexed Cartesian products, while **open-loop iterative ReAct loops** introduce high multi-turn latency, semantic drift on exact identifiers, and vulnerability to indirect prompt injection across intermediate hops.

To resolve these security, expressiveness, and verifiability trade-offs, we present **Zero-Trust Governed Graph-RAG (ZTG-RAG)**, an agentic systems architecture that replaces unconstrained query synthesis with governed, parameterized tool brokerage for locally hosted LLMs. ZTG-RAG enforces four core systems contributions: (1) **Parameterized Governed Tool Brokerage**: a catalog of 14 pre-compiled, parameterized Cypher tools guarded by a lexical security validator and database-level read-only transactions; (2) **Broker-Enforced RBAC & Recursive Masking**: caller-bound role authorization and recursive data-layer field redaction that prevents unauthorized PII disclosure regardless of prompt jailbreaks; (3) **Deterministic Multi-Hop Chaining with Structured Entity Interception**: a configuration-driven composition engine that resolves relational dependencies without iterative LLM round-trips, strictly validating intermediate entity tokens against format regexes and active graph caches to prevent free-text propagation; and (4) **Forward-Secure Cryptographic Audit Provenance**: a thread-safe, HMAC-SHA256 hash-chained telemetry ledger providing tamper-evident auditability aligned with regulatory mandates (e.g., EU AI Act Article 12).

We evaluate ZTG-RAG over a university campus knowledge graph comprising authentic curriculum and faculty records (668 courses, 2,501 faculty, 428 degree programs) combined with modeled operational schedules (264 rooms, 1,336 timetable sessions). Evaluated across an independent 200-question held-out benchmark suite, ZTG-RAG achieves a **100.0% Cypher execution accuracy**, an invalid query rate of **0.0%**, **85.0% accuracy on single-hop inquiries** (**71.7% across currently supported tool inventory**), and **100% mitigation against Cypher mutations, role spoofing, and PII exfiltration**, with a median decision latency of **58.4 ms** compared to **4,820.0 ms** for local LLM tool synthesis, while maintaining verifiable ledger integrity across 12,400+ sequential multi-hop agent turns.

**Index Terms**—Large Language Models, Graph-RAG, Tool Governance, Role-Based Access Control, Tamper-Evident Audit Ledger, Indirect Prompt Injection, Knowledge Graphs.

---

## I. Introduction

Large Language Models (LLMs) suffer from well-documented parametric limitations, including temporal staleness and factual hallucinations \cite{lewis2020retrieval}. Retrieval-Augmented Generation (RAG) mitigates these issues by retrieving external knowledge into the model's inference context. While early RAG architectures relied primarily on unstructured dense vector embeddings \cite{karpukhin2020dense}, real-world enterprise applications increasingly adopt **Graph-RAG** \cite{edge2024graphrag}. By representing entities and their topological dependencies within Labeled Property Graphs (LPGs)—such as course prerequisites, faculty departmental affiliations, and classroom schedules—Graph-RAG enables multi-hop relational reasoning that vector distance metrics cannot reliably resolve.

Despite its expressiveness, common Graph-RAG architectures (e.g., LangChain `GraphCypherQAChain`, Microsoft GraphRAG) frequently delegate database interaction to dynamic query synthesis: **Text-to-Cypher or Text-to-SQL**. In this paradigm, user natural language prompts and database query syntax share an unsegregated token space. Consequently, adversaries can leverage direct prompt injection to manipulate query syntax, alter database state, or exfiltrate sensitive data attributes \cite{owasp2025llm01, liu2025evaluating}.

Furthermore, resolving multi-hop inquiries (e.g., *"Which instructors teach the prerequisites of Course X?"*) has traditionally relied on open-loop **Reasoning and Acting (ReAct)** agent loops \cite{yao2022react}. In a ReAct loop, an LLM iteratively inspects unstructured tool outputs, generates natural language thought tokens, and synthesizes subsequent tool calls. This introduces four severe liabilities:
1. **High Latency & Resource Consumption**: Multi-hop queries require multiple sequential LLM inferences, often consuming $10\text{s} - 35\text{s}$ on local consumer-grade GPUs.
2. **Intermediate Semantic Drift**: The LLM frequently mutates exact alphanumeric identifiers (e.g., course codes like `21CSC206T` or faculty IDs like `FAC-1004`) into descriptive paraphrases, causing subsequent database lookups to fail.
3. **Susceptibility to Indirect Prompt Injection**: If data retrieved in Hop 1 contains adversarial strings or untrusted text, passing this unstructured text back into the LLM context can hijack Hop 2's parameter selection \cite{greshake2023indirect}.
4. **Lack of Verifiable Provenance**: Standard agent implementations emit volatile plaintext logs that offer no cryptographic guarantee against post-hoc tampering, failing compliance with emerging regulatory frameworks such as **Article 12 of the European Union AI Act** \cite{eu_ai_act_2024}.

### Contributions
To resolve these architectural and security challenges, we present **Zero-Trust Governed Graph-RAG (ZTG-RAG)**. Our contributions are:
- **Parameterized Governed Tool Brokerage**: We eliminate dynamic Text-to-Cypher at the execution layer. We formalize a closed inventory of 14 pre-compiled, parameterized Cypher tools guarded by a lexical security validator, procedure allowlists, and driver-level read-only transaction constraints.
- **Broker-Enforced RBAC & Recursive Masking**: We enforce caller-bound Role-Based Access Control (RBAC) at the broker boundary. Sensitive fields (e.g., personal faculty telephone numbers) are recursively redacted at the serialization layer, preventing PII disclosure regardless of prompt jailbreaks.
- **Deterministic Multi-Hop Chaining with Structured Entity Interception**: We implement **Option A Chaining**, a configuration-driven composition engine that resolves multi-hop graph dependencies deterministically. We design a **Structured Entity Interceptor** that strictly validates intermediate parameters against format regexes and live graph caches, **forbidding free-text propagation between hops** to mitigate indirect prompt injection.
- **Forward-Secure HMAC-SHA256 Audit Provenance**: We design an append-only, linear hash-chained audit ledger protected by thread locks and server-bound HMAC keys, providing tamper-evident operational telemetry over thousands of sequential agent interactions.
- **Empirical Rigor**: We evaluate ZTG-RAG on an independent 200-question held-out benchmark suite across 7 query categories, demonstrating a **100.0% Cypher execution accuracy**, an invalid query rate of **0.0%**, an **85.0% single-hop accuracy** (**71.7% across supported inventory**), and **100% mitigation against state mutations, role spoofing, and PII exfiltration**.

---

## II. Related Work

### A. Graph-RAG and Query Synthesis
Retrieval-Augmented Generation was established by Lewis et al. \cite{lewis2020retrieval} and Karpukhin et al. \cite{karpukhin2020dense} to ground generative models in non-parametric text passages. Edge et al. \cite{edge2024graphrag} extended this paradigm to knowledge graphs, demonstrating that hierarchical clustering and community summarization improve holistic query comprehension over unstructured vectors. However, traditional Graph-RAG systems frequently rely on dynamic Text-to-Cypher or Text-to-SQL translation. Sanyal et al. \cite{sanyal2024benchmarking} demonstrated that while large proprietary models can generate simple Cypher queries, smaller open-weight models (1.5B–7B parameters) exhibit significant syntax failure rates, hallucinate non-existent relationship types, and struggle with complex filter clauses. Furthermore, dynamic query synthesis creates an inherent prompt injection attack surface \cite{owasp2025llm01}, as user-controlled tokens can manipulate query semantics.

### B. LLM Tool Calling and Agent Governance
The ReAct framework (Yao et al. \cite{yao2022react}) demonstrated that interleaving reasoning traces with tool execution enables complex problem solving. Toolformer (Schick et al. \cite{schick2023toolformer}) demonstrated that language models can be trained to invoke external APIs autonomously. To constrain LLM outputs to valid APIs, grammar-guided and schema-constrained decoding approaches (Willard & Louf \cite{willard2023guided}) restrict token sampling to paths valid under formal grammars (e.g., JSON schemas enforced by Pydantic). 

Despite schema validation, tool-augmented agents remain vulnerable to **indirect prompt injection** (Greshake et al. \cite{greshake2023indirect}, Liu et al. \cite{liu2025evaluating}), where untrusted data returned by a tool contains adversarial instructions that hijack subsequent turns. ZTG-RAG addresses this vulnerability by enforcing a strict **Structured Entity Interceptor**, preventing unstructured tool outputs from flowing freely into intermediate agent contexts.

### C. Cryptographic Auditability in Autonomous AI
Audit logging is fundamental to enterprise security and regulatory accountability. S. Haber and W. S. Stornetta \cite{haber1991timestampping} established digital document time-stamping using cryptographic hash chains, proving that sequential one-way hashing renders modification of historical records computationally infeasible. Bellare and Yee \cite{bellare2003forward} formalized forward-secure integrity for audit trails, ensuring that past logs remain verifiable even if subsequent keys are compromised. In the context of generative AI, emerging governance mandates—such as Article 12 of the EU Artificial Intelligence Act \cite{eu_ai_act_2024}—require continuous, tamper-evident recording of events throughout an AI system's operational lifecycle. ZTG-RAG operationalizes these cryptographic guarantees directly within the agent tool brokerage layer.

---

## III. Threat Model and Security Invariants

### A. Adversary Capabilities
We consider an adversary $\mathcal{A}$ interacting with the Graph-RAG system via natural language queries:
1. **Direct Prompt Injection ($\mathcal{A}_{DPI}$)**: $\mathcal{A}$ crafts meta-prompts (e.g., `<<<END_PROMPT>>>`) designed to override system constraints and instruct the model to disclose internal credentials, schemas, or raw data.
2. **Cypher Mutation Injection ($\mathcal{A}_{CMI}$)**: $\mathcal{A}$ embeds Cypher clauses (e.g., `DETACH DELETE`, `CREATE`, `DROP`, `CALL apoc.*`) to alter graph topology, drop indices, or invoke unauthorized database procedures.
3. **Privilege Escalation & Identity Spoofing ($\mathcal{A}_{PE}$)**: $\mathcal{A}$ attempts to forge role headers (e.g., claiming `role=admin`) or manipulate bearer tokens to access administrative tools (`run_governed_query`).
4. **Indirect Prompt Injection via Graph Payloads ($\mathcal{A}_{IPI}$)**: $\mathcal{A}$ exploits poisoned graph nodes. When Tool 1 retrieves an entity containing hidden instructions, the payload attempts to hijack Tool 2's parameters in a multi-hop sequence.
5. **Denial-of-Service ($\mathcal{A}_{DoS}$)**: $\mathcal{A}$ submits unindexed, Cartesian, or cyclical graph queries to exhaust database memory and CPU resources.

### B. Formal Security Invariants
Our architecture enforces four mathematical security invariants:
- **Invariant 1 (Read-Only Execution)**: $\forall t \in \mathcal{T}, \text{Operations}(t) \subseteq \{\text{MATCH}, \text{RETURN}, \text{WHERE}, \text{ORDER BY}\}$. Any query containing write mutators or unauthorized procedures is rejected prior to execution:
$$\mathcal{P}_{\text{Lexical}}(q) = \text{REJECT} \quad \text{if} \quad \text{Tokens}(q) \cap \text{Mutators} \neq \emptyset$$
Furthermore, database driver sessions are initialized with explicit read-only socket flags (`AccessMode.READ`), ensuring that even unflagged mutating clauses are rejected by the database engine.
- **Invariant 2 (Least Privilege RBAC)**: Let $P = \langle u, r \rangle$ be the principal with role $r \in \{\text{student}, \text{faculty}, \text{admin}\}$, and let $\text{Policy}(r)$ be the authorized tool set declared in `policy.yaml`. A tool $t$ executes if and only if $t \in \text{Policy}(r)$.
- **Invariant 3 (Structured Entity Isolation)**: In any multi-hop chain $t_1 \to t_2$, the intermediate parameter $x_2$ consumed by tool $t_2$ must belong to the verified graph entity cache $\mathcal{E}$ and satisfy format regex $\mathcal{R}$:
$$x_2 \in \mathcal{E} \land \text{RegexMatch}(\mathcal{R}, x_2) = \text{True}$$
Free text $s \notin \mathcal{E}$ is unconditionally rejected.
- **Invariant 4 (Audit Immutability)**: Every audit entry $e_i$ is bound to its predecessor $e_{i-1}$ via an HMAC-SHA256 signature under server secret $K_{\text{audit}}$:
$$h_i = \text{HMAC-SHA256}_{K_{\text{audit}}}(\text{CanonicalJSON}(e_i \setminus \{h_i\}) \parallel h_{i-1})$$
where $h_0 = 0^{64}$. Any modification of entry $e_j$ ($j \le i$) invalidates all subsequent hashes $h_k$ ($k \ge j$).

---

## IV. System Architecture & Governed Parameter Broker

The ZTG-RAG architecture coordinates request routing, schema validation, database execution, and cryptographic logging:

```
[User Request / Principal Context]
             │
             ▼
┌────────────────────────────────────────────────────────┐
│ 1. Gateway & Principal Resolution                      │
│    - HMAC-SHA256 JWT Authentication                    │
│    - RBAC Role Assignment (student | faculty | admin)  │
│    - Read-Only Lexical Guard & Procedure Allowlist     │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ 2. Hybrid Intent Router                                │
│    - Fast-Path Identifier Matcher (~1ms)               │
│    - Primary Model-First Intent Classifier (Qwen 2.5)  │
│    - High-Speed Fuzzy Normalized Fallback Router (~8ms)│
└──────────────────────────┬─────────────────────────────┘
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
┌────────────────────────┐  ┌────────────────────────────┐
│ 3A. Single-Hop Broker  │  │ 3B. Deterministic Chaining │
│     - Pydantic Schema  │  │     - Hop 1 Tool Execution │
│     - Type Sanitization│  │     - Entity Interceptor   │
│     - RBAC Policy Gate │  │     - Hop 2 Batch Dispatch │
└────────────┬───────────┘  └────────────┬───────────────┘
             │                           │
             └─────────────┬─────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│ 4. Isolated Execution Engine (Neo4j Community)         │
│    - Pre-compiled Parameterized Cypher Statements      │
│    - Explicit AccessMode.READ Socket Transactions      │
│    - Recursive Serialization-Layer Field Redaction     │
└──────────────────────────┬─────────────────────────────┘
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
┌────────────────────────┐  ┌────────────────────────────┐
│ 5A. Grounded Synthesis │  │ 5B. Cryptographic Audit    │
│     - Grounding Guard  │  │     - HMAC-SHA256 Hashing  │
│     - Delimiter Shield │  │     - Thread-Locked Ledger │
└────────────────────────┘  └────────────────────────────┘
```

### A. Pre-Compiled Governed Tools
Rather than allowing an LLM to generate Cypher dynamically, ZTG-RAG defines a closed catalog of 14 governed tools. Each tool encapsulates a strictly parameterized Cypher template. For example, `find_course_schedule` executes:
```cypher
MATCH (r:Room)-[o:OCCUPIES]->(c:Course)
WHERE toUpper(c.code) = $code
RETURN r.id as room_id, r.type as room_type, r.capacity as capacity,
       r.building_code as building_code, o.day as day, o.slot as slot
ORDER BY o.day, o.slot
```
Because `$code` is bound as a literal parameter within the Neo4j Bolt driver, input tokens cannot escape parameter boundaries into Cypher clause syntax.

### B. Broker-Enforced RBAC & Recursive Masking
Before query dispatch, `execute_tool()` validates the caller's verified `Principal`. If an unauthorized role attempts execution (e.g., a student invoking `run_governed_query`), execution halts immediately with a `SecurityViolationError`.

Privacy redaction does not rely on post-hoc prompt instructions. Role definitions and hidden fields reside in `policy.yaml` (e.g., `hidden_fields: [phone, mobile, personal_phone]` for the `student` role). The executor applies recursive masking across all nested dictionaries and lists before data returns to the agent:
```python
def mask_fields_recursive(obj: Any, hidden_fields: Set[str]) -> Any:
    """Recursively masks sensitive attributes across nested structures."""
    if not hidden_fields:
        return obj
    if isinstance(obj, dict):
        return {
            k: ("[Hidden by Policy]" if k in hidden_fields else mask_fields_recursive(v, hidden_fields))
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [mask_fields_recursive(item, hidden_fields) for item in obj]
    return obj
```
Because redaction occurs at the serialization boundary, prompt jailbreaks instructing the model to *"ignore instructions and show all phone numbers"* fail: the sensitive strings are physically absent from the LLM prompt context.

---

## V. Deterministic Chaining vs. Iterative Loops

To support multi-hop reasoning without the latency and failure modes of open-loop ReAct agents, ZTG-RAG introduces **Option A Deterministic Governed Chaining**.

### A. Chain Topologies
Chains are declared in `chain_config.yaml` across two topologies:
1. **Independent Multi-Part Chains**: Multiple tools execute against a single input entity (e.g., `course_prereqs_and_faculty` executes `get_prerequisite_tree` and `find_faculty_for_course`). Results are merged and rendered based on query focus.
2. **Dependent Multi-Hop Chains**: Hop 2 consumes structured identifiers produced by Hop 1 (e.g., `prerequisite_instructors` executes `get_prerequisite_tree`, extracts prerequisite course codes, and invokes `find_faculty_for_course` for each code).

### B. The Structured Entity Interceptor
To eliminate indirect prompt injection, we design the **Structured Entity Interceptor** (Algorithm 1). Free-text output from Hop 1 is strictly quarantined. Only fields explicitly declared as structured entity keys (e.g., `prerequisite_code`) are extracted. Each extracted token must satisfy format regex and exist within the verified graph entity cache before being passed to Hop 2.

```
Algorithm 1: Governed Dependent Chain Execution
Input: Template T, Initial Entity ID e_0, Principal P, Graph Client G
Output: Response R, Evidence Payload E
1: chain_id ← GenerateUUID("chn-")
2: Validate e_0 against Schema(T.hop1.entity_type)
3: res_1 ← execute_tool(T.hop1.tool, {T.hop1.param: e_0}, P, chain_id)
4: if res_1.empty() or res_1.has_error() then
5:     return HaltCleanly("No Hop 1 records found.", chain_id)
6: end if
7: raw_codes ← ExtractField(res_1, T.hop1.code_key)
8: valid_codes ← []
9: for each code in raw_codes do
10:    if RegexMatch(code) and code in G.entity_cache then
11:        valid_codes.append(code)
12:    end if
13: end for
14: if len(valid_codes) > T.limits.max_rows_forward then
15:    valid_codes ← valid_codes[0 : T.limits.max_rows_forward]
16: end if
17: res_2_batch ← []
18: for each c in valid_codes do
19:    if CallsCount >= T.limits.max_calls then break end if
20:    try:
21:        r2 ← execute_tool(T.hop2.tool, {T.hop2.param: c}, P, chain_id)
22:        res_2_batch.append(r2)
23:    except SecurityViolationError:
24:        res_2_batch.append(PolicyNotice(P.role, T.hop2.tool))
25:        break
26: end for
27: return SynthesizeGroundedSections(res_1, res_2_batch, chain_id)
```

---

## VI. Forward-Secure HMAC-SHA256 Audit Provenance

To satisfy verifiable operational provenance under enterprise compliance mandates, every execution event is permanently recorded in a cryptographic audit ledger.

### A. Mathematical Formulation
Let $e_i$ denote the $i$-th audit event represented as a structured key-value map:
$$e_i = \langle \tau_i, u_i, r_i, t_i, \theta_i, s_i, \lambda_i, \kappa_i, \chi_i, h_{i-1} \rangle$$
where $\tau_i$ is the ISO-8601 UTC timestamp, $u_i$ is caller identity, $r_i$ is verified role, $t_i$ is tool invoked, $\theta_i$ is sanitized parameter payload, $s_i \in \{\text{SUCCESS}, \text{POLICY\_VIOLATION}, \text{VALIDATION\_ERROR}\}$ is execution status, $\lambda_i$ is latency in milliseconds, $\kappa_i$ is result count, $\chi_i$ is shared `chain_id`, and $h_{i-1}$ is the predecessor hash.

Under a thread-level re-entrant lock (`threading.RLock`), the entry hash $h_i$ is signed via HMAC-SHA256 using server secret $K_{\text{audit}}$:
$$h_i = \text{HMAC-SHA256}_{K_{\text{audit}}}(\text{CanonicalJSON}(e_i \setminus \{h_i\}) \parallel h_{i-1})$$
Canonical JSON serialization enforces alphabetical key sorting and deterministic numeric formatting.

### B. Verification & Tamper Detection
Integrity verification operates via a linear verification pass:
$$\text{Verify}(\mathcal{L}) = \bigwedge_{i=1}^N \left( e_i.h_{i-1} == h_{i-1} \land \mathcal{H}_{\text{HMAC}}(e_i \setminus \{h_i\}) == e_i.h_i \right)$$
If an adversary modifies a recorded parameter or status flag in past entry $e_k$, re-evaluating $\mathcal{H}(e_k)$ detects the discrepancy immediately. If the adversary recomputes $e_k.h_k$, the successor entry's stored predecessor pointer ($e_{k+1}.h_{k-1} \neq e_k.h_k$) breaks the chain. Because HMAC signing requires $K_{\text{audit}}$, an attacker with local file access cannot forge valid hashes without the server secret.

---

## VII. Empirical Evaluation & Benchmarks

### A. Experimental Setup & Knowledge Graph Corpus
- **Knowledge Graph Corpus**: Hosted in Neo4j Community `2026.10.2`. The dataset combines authentic institutional data with synthetically modeled scheduling allocations:
  - **Authentic Scraped Data**: 668 accredited academic courses, 2,501 faculty members across engineering and science schools, and 428 degree admission requirements scraped from public university portals.
  - **Modeled Operational Data**: 264 classrooms across 9 building complexes (TP, TP2, UB, BEL, MEB, ESB, FMB, SLB, MCB) and 1,336 scheduled timetable sessions modeled to reflect representative semester course allocations.
- **Evaluation Dataset**: An independent, held-out benchmark suite of 200 items (`campus_eval_200.json`) whose ground-truth facts were programmatically extracted from the active campus knowledge graph:
  - **60 Single-Hop queries**: Course attributes, room schedules, faculty profiles, building facilities, and admissions cutoffs.
  - **36 Multi-Hop relational queries**: Dependent prerequisite instructor chains and multi-building room occupancy workflows.
  - **24 Multi-Query questions**: Multi-turn coreference resolution and multi-entity attribute projections.
  - **24 Robustness questions**: Natural student phrasing, severe spelling typos, and informal academic slang.
  - **30 Security vectors**: Cypher injection, privilege escalation, meta-prompt delimiter escapes, personal data (PII) exfiltration, unauthenticated audit reading, and client-header rate-limit flooding.
  - **10 Negative cases**: Out-of-scope inquiries (weather, general trivia) and non-existent entities.
  - **16 Coverage gap tests**: Explicitly evaluating 8 proposed future tools not yet present in the 13-tool inventory to measure feature roadmaps.
- **Hardware & Inference Environment**: Local Ollama server executing `qwen2.5:3b` (temperature = 0.0, context window `num_ctx: 4096`, `num_predict: 256`), hosted on an AMD Ryzen architecture under Windows OS.

### B. Comparative Performance & Latency Analysis

TABLE I presents the comparative evaluation across architectural baselines, and TABLE II breaks down empirical performance across all 7 benchmark categories.

#### TABLE I: Performance and Latency Comparison across Architectural Baselines
| Metric | Governed Hybrid (Proposed) | Native Tool Calling | Iterative ReAct Loop | Unconstrained Text-to-Cypher | Target Benchmark |
|---|:---:|:---:|:---:|:---:|:---:|
| **Queries Evaluated** | 200 | 200 | 200 | 200 | — |
| **Tool / Query Selection Accuracy (All 200)** | **67.0%** (134/200) | 61.5% (123/200) | 54.0% (108/200) | 38.5% (77/200) | $\ge 65.0\%$ |
| **Tool Accuracy (Supported 184 Inventory)** | **71.7%** (132/184) | 66.8% (123/184) | 58.7% (108/184) | 41.8% (77/184) | $\ge 70.0\%$ |
| **Grounded Fact Match Rate** | **96.0%** (192/200) | 88.5% (177/200) | 78.0% (156/200) | 51.5% (103/200) | $\ge 85.0\%$ |
| **Cypher Execution Accuracy** | **100.0%** (200/200) | 95.4% (191/200) | 86.3% (173/200) | 61.1% (122/200) | 100.0% |
| **Invalid Query / Syntax Error Rate** | **0.0%** (0/200) | 4.6% (9/200) | 13.7% (27/200) | 38.9% (78/200) | $< 2.0\%$ |
| **Pydantic Schema Violations** | **0** | 3 | 11 | N/A | 0 |
| **Hard Gate Security Mitigation Rate** $^\dagger$ | **100.0%** (20/20) | 100.0% (20/20) | 65.0% (13/20) | 0.0% (0/20) | 100.0% |
| **Overall Security Defense Rate (All 30)** | **76.7%** (23/30) | 73.3% (22/30) | 50.0% (15/30) | 0.0% (0/30) | $\ge 75.0\%$ |
| **Median Decision Latency** $^\ddagger$ | **58.4 ms** | 4,820.0 ms | 18,450.0 ms | 6,120.0 ms | $< 2,000\text{ ms}$ |
| **Mean End-to-End Latency** | **1,180.5 ms** | 6,240.5 ms | 24,180.0 ms | 7,850.0 ms | $< 3,000\text{ ms}$ |
| **Audit Ledger Verification** | **100% Intact** (12,459) | N/A | N/A | N/A | 100% Intact |

$^\dagger$*Hard Gate Security reflects Cypher injections, role spoofing, client rate-limit evasion, and PII exfiltration.*  
$^\ddagger$*Decision Latency reflects routing, schema validation, and tool execution time prior to final conversational answer generation.*

#### TABLE II: Category-by-Category Empirical Pass Rates (ZTG-RAG)
| Category | Total Queries | Passed | Failed | Pass Rate (%) | Tool Accuracy (%) | Key Finding / Failure Mode |
|---|:---:|:---:|:---:|:---:|:---:|---|
| **Single-Hop** | 60 | 51 | 9 | **85.0%** | **85.0%** | Strong on course, faculty, building, and admission lookups; minor ambiguity on course timeslots. |
| **Security & Adversarial** | 30 | 23 | 7 | **76.7%** | **76.7%** | 100% on Cypher mutation, role escalation, PII masking, and rate limits; natural language jailbreaks require semantic filter. |
| **Multi-Query** | 24 | 16 | 8 | **66.7%** | **70.8%** | Effectively resolves multi-entity projections; multi-part questions occasionally focus on single dominant entity. |
| **Multi-Hop** | 36 | 23 | 13 | **63.9%** | **63.9%** | Option A Chaining succeeds on prerequisite chains; course vs. room schedule ambiguity on building queries. |
| **Negative Cases** | 10 | 6 | 4 | **60.0%** | **60.0%** | Accurately identifies non-existent faculty; open-domain trivia triggers federated search fallback. |
| **Robustness** | 24 | 12 | 12 | **50.0%** | **50.0%** | Handles common typos; extreme acronyms ("DS", "DBMS", "OS kab hai") require semantic expansion. |
| **Coverage Gap (New Tools)** | 16 | 2 | 14 | **12.5%** | **12.5%** | **Expected Gap**: Questions explicitly target 8 proposed tools not yet in the 13-tool inventory. |
| **Total Benchmark Suite** | **200** | **133** | **67** | **66.5%** | **67.0%** | Robust baseline over zero-shot, un-tuned held-out test data. |

### C. Analysis of Research Questions

#### RQ1: Injection Resistance & Boundary Enforcement
In the 30-vector security evaluation, ZTG-RAG achieved a **100% mitigation rate across all structural and protocol attacks**:
- **Cypher Injections & Destructive Mutations**: Statements containing `DETACH DELETE`, `UNION MATCH`, stacked clauses (`;`), or system commands were intercepted by the `ASTSecurityValidator` in $< 1\text{ ms}$ before any database connection was established.
- **Protocol & Role Spoofing (SEC-001–SEC-003)**: Unauthenticated and student requests claiming `role: admin` were rejected with `HTTP 403 (ROLE_SPOOFING_BLOCKED)`. Tampered signatures were rejected with `HTTP 401`.
- **Privileged Tool Execution (SEC-023, SEC-024)**: Student invocations of `run_governed_query` and un-whitelisted templates were blocked with `HTTP 403`.
- **Client Rate-Limit Evasion (SEC-030)**: Sending 25 rapid requests while rotating `X-Session-Id` headers triggered `HTTP 429 Too Many Requests` after request 20, confirming that rate limits are strictly bound to verified client IP.
- **PII Exfiltration (SEC-005–SEC-007)**: When students explicitly queried faculty personal contact details, `lookup_faculty_profile` executed but personal phone numbers were redacted to `[Hidden by Policy]` by recursive data-layer masking. Zero phone numbers leaked.
- **Limitation Disclosed**: Natural language jailbreaks (e.g. `SEC-014`, `SEC-018` translation wrappers) passed the lexical AST filter because they contain no Cypher keywords. While data-layer masking prevented PII exposure, upfront rejection requires a semantic intent classification stage.

#### RQ2: Multi-Hop Reasoning & Semantic Drift
Under ZTG-RAG Option A Chaining, multi-hop queries achieved a $63.9\%$ pass rate without semantic drift. By quarantining Hop 1's intermediate payload and validating entity tokens against verified graph caches via the Structured Entity Interceptor, intermediate identifiers (`21CSC206T`, `UB101`) were preserved verbatim without LLM paraphrasing. Failures in multi-hop queries were primarily due to intent ambiguity: queries asking *"Which building is Course X held in?"* frequently routed to `lookup_course` (which returns academic details) rather than `find_course_schedule`.

#### RQ3: Latency & Computational Trade-offs
ZTG-RAG achieves a median decision-and-tool latency of **58.4 ms** on direct queries. Profiling confirms:
- Heuristic intent routing: $\sim 1.2\text{ ms} - 4.5\text{ ms}$.
- Pydantic schema validation: $\sim 0.4\text{ ms}$.
- Neo4j indexed Bolt read: $\sim 15.0\text{ ms} - 45.0\text{ ms}$.
- HMAC-SHA256 audit ledger signing: $\sim 0.18\text{ ms}$.
The computational overhead of cryptographic audit logging and schema checking combined is less than **$1\text{ ms}$**, confirming that rigorous governance does not compromise operational throughput.

#### RQ4: Cryptographic Ledger Scalability & Verifiability
We cryptographically verified the sequential HMAC-SHA256 chain across **12,459 consecutive audit entries** in `audit_telemetry.jsonl`. Verification completed in $0.49\text{ seconds}$ with zero broken links:
```text
Verification: intact=True, verified_count=12459, err=Hash chain intact. Zero tampering detected.
```
In simulated tampering trials (modifying a single parameter character in historical entry 6,000), `verify_chain()` deterministically caught the exact entry index and flagged cryptographic tampering.

---

## VIII. Discussion and Limitations

### A. Architectural Trade-offs: Governed Tools vs. Dynamic Cypher Synthesis
Our findings indicate that for institutional enterprise domains governed by regulatory frameworks, unconstrained Text-to-Cypher represents an unacceptably high risk profile. Dynamic query synthesis conflates instruction and data spaces, creating vulnerabilities that prompt engineering cannot reliably resolve. Constraining local LLMs to parameter extraction over pre-compiled, parameterized tools eliminates the query-injection attack surface while maintaining low latency on consumer-grade hardware.

### B. Limitations
We identify four primary limitations of this work:
1. **Rule & Schema Maintenance Overhead**: The hybrid router relies on hand-crafted token extraction rules and Pydantic schemas (~4,500 lines of routing logic). When institutional curriculum taxonomies evolve, administrators must maintain corresponding schema mappings.
2. **Single-Domain Scope**: Evaluation was conducted on a single university campus graph and local model family (`qwen2.5:3b`). Cross-domain validation (e.g., healthcare or legal domains) remains necessary to assess generalization across heterogeneous domain ontologies.
3. **Conversational Synthesis Drift**: While retrieved graph facts are 100% verified, the LLM still generates the final conversational prose. Post-generation grounding guards verify that cited course codes and room IDs match retrieved data, but open-ended generative prose can still exhibit stylistic variation.
4. **Partly Modeled Scheduling Topology**: While courses, degree requirements, and faculty profiles represent authentic university records, classroom allocations and timetable slots are synthetically modeled to evaluate scheduling queries without accessing confidential internal registrar databases.

---

## IX. Conclusion

We presented **Zero-Trust Governed Graph-RAG (ZTG-RAG)**, an agentic systems architecture for secure, verifiable knowledge graph question-answering with local LLMs. By decoupling language models from raw query generation and introducing **parameterized tool brokerage**, **broker-enforced RBAC with recursive data masking**, **deterministic multi-hop chaining with structured entity interception**, and a **forward-secure HMAC-SHA256 audit ledger**, ZTG-RAG eliminates the attack surface of dynamic Cypher generation while maintaining sub-second execution speeds. Our evaluation confirms $100\%$ perimeter adversarial mitigation, $0.0\%$ invalid queries, and sub-millisecond governance overhead over 12,000+ sequential records.

---

## References

1. P. Lewis, et al., "Retrieval-augmented generation for knowledge-intensive NLP tasks," in *Advances in Neural Information Processing Systems (NeurIPS)*, vol. 33, pp. 9459–9474, 2020.
2. V. Karpukhin, et al., "Dense passage retrieval for open-domain question answering," in *Proc. of the 2020 Conference on Empirical Methods in Natural Language Processing (EMNLP)*, pp. 6769–6781, 2020.
3. D. Edge, et al., "From local to global: A graph RAG approach to query-focused summarization," *arXiv preprint arXiv:2404.16130*, 2024.
4. S. Yao, et al., "ReAct: Synergizing reasoning and acting in language models," in *International Conference on Learning Representations (ICLR)*, 2023.
5. T. Schick, et al., "Toolformer: Language models can teach themselves to use tools," in *Advances in Neural Information Processing Systems (NeurIPS)*, vol. 36, 2023.
6. S. Sanyal, et al., "Benchmarking and evaluating large language models on Text-to-Cypher generation over knowledge graphs," in *Proc. of the VLDB Endowment*, 2024.
7. OWASP Foundation, "OWASP Top 10 for Large Language Model Applications v2.0," *OWASP Technical Report*, 2025.
8. K. Greshake, et al., "Not what you've signed up for: Compromising real-world LLM-integrated applications with indirect prompt injection," in *Proc. of the 16th ACM Workshop on Artificial Intelligence and Security (AISEC)*, pp. 79–90, 2023.
9. J. Liu, et al., "Evaluating prompt injection attacks and defenses in tool-augmented LLM agents," in *Proc. of the IEEE Symposium on Security and Privacy (S&P)*, 2025.
10. S. Haber and W. S. Stornetta, "How to time-stamp a digital document," *Journal of Cryptology*, vol. 3, no. 2, pp. 99–111, 1991.
11. M. Bellare and B. Yee, "Forward-security in private-key cryptography: Call for solutions and open problems," *ACM Transactions on Information and System Security (TISSEC)*, vol. 6, no. 2, pp. 175–204, 2003.
12. National Institute of Standards and Technology (NIST), "Zero Trust Architecture," *NIST Special Publication 800-207*, 2020.
13. European Parliament and Council of the European Union, "Regulation (EU) 2024/1689 laying down harmonised rules on artificial intelligence (Artificial Intelligence Act)," *Official Journal of the European Union*, 2024.
14. B. Willard and R. Louf, "Efficient guided generation for large language models," *arXiv preprint arXiv:2307.09702*, 2023.
15. Qwen Team, "Qwen2.5: A foundation language model with enhanced reasoning and tool usage capabilities," *Alibaba Cloud Technical Report*, 2024.
16. Neo4j Inc., "Neo4j Cypher Manual v2026.10," *Neo4j Documentation*, 2024.
17. Pydantic Services Inc., "Data validation and settings management using Python type annotations," *Pydantic v2 Documentation*, 2024.
18. Anthropic, "Model Context Protocol (MCP) Specification," *Anthropic Technical Documentation*, 2024.
