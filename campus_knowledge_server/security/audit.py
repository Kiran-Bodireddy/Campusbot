"""
Structured JSONL Audit & Governance Telemetry Logger with Cryptographic Hash Chaining
Maintains an immutable, append-only security log of every tool execution,
parameter payload, caller identity, execution latency, and policy violation.
Each record is cryptographically linked with SHA-256 (blockchain-style tamper detection).
"""

import os
import json
import time
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
AUDIT_LOG_FILE = os.path.join(LOG_DIR, "audit_telemetry.jsonl")

GENESIS_HASH = "0" * 64

class AuditLogger:
    def __init__(self, log_path: str = AUDIT_LOG_FILE):
        self.log_path = log_path
        self._last_hash = self._get_tail_hash()

    def _get_tail_hash(self) -> str:
        """Reads the last entry's hash to initialize the hash chain, or returns GENESIS_HASH."""
        if not os.path.exists(self.log_path):
            return GENESIS_HASH
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
            if lines:
                last_entry = json.loads(lines[-1])
                return last_entry.get("entry_hash", GENESIS_HASH)
        except Exception:
            pass
        return GENESIS_HASH

    def log_event(
        self,
        caller: str,
        tool_name: str,
        parameters: Dict[str, Any],
        status: str,  # "SUCCESS", "POLICY_VIOLATION", "VALIDATION_ERROR", "EXECUTION_ERROR"
        latency_ms: float,
        result_count: int = 0,
        cypher_executed: Optional[str] = None,
        violation_reason: Optional[str] = None,
        role: str = "student"
    ) -> Dict[str, Any]:
        """Appends a structured, SHA-256 hash-chained event entry to the JSONL log file."""
        event: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "caller": caller,
            "role": role,
            "tool_name": tool_name,
            "parameters": parameters,
            "status": status,
            "latency_ms": round(latency_ms, 2),
            "result_count": result_count,
            "cypher_executed": cypher_executed,
            "violation_reason": violation_reason,
            "prev_hash": self._last_hash
        }

        # Compute tamper-evident SHA-256 entry hash
        canonical_str = json.dumps(event, sort_keys=True)
        entry_hash = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
        event["entry_hash"] = entry_hash
        self._last_hash = entry_hash

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as e:
            print(f"Error writing to audit log: {e}")

        return event

    def verify_chain(self) -> Tuple[bool, int, Optional[str]]:
        """
        Verifies the cryptographic integrity of the SHA-256 audit log chain.
        Returns:
            (is_intact: bool, verified_entries_count: int, error_message: Optional[str])
        """
        if not os.path.exists(self.log_path):
            return True, 0, "Log file does not exist yet."

        expected_prev = GENESIS_HASH
        count = 0

        with open(self.log_path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except Exception as e:
                    return False, count, f"Line {idx} corrupted JSON: {e}"

                # 1. Verify prev_hash matches prior entry's hash
                entry_prev = entry.get("prev_hash")
                if entry_prev is None:
                    # Legacy log entry without hash-chaining; allow upgrade
                    expected_prev = entry.get("entry_hash", GENESIS_HASH)
                    count += 1
                    continue

                if entry_prev != expected_prev:
                    return False, count, f"Hash chain broken at entry {idx}: prev_hash '{entry_prev}' does not match expected '{expected_prev}'."

                # 2. Re-compute hash to ensure payload was not modified
                stored_hash = entry.get("entry_hash")
                payload = {k: v for k, v in entry.items() if k != "entry_hash"}
                canonical_str = json.dumps(payload, sort_keys=True)
                computed_hash = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

                if computed_hash != stored_hash:
                    return False, count, f"Tampering detected at entry {idx}: payload altered. Stored '{stored_hash}', computed '{computed_hash}'."

                expected_prev = stored_hash
                count += 1

        return True, count, "Hash chain intact. Zero tampering detected."

# Global singleton logger
_audit_logger_instance: Optional[AuditLogger] = None

def get_audit_logger() -> AuditLogger:
    global _audit_logger_instance
    if _audit_logger_instance is None:
        _audit_logger_instance = AuditLogger()
    return _audit_logger_instance
