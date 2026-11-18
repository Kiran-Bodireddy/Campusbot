"""
Cryptographic Token-Based Role Authentication & Authorization.
Enforces Role-Based Access Control (RBAC) via signed HMAC-SHA256 JWT tokens,
preventing client-side privilege escalation and role spoofing.
"""

import os
import time
import jwt
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

JWT_SECRET = os.getenv("CAMPUS_JWT_SECRET")
if not JWT_SECRET:
    raise ValueError("CAMPUS_JWT_SECRET environment variable is required.")

JWT_ALGORITHM = "HS256"
DEFAULT_EXPIRATION_SECONDS = 86400  # 24 hours


class AuthenticationError(Exception):
    """Raised when an authorization token is missing, invalid, or expired."""
    pass


class RoleSpoofingError(Exception):
    """Raised when a client attempts to claim a higher privilege than their verified token."""
    pass


class Principal:
    """Security principal representing the authenticated caller and their verified RBAC role."""
    def __init__(self, user_id: str, role: str, caller_type: str = "http"):
        self.user_id = user_id
        self.role = role
        self.caller_type = caller_type

    def __repr__(self) -> str:
        return f"<Principal id={self.user_id} role={self.role} caller={self.caller_type}>"


def create_access_token(
    user_id: str,
    role: str = "student",
    expires_in_seconds: int = DEFAULT_EXPIRATION_SECONDS,
    additional_claims: Optional[Dict[str, Any]] = None
) -> str:
    """Issues a cryptographically signed HMAC-SHA256 JWT token with verified role."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + expires_in_seconds,
        "iss": "srmist-campus-knowledge-authority"
    }
    if additional_claims:
        payload.update(additional_claims)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_access_token(token: str) -> Dict[str, Any]:
    """
    Decodes and cryptographically verifies an access token.
    Raises AuthenticationError on expired or tampered signatures.
    """
    if not token:
        raise AuthenticationError("Authorization token is missing.")
    # Strip optional 'Bearer ' prefix
    if token.startswith("Bearer "):
        token = token[7:].strip()
    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return decoded
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Authorization token has expired.")
    except jwt.InvalidTokenError as e:
        raise AuthenticationError(f"Invalid authorization token: {e}")


def resolve_principal(
    auth_header: Optional[str] = None,
    requested_body_role: Optional[str] = None,
    caller_ip: str = "unknown"
) -> Principal:
    """
    Resolves the caller identity and verified role:
    1. If auth_header is present, decrypts and verifies the JWT token.
    2. If client sends role: 'admin' in body but token is for 'student', raises RoleSpoofingError.
    3. If no auth_header is provided, assigns least-privilege 'student' guest principal.
       Any attempt to request elevated role without a token raises RoleSpoofingError.
    """
    if auth_header:
        claims = verify_access_token(auth_header)
        verified_role = claims.get("role", "student").lower()
        user_id = claims.get("sub", caller_ip)

        # Privilege escalation check
        if requested_body_role and requested_body_role.lower() != verified_role:
            role_hierarchy = {"student": 1, "faculty": 2, "admin": 3}
            token_level = role_hierarchy.get(verified_role, 1)
            requested_level = role_hierarchy.get(requested_body_role.lower(), 1)
            if requested_level > token_level:
                raise RoleSpoofingError(
                    f"Privilege Escalation Blocked: Verified role '{verified_role}' cannot claim '{requested_body_role}'."
                )

        return Principal(user_id=user_id, role=verified_role, caller_type="jwt")

    # Unauthenticated default: Least-privilege 'student'
    if requested_body_role and requested_body_role.lower() in ("faculty", "admin"):
        raise RoleSpoofingError(
            f"Privilege Escalation Blocked: Role '{requested_body_role}' requires a verified JWT Bearer token."
        )

    return Principal(user_id=f"guest_{caller_ip}", role="student", caller_type="anonymous")


# Standard pre-generated credentials for evaluation and testing
TEST_TOKENS = {
    "student": create_access_token("test_student_01", role="student"),
    "faculty": create_access_token("test_faculty_01", role="faculty"),
    "admin": create_access_token("test_admin_01", role="admin")
}
