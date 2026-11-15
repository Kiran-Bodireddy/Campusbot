# Complete SRMIST Campus Knowledge Tool Server Architecture

This document contains the complete system architecture diagram ready to paste into **Excalidraw** or **Mermaid Live**.

---

## 1. Complete Architecture Diagram (Mermaid Code)

```mermaid
flowchart TD
    %% ------------------------------------------------------------------------
    %% 1. CLIENT & INTERACTION LAYER
    %% ------------------------------------------------------------------------
    subgraph TIER1 ["1. Client & Interface Layer"]
        UI["Web Portal UI\n(campus_assistant.html)"]
        CLI["Interactive CLI Console\n(show_dataset.py)"]
        API_CLIENT["REST & MCP Clients\n(External HTTP / JSON-RPC)"]
    end

    %% ------------------------------------------------------------------------
    %% 2. GATEWAY & GOVERNANCE LAYER
    %% ------------------------------------------------------------------------
    subgraph TIER2 ["2. Security Gateway & AST Boundary"]
        ROUTER["High-Speed Intent Router\n(Fast-Path Regex & Normalizer)"]
        AST_GUARD["AST Security Validator\n(Read-Only AST Sanitizer)"]
        RBAC["Role-Based Access Control\n(policy.yaml: Student / Faculty / Admin)"]
        MASKING["Field Masking & Row Limiter\n(Privacy & Output Scoping)"]
    end

    %% ------------------------------------------------------------------------
    %% 3. TOOL SERVER & ORCHESTRATION LAYER
    %% ------------------------------------------------------------------------
    subgraph TIER3 ["3. Governed Tool Server (FastAPI)"]
        AGENT["Governed Campus Agent\n(qwen_agent.py)"]
        
        subgraph TOOLS ["Governed Tool Registry"]
            T_CURR["get_semester_curriculum\n(3,498 Allocations)"]
            T_CRS["lookup_course\n(668 Accredited Courses)"]
            T_PREREQ["get_prerequisite_tree\n& verify_prerequisites"]
            T_ADM["check_admission_eligibility\n(430 Degree Programs)"]
            T_FAC["lookup_faculty_profile\n(2,501 Directory Records)"]
            T_ROOM["find_available_rooms\n& find_room_schedule"]
            T_STAT["get_campus_statistics\n(Unified Graph Aggregates)"]
        end
    end

    %% ------------------------------------------------------------------------
    %% 4. SYNTHESIS ENGINE
    %% ------------------------------------------------------------------------
    subgraph TIER4 ["4. Grounded Synthesis Engine"]
        LLM["Local Qwen 2.5 7B\n(Ollama - 100% Offline)"]
        DETERM["Deterministic Governed Synthesizer\n(Zero-Hallucination Fallback)"]
        CIT_GUARD["Citation Guardrail\n(Strict Database Grounding)"]
    end

    %% ------------------------------------------------------------------------
    %% 5. DATABASE & KNOWLEDGE GRAPH LAYER
    %% ------------------------------------------------------------------------
    subgraph TIER5 ["5. Neo4j Property Graph Database (Port 7687)"]
        NEO4J[("Neo4j Community DBMS\n(SRMIST Campus Graph)")]
        
        subgraph GRAPH_SCHEMA ["Property Graph Model"]
            N_PROG["Program Node\n(430 Programs)"]
            N_COURSE["Course Node\n(668 Courses)"]
            N_FAC["Faculty Node\n(500 Members)"]
            N_ROOM["Classroom Node\n(264 Rooms)"]
            
            E_OFFERS["OFFERS_IN_SEMESTER\n(3,498 Edges)"]
            E_REQ["REQUIRES_PREREQUISITE\n(Directed Acyclic Graph)"]
            E_TEACH["TEACHES\n(Faculty to Program)"]
            E_ASSIGN["ASSIGNED_TO\n(Schedule to Room)"]
        end
        
        CACHE[("Governed In-Memory Cache\n(Zero-Downtime Mirror)")]
    end

    %% ------------------------------------------------------------------------
    %% 6. OBSERVABILITY & AUDIT LEDGER
    %% ------------------------------------------------------------------------
    subgraph TIER6 ["6. Cryptographic Observability Ledger"]
        LEDGER[("Append-Only JSONL Ledger\naudit_telemetry.jsonl")]
        HASH_CHAIN["SHA-256 Hash Chaining\n(Tamper-Evident Ledger)"]
        AUDIT_API["Verification Engine\n(/audit/verify & /audit/logs)"]
        DASHBOARD["Live Architecture Telemetry Dashboard\n(Sub-5ms Graph Monitor)"]
    end

    %% ------------------------------------------------------------------------
    %% EXECUTION FLOW
    %% ------------------------------------------------------------------------
    UI -->|"1. Query"| ROUTER
    CLI -->|"1. Query"| ROUTER
    API_CLIENT -->|"1. Query"| ROUTER

    ROUTER -->|"2. Normalized Entity"| AST_GUARD
    AST_GUARD -->|"3. Whitelist Check"| RBAC
    RBAC -->|"4. Authorized Call"| AGENT

    AGENT -->|"5. Dispatches Tool"| TOOLS
    
    T_CURR -->|"Cypher Traversal"| NEO4J
    T_CRS -->|"Cypher Traversal"| NEO4J
    T_PREREQ -->|"Cypher Traversal"| NEO4J
    T_ADM -->|"Cypher Traversal"| NEO4J
    T_FAC -->|"Cypher Traversal"| NEO4J
    T_ROOM -->|"Cypher Traversal"| NEO4J
    T_STAT -->|"Cypher Traversal"| NEO4J
    
    NEO4J -.->|"Mirror Sync"| CACHE

    NEO4J -->|"6. Verified Records"| MASKING
    MASKING -->|"7. Masked Records"| CIT_GUARD
    
    CIT_GUARD -->|"8. Grounded Context"| LLM
    CIT_GUARD -->|"8. Deterministic Context"| DETERM
    
    LLM -->|"9. Grounded Answer"| UI
    DETERM -->|"9. Grounded Answer"| UI

    AGENT -->|"Log Invocation"| LEDGER
    LEDGER -->|"Compute Hash"| HASH_CHAIN
    HASH_CHAIN -->|"Verify Chain"| AUDIT_API
    AUDIT_API -->|"Live Metrics"| DASHBOARD
```

