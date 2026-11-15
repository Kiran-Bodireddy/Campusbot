"""
Adversarial Security & Governance Test Suite
Validates that malicious Cypher injections, unauthorized write operations,
stacked statements, and out-of-bounds parameters are 100% intercepted and audited.
"""

import pytest
from pydantic import ValidationError

from campus_knowledge_server.security.ast_validator import ASTSecurityValidator, SecurityViolationError
from campus_knowledge_server.tools.campus_tools import (
    PrerequisiteTreeRequest,
    AvailableRoomsRequest,
    GovernedQueryTemplateRequest,
    CampusKnowledgeTools
)

# 1. Adversarial Cypher Payloads
ADVERSARIAL_CYPHER_ATTACKS = [
    ("MATCH (n) DETACH DELETE n", "DELETE"),
    ("MATCH (c:Course) CREATE (x:Hacked {name: 'pwnd'})", "CREATE"),
    ("MATCH (f:Faculty) SET f.salary = 1000000", "SET"),
    ("DROP CONSTRAINT course_code", "DROP"),
    ("ALTER DATABASE neo4j SET ACCESS READ ONLY", "detected"),
    ("CALL apoc.system.execute('rm -rf /')", "CALL apoc.system"),
    ("MATCH (c:Course) LOAD CSV FROM 'http://evil.com/data.csv' AS row RETURN row", "LOAD CSV"),
    ("MATCH (c:Course) RETURN c.name; DROP (n)", "stacked statements"),
    ("GRANT ALL PRIVILEGES ON DATABASE neo4j TO attacker", "GRANT"),
]

@pytest.mark.parametrize("malicious_cypher,expected_token", ADVERSARIAL_CYPHER_ATTACKS)
def test_cypher_ast_blocks_malicious_attacks(malicious_cypher, expected_token):
    """Verifies that all malicious and destructive queries are rejected by AST validator."""
    is_safe, reason, _ = ASTSecurityValidator.validate_cypher(malicious_cypher)
    assert not is_safe, f"Security failure: Malicious query should have been blocked: {malicious_cypher}"
    assert reason is not None
    assert expected_token.lower() in reason.lower()

def test_safe_queries_pass_and_receive_auto_limit():
    """Verifies that legitimate read-only queries pass and receive automatic bounds."""
    safe_query = "MATCH (c:Course)-[:REQUIRES_PREREQUISITE]->(p:Course) RETURN c.name, p.name"
    is_safe, reason, sanitized = ASTSecurityValidator.validate_cypher(safe_query)
    assert is_safe
    assert reason is None
    assert "LIMIT 50" in sanitized

def test_pydantic_enforces_bounds():
    """Verifies that parameter bounds (e.g., max_depth <= 4) are strictly enforced."""
    # Attempt max_depth = 10 (exceeds le=4)
    with pytest.raises(ValidationError):
        PrerequisiteTreeRequest(course_code="CSE301", max_depth=10)

    # Attempt room capacity < 10
    with pytest.raises(ValidationError):
        AvailableRoomsRequest(building_code="TP", min_capacity=2)

def test_unauthorized_template_rejected():
    """Verifies that arbitrary or unwhitelisted templates are rejected."""
    req = GovernedQueryTemplateRequest(template_id="drop_all_tables_template", parameters={})
    with pytest.raises(SecurityViolationError):
        CampusKnowledgeTools.run_governed_query(req, caller="test_adversary")

def test_audit_hash_chain_detects_tampering(tmp_path):
    """Verifies that tampering with an audit entry breaks the cryptographic SHA-256 hash chain."""
    import json
    from campus_knowledge_server.security.audit import AuditLogger
    
    test_log = str(tmp_path / "tamper_test.jsonl")
    logger = AuditLogger(log_path=test_log)
    
    # 1. Log two legitimate events
    logger.log_event("alice", "lookup_course", {"course_code": "CSE101"}, "SUCCESS", 10.0)
    logger.log_event("bob", "find_room_schedule", {"room_id": "TP-101"}, "SUCCESS", 15.0)
    
    is_intact, count, msg = logger.verify_chain()
    assert is_intact is True
    assert count == 2
    
    # 2. Adversary tampers with the first entry (alters status)
    with open(test_log, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    tampered_entry = json.loads(lines[0])
    tampered_entry["status"] = "HACKED_STATUS"
    lines[0] = json.dumps(tampered_entry) + "\n"
    
    with open(test_log, "w", encoding="utf-8") as f:
        f.writelines(lines)
        
    # 3. Verification must fail and detect tampering
    is_intact_tampered, _, tamper_msg = logger.verify_chain()
    assert is_intact_tampered is False
    assert "Tampering detected" in tamper_msg

if __name__ == "__main__":
    pytest.main(["-v", __file__])

