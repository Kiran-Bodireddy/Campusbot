"""
Cypher AST & Query Security Validator
Implements zero-trust access control, rejecting write clauses,
APOC system procedures, administrative commands, and malicious injections.
Automatically injects bounds (LIMIT 50) on unconstrained queries.
"""

import re
from typing import Tuple, Optional

# Forbidden destructive, modification, and admin keywords (case-insensitive)
FORBIDDEN_KEYWORDS = [
    r"\bCREATE\b",
    r"\bMERGE\b",
    r"\bDELETE\b",
    r"\bDETACH\b",
    r"\bSET\b",
    r"\bREMOVE\b",
    r"\bDROP\b",
    r"\bALTER\b",
    r"\bGRANT\b",
    r"\bREVOKE\b",
    r"\bLOAD\s+CSV\b",
    r"\bPERIODIC\s+COMMIT\b",
    r"\bCALL\s+apoc\.system\b",
    r"\bCALL\s+apoc\.trigger\b",
    r"\bCALL\s+apoc\.cypher\.runMany\b",
    r"\bCALL\s+dbms\b",
    r"\bCALL\s+db\.create\b",
    r"\bCALL\s+db\.drop\b"
]

COMPILED_FORBIDDEN = [re.compile(kw, re.IGNORECASE) for kw in FORBIDDEN_KEYWORDS]

# Multiple query delimiter check (prevent query chaining)
SEMICOLON_CHECK = re.compile(r";\s*\S+")

class SecurityViolationError(Exception):
    """Raised when a query or tool call violates governance policies."""
    pass

