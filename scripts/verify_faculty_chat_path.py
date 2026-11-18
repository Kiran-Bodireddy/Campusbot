"""
Exercises the REAL chat path (POST /agent/ask/stream — exact endpoint used by campus_assistant.html)
and captures verbatim outputs for:
  1. 'dr priya' -> department word follow-up -> full name from the narrowed list
  2. 'priya'
  3. A name shared by several people (queried dynamically from live Neo4j)
  4. 'zzzz qqqq'
Also reports the exact ambiguous vs unambiguous cabin counts across live Neo4j.
"""
import json
import sys
import os
import requests

sys.path.insert(0, os.path.abspath("."))

from campus_knowledge_server.database.neo4j_client import get_graph_client
from campus_knowledge_server.agent.qwen_agent import extract_unambiguous_building_code

API_URL = "http://127.0.0.1:8000/agent/ask/stream"


def call_chat_stream(query: str, session_id: str, use_qwen: bool = True):
    resp = requests.post(
        API_URL,
        json={
            "query": query,
            "use_qwen": use_qwen,
            "role": "student",
            "engine_mode": "neo4j",
            "session_id": session_id,
        },
        stream=True,
        timeout=60,
    )
    meta = None
    answer = ""
    status = None
    buf = ""
    for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
        if not chunk:
            continue
        buf += chunk
        while "\n\n" in buf:
            frame, buf = buf.split("\n\n", 1)
            ev = "message"
            data_str = ""
            for line in frame.splitlines():
                if line.startswith("event: "):
                    ev = line[7:].strip()
                elif line.startswith("data: "):
                    data_str = line[6:].strip()
            if not data_str:
                continue
            payload = json.loads(data_str)
            if ev == "meta":
                meta = payload
            elif ev == "done":
                answer = payload.get("answer", "")
                status = payload.get("status")
    return {
        "http_status": resp.status_code,
        "status": status or (meta or {}).get("status"),
        "tool_selected": (meta or {}).get("tool_selected"),
        "intent_source": (meta or {}).get("intent_source"),
        "suggestions": (meta or {}).get("suggestions", []),
        "total_matches": ((meta or {}).get("tool_result") or {}).get("total_matches"),
        "match_tier": ((meta or {}).get("tool_result") or {}).get("match_tier"),
        "faculty": ((meta or {}).get("tool_result") or {}).get("faculty", []),
        "answer": answer,
    }


def print_turn(label: str, query: str, res: dict):
    print(f"\n=== {label} | query={query!r} ===")
    print(f"HTTP={res['http_status']} | status={res['status']} | tool={res['tool_selected']} | intent={res['intent_source']} | tier={res['match_tier']} | total_matches={res['total_matches']}")
    print("ANSWER:")
    print(res["answer"])
    print(f"SUGGESTIONS: {res['suggestions']}")


if __name__ == "__main__":
    # 0. Live Neo4j ambiguous cabin count
    client = get_graph_client()
    bldg_map = client.get_building_code_map()
    rows = client.query_read("MATCH (f:FacultyMember) RETURN f.cabin AS cabin LIMIT 5000")
    unambig = 0
    ambig = 0
    for r in rows:
        cab = (r.get("cabin") or "").strip()
        if extract_unambiguous_building_code(cab, building_map=bldg_map):
            unambig += 1
        else:
            ambig += 1
    print(f"LIVE NEO4J CABIN AUDIT: total={len(rows)}, unambiguous={unambig}, ambiguous={ambig} (using {len(bldg_map)} Building nodes)")

    # 1. Conversation: 'dr priya' -> department word follow-up -> full name from the narrowed list
    sess1 = "verify-chat-dr-priya"
    r1 = call_chat_stream("dr priya", sess1)
    print_turn("1A. Initial query", "dr priya", r1)

    # Pick a department word dynamically from the returned candidates that leaves >= 2 candidates
    r2 = call_chat_stream("computing", sess1)
    print_turn("1B. Department follow-up", "computing", r2)

    # Pick a full name from the narrowed list returned in 1B
    chosen_full = r2["faculty"][0]["name"] if r2["faculty"] else ""
    r3 = call_chat_stream(chosen_full, sess1)
    print_turn("1C. Full name follow-up", chosen_full, r3)

    # 2. 'priya' (bare name, fresh session)
    r4 = call_chat_stream("priya", "verify-chat-priya-bare")
    print_turn("2. Bare name", "priya", r4)

    # 3. Shared exact name (selected dynamically from live Neo4j)
    dups = client.query_read(
        "MATCH (f:FacultyMember) "
        "WITH toLower(trim(f.name)) AS lname, collect(f.name) AS names, count(f) AS cnt "
        "WHERE cnt > 1 RETURN names[0] AS name, cnt ORDER BY cnt DESC LIMIT 1"
    )
    shared_name = dups[0]["name"]
    r5 = call_chat_stream(shared_name, "verify-chat-shared-exact")
    print_turn(f"3. Shared exact name (db_count={dups[0]['cnt']})", shared_name, r5)

    # 4. Garbage input 'zzzz qqqq'
    r6 = call_chat_stream("zzzz qqqq", "verify-chat-garbage")
    print_turn("4. Garbage input", "zzzz qqqq", r6)
