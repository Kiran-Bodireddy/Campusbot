"""
make_demo_tokens.py
-------------------
Generates signed JWT demo tokens (student and admin) for testing RBAC and admin endpoints.
Tokens are generated dynamically using the active server JWT secret — never hardcoded in HTML.

Usage:
    python scripts/make_demo_tokens.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from campus_knowledge_server.security.auth import create_access_token


def main():
    student_token = create_access_token(user_id="demo_student_01", role="student", expires_in_seconds=86400)
    admin_token = create_access_token(user_id="demo_admin_01", role="admin", expires_in_seconds=86400)

    print("=== DEMO JWT TOKENS (valid 24h) ===")
    print(f"\nSTUDENT_TOKEN={student_token}")
    print(f"\nADMIN_TOKEN={admin_token}")
    print("\nExample header: Authorization: Bearer <TOKEN>")


if __name__ == "__main__":
    main()