class ASTSecurityValidator:
    """Enforces least privilege, read-only guarantees, and resource bounds on Cypher queries."""

    @staticmethod
    def validate_cypher(cypher: str) -> Tuple[bool, Optional[str], str]:
        """
        Validates Cypher query string.
        Returns:
            (is_safe: bool, violation_reason: Optional[str], sanitized_cypher: str)
        """
        if not cypher or not cypher.strip():
            return False, "Empty query provided.", ""

        cleaned = cypher.strip()

        # 1. Reject stacked queries separated by semicolons
        if SEMICOLON_CHECK.search(cleaned):
            return False, "Query chaining or stacked statements (';') detected.", cleaned

        # 2. Check forbidden modification & admin clauses
        for pattern in COMPILED_FORBIDDEN:
            match = pattern.search(cleaned)
            if match:
                forbidden_token = match.group(0)
                return False, f"Access policy violation: Forbidden clause or token '{forbidden_token}' detected.", cleaned

        # 3. Must begin with allowed read-only root clauses (MATCH, OPTIONAL MATCH, WITH, UNWIND, RETURN, CALL db.index)
        first_token_match = re.match(r"^\s*(\w+)", cleaned, re.IGNORECASE)
        if not first_token_match:
            return False, "Malformed query structure.", cleaned

        first_token = first_token_match.group(1).upper()
        allowed_starting_tokens = {"MATCH", "OPTIONAL", "WITH", "UNWIND", "RETURN", "CALL"}
        if first_token not in allowed_starting_tokens:
            return False, f"Invalid query root: '{first_token}'. Must start with MATCH, WITH, UNWIND, or CALL.", cleaned

        # 4. Inject automatic bounds (LIMIT 50) if query lacks a LIMIT clause
        sanitized = cleaned
        if not re.search(r"\bLIMIT\s+\d+\b", sanitized, re.IGNORECASE):
            sanitized = f"{sanitized} LIMIT 50"

        return True, None, sanitized

    @staticmethod
    def assert_safe(cypher: str) -> str:
        """Helper that returns sanitized Cypher or raises SecurityViolationError."""
        is_safe, reason, sanitized = ASTSecurityValidator.validate_cypher(cypher)
        if not is_safe:
            raise SecurityViolationError(reason)
        return sanitized

    @staticmethod
    def is_adversarial_or_destructive(query: str) -> Tuple[bool, Optional[str]]:
        """
        Detects malicious injection attacks, destructive database commands,
        or unauthorized schema alterations in raw user input (including typos like 'databse').
        Returns:
            (is_adversarial: bool, violation_reason: Optional[str])
        """
        if not query or not query.strip():
            return False, None

        q = query.strip()

        # 1. Direct Cypher/SQL Injection & Destructive Clause Syntax
        # Match actual query/DB-mutation syntax rather than bare English words like "create" or "delete"
        USER_INPUT_CLAUSE_PATTERNS = [
            (r"\bDETACH\s+DELETE\b", "DETACH DELETE"),
            (r"\bDELETE\s+(?:ALL\b|FROM\b|\*)|\bMATCH\b.*\bDELETE\s+[a-z_]\w*", "DELETE"),
            (r"\bCREATE\s*(?:\(|NODE\b|TABLE\b|DATABASE\b|INDEX\b|CONSTRAINT\b|USER\b|ROLE\b)", "CREATE"),
            (r"\bMERGE\s*\(", "MERGE"),
            (r"\bDROP\s+(?:ALL\b|TABLE\b|DATABASE\b|INDEX\b|CONSTRAINT\b|NODE\b|\()", "DROP"),
            (r"\bALTER\s+(?:DATABASE\b|TABLE\b|USER\b|ROLE\b|SYSTEM\b)", "ALTER"),
            (r"\bSET\s+(?:ROLE\b|[a-z_]\w*\.[a-z_]\w*\s*=)", "SET"),
            (r"\bGRANT\s+(?:ALL\b|PRIVILEGES\b|ACCESS\b|ROLE\b|READ\b|WRITE\b)", "GRANT"),
            (r"\bREVOKE\s+(?:ALL\b|PRIVILEGES\b|ACCESS\b|ROLE\b)", "REVOKE"),
            (r"\bREMOVE\s+[a-z_]\w*(?:\.[a-z_]\w*|:[A-Za-z_]\w*)", "REMOVE"),
            (r"\bLOAD\s+CSV\b", "LOAD CSV"),
            (r"\bPERIODIC\s+COMMIT\b", "PERIODIC COMMIT"),
            (r"\bCALL\s+apoc\.(?:system|trigger|cypher\.runMany)\b", "CALL apoc"),
            (r"\bCALL\s+dbms\b", "CALL dbms"),
            (r"\bCALL\s+db\.(?:create|drop)\b", "CALL db.admin"),
        ]
        for pat, token in USER_INPUT_CLAUSE_PATTERNS:
            if re.search(pat, q, re.IGNORECASE):
                return True, f"Forbidden database operation token '{token}' detected."

        # 2. Query Chaining Delimiter (prevent stacked queries)
        if SEMICOLON_CHECK.search(q):
            return True, "Stacked query chaining (';') detected."

        # 3. Natural Language Destructive Commands targeting database/graph/bulk data (e.g. 'delete database', 'drop table', 'wipe all courses')
        DESTRUCTIVE_VERBS = r"(?:delete|del|drop|destroy|wipe|truncate|erase|purge|clear|kill|format)"
        TARGET_ENTITIES = r"(?:(?:all\s+)?(?:db|databases?|databse|tables?|collections?|nodes?|relationships?|graph|records?|schema|everything)|all\s+(?:faculty|courses?|programs?|rooms?|campus|data))"
        comb_pattern = re.compile(rf"\b{DESTRUCTIVE_VERBS}\b.*?\b{TARGET_ENTITIES}\b|\b{TARGET_ENTITIES}\b.*?\b{DESTRUCTIVE_VERBS}\b", re.IGNORECASE)
        if comb_pattern.search(q):
            return True, "Destructive database mutation operation requested."

        # 4. OS shell execution / injection attempts
        if re.search(r"\b(?:rm\s+-rf|sudo|system\(|exec\(|eval\(|__import__|;\s*bash)\b", q, re.IGNORECASE):
            return True, "Unauthorized system or shell execution command detected."

        # 5. Prompt Injection & Delimiter Breakout Attempts
        if re.search(
            r"<<<(?:END_)?VERIFIED_CAMPUS_FACTS|"
            r"\b(?:disregard|ignore|override|bypass)\s+(?:all\s+)?(?:prior|previous|above|system)\s+instructions?\b|"
            r"\b(?:jwt\s+secret|secret\s+key|environment\s+passwords?|dump_server_environment)\b",
            q,
            re.IGNORECASE
        ):
            return True, "Prompt injection, delimiter breakout, or credential exfiltration attempt detected."

        # 6. SQL Injection & Raw Restricted Query / PII Exfiltration
        if re.search(
            r"\bUNION\s+SELECT\b|'\s*OR\s+1\s*=\s*1\b|"
            r"^\s*SELECT\s+.+\s+FROM\s+\w+|"
            r"\brun_governed_query\b",
            q,
            re.IGNORECASE
        ):
            return True, "SQL/Cypher injection or unauthorized raw query/tool invocation detected."

        return False, None
