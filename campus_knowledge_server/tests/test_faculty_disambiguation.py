"""
Generic tests for ambiguous faculty-name handling, tiered ranking, conversation narrowing,
graph-derived cabin labeling, and registry-backed follow-up suggestions.
All test names, departments, and cabins are selected dynamically from the live Neo4j graph
at runtime — no hardcoded person names, IDs, departments, or buildings.
"""
import re
from collections import Counter, defaultdict
import pytest

from campus_knowledge_server.agent.qwen_agent import (
    GovernedCampusAgent,
    ConversationMemory,
    describe_cabin_location,
    extract_unambiguous_building_code,
)
from campus_knowledge_server.config.matching_config import (
    load_matching_config,
    strip_honorifics_and_tokenize,
)
from campus_knowledge_server.database.neo4j_client import get_graph_client
from campus_knowledge_server.tools.campus_tools import CampusKnowledgeTools, FacultyProfileRequest
from campus_knowledge_server.tools.governed_executor import TOOL_FUNC_MAP


def _fetch_live_faculty():
    client = get_graph_client()
    assert client.is_connected and client.driver, "Live Neo4j connection required for graph-driven tests."
    rows = client.query_read(
        "MATCH (f:FacultyMember) "
        "RETURN f.id AS id, f.name AS name, f.department AS department, f.cabin AS cabin "
        "LIMIT 5000"
    )
    assert len(rows) > 0
    return rows


@pytest.fixture(scope="module")
def agent():
    return GovernedCampusAgent()


@pytest.fixture(scope="module")
def live_faculty():
    return _fetch_live_faculty()


def test_honorific_stripping_all_configured_forms(live_faculty):
    cfg = load_matching_config()["faculty_matching"]
    honorifics = cfg["honorifics"]

    # Pick a faculty member whose stripped full name is unique in the live graph
    stripped_counts = Counter()
    stripped_to_row = {}
    for row in live_faculty:
        toks = strip_honorifics_and_tokenize(row["name"], honorifics)
        if len(toks) >= 2:
            phrase = " ".join(toks)
            stripped_counts[phrase] += 1
            stripped_to_row[phrase] = row

    unique_phrase = next(p for p, cnt in stripped_counts.items() if cnt == 1)
    expected_row = stripped_to_row[unique_phrase]

    # Query bare name and with each configured honorific (with and without '.')
    variants = [unique_phrase]
    for h in honorifics:
        variants.append(f"{h} {unique_phrase}")
        variants.append(f"{h.capitalize()}. {unique_phrase}")

    for q in variants:
        res = CampusKnowledgeTools.lookup_faculty_profile(FacultyProfileRequest(faculty_name=q), caller="test")
        assert res["status"] == "SUCCESS"
        assert res["match_tier"] == "exact"
        assert res["total_matches"] == 1
        assert res["faculty"][0]["id"] == expected_row["id"]


def test_whole_word_match_ranks_above_partial_match(live_faculty):
    cfg = load_matching_config()["faculty_matching"]
    honorifics = cfg["honorifics"]

    # Dynamically find a token (>= 4 chars) that occurs as a whole word in >= 1 name
    # AND strictly as a proper substring inside a longer word in >= 1 other name.
    token_whole_ids = defaultdict(set)
    all_words = set()
    for row in live_faculty:
        toks = strip_honorifics_and_tokenize(row["name"], honorifics)
        for t in set(toks):
            if len(t) >= 4:
                token_whole_ids[t].add(row["id"])
                all_words.add(t)

    chosen_token = None
    for tok, whole_ids in token_whole_ids.items():
        has_longer_superstring = any(tok in w and w != tok for w in all_words)
        if has_longer_superstring and len(whole_ids) >= 2:
            chosen_token = tok
            break

    assert chosen_token is not None, "Expected at least one token with both whole-word and partial matches in graph."

    res = CampusKnowledgeTools.lookup_faculty_profile(FacultyProfileRequest(faculty_name=chosen_token), caller="test")
    assert res["match_tier"] == "whole_word"
    assert res["total_matches"] == len(token_whole_ids[chosen_token])
    assert res["all_matches_count"] > res["total_matches"]
    # Every top-tier returned candidate MUST contain chosen_token as a whole word
    for fac in res["faculty"]:
        fac_toks = strip_honorifics_and_tokenize(fac["name"], honorifics)
        assert chosen_token in fac_toks


def test_multiple_matches_return_list_with_total_count_and_no_silent_single_pick(agent, live_faculty):
    cfg = load_matching_config()["faculty_matching"]
    honorifics = cfg["honorifics"]
    max_show = int(cfg["max_displayed_matches"])

    # Dynamically pick a whole-word token shared by > max_displayed_matches people
    tok_counts = Counter()
    for row in live_faculty:
        for t in set(strip_honorifics_and_tokenize(row["name"], honorifics)):
            if len(t) >= 4:
                tok_counts[t] += 1

    ambig_tok, expected_total = next((t, c) for t, c in tok_counts.most_common() if c > max_show)

    sess_id = "test-generic-ambig-list"
    ConversationMemory.clear_session(sess_id)
    res = agent.execute_query(f"dr {ambig_tok}", use_llm_synthesis=False, session_id=sess_id)

    assert res["tool_selected"] == "lookup_faculty_profile"
    assert res["status"] == "CLARIFICATION_NEEDED"
    assert res["tool_result"]["total_matches"] == expected_total
    assert str(expected_total) in res["answer"]
    bullet_lines = [ln for ln in res["answer"].splitlines() if ln.strip().startswith("- ")]
    assert len(bullet_lines) == max_show
    assert "full name" in res["answer"].lower() and "department" in res["answer"].lower()


def test_shared_exact_name_lists_all_matches_never_picks_one(agent, live_faculty):
    cfg = load_matching_config()["faculty_matching"]
    honorifics = cfg["honorifics"]
    max_show = int(cfg["max_displayed_matches"])

    # Dynamically find an exact stripped name shared by >= 2 people in Neo4j
    by_stripped = defaultdict(list)
    for row in live_faculty:
        phrase = " ".join(strip_honorifics_and_tokenize(row["name"], honorifics))
        if phrase:
            by_stripped[phrase].append(row)

    shared_phrase, rows = next((p, rlist) for p, rlist in by_stripped.items() if len(rlist) >= 2)
    sample_query_name = rows[0]["name"]

    sess_id = "test-generic-shared-exact"
    ConversationMemory.clear_session(sess_id)
    res = agent.execute_query(sample_query_name, use_llm_synthesis=False, session_id=sess_id)

    assert res["tool_selected"] == "lookup_faculty_profile"
    assert res["status"] == "CLARIFICATION_NEEDED"
    assert res["tool_result"]["match_tier"] == "exact"
    assert res["tool_result"]["total_matches"] == len(rows)
    assert str(len(rows)) in res["answer"]
    bullet_lines = [ln for ln in res["answer"].splitlines() if ln.strip().startswith("- ")]
    assert len(bullet_lines) == min(len(rows), max_show)


def test_conversation_followup_filters_stored_list_without_new_search(agent, live_faculty, monkeypatch):
    cfg = load_matching_config()["faculty_matching"]
    honorifics = cfg["honorifics"]

    # Dynamically find a whole-word token whose candidates span multiple departments,
    # with at least one department holding >= 2 candidates and a distinct full name inside that department.
    by_tok = defaultdict(list)
    for row in live_faculty:
        for t in set(strip_honorifics_and_tokenize(row["name"], honorifics)):
            if len(t) >= 4:
                by_tok[t].append(row)

    chosen_tok = None
    chosen_dept_word = None
    chosen_person = None
    stop = {"department", "of", "and", "the", "school", "college", "srm", "faculty"}

    for tok, rows in by_tok.items():
        if not (4 <= len(rows) <= 20):
            continue
        by_dept = defaultdict(list)
        for r in rows:
            if r.get("department"):
                by_dept[r["department"]].append(r)
        if len(by_dept) < 2:
            continue
        # Find a department word that narrows (1 <= matches < len(rows))
        for dept_name, drows in by_dept.items():
            d_words = [w for w in re.sub(r"[^\w\s]", " ", dept_name.lower()).split() if len(w) >= 5 and w not in stop]
            for dw in d_words:
                sub = [r for r in rows if dw in (r.get("department") or "").lower()]
                if 2 <= len(sub) < len(rows):
                    # Ensure at least one person in `sub` has a unique stripped name within `sub`
                    s_names = Counter(" ".join(strip_honorifics_and_tokenize(x["name"], honorifics)) for x in sub)
                    uniq_cand = next(
                        (x for x in sub if s_names[" ".join(strip_honorifics_and_tokenize(x["name"], honorifics))] == 1),
                        None
                    )
                    if uniq_cand:
                        chosen_tok = tok
                        chosen_dept_word = dw
                        chosen_person = uniq_cand
                        break
            if chosen_tok:
                break
        if chosen_tok:
            break

    assert chosen_tok and chosen_dept_word and chosen_person

    sess_id = "test-generic-followup-narrowing"
    ConversationMemory.clear_session(sess_id)

    # Turn 1: Ambiguous query populates stored candidates
    res1 = agent.execute_query(chosen_tok, use_llm_synthesis=False, session_id=sess_id)
    assert res1["status"] == "CLARIFICATION_NEEDED"
    pending = ConversationMemory.get_pending_faculty(sess_id)
    assert pending is not None and len(pending["candidates"]) >= 4

    # Block any new DB lookup during Turn 2 and Turn 3 to prove narrowing uses ONLY stored candidates
    def _forbid_new_search(*args, **kwargs):
        raise AssertionError("Follow-up narrowing must filter stored candidates, not start a new search!")

    monkeypatch.setattr(CampusKnowledgeTools, "lookup_faculty_profile", staticmethod(_forbid_new_search))

    # Turn 2: Department word narrows stored list and reports remaining count
    res2 = agent.execute_query(chosen_dept_word, use_llm_synthesis=False, session_id=sess_id)
    assert res2["status"] == "CLARIFICATION_NEEDED"
    assert res2["intent_source"] == "Conversation Memory Narrowing"
    rem_count = res2["tool_result"]["total_matches"]
    assert 2 <= rem_count < len(pending["candidates"])
    assert str(rem_count) in res2["answer"]

    # Turn 3: Full name from narrowed list resolves directly to 1 profile
    res3 = agent.execute_query(chosen_person["name"], use_llm_synthesis=False, session_id=sess_id)
    assert res3["status"] == "SUCCESS"
    assert res3["intent_source"] == "Conversation Memory Narrowing"
    assert chosen_person["name"] in res3["answer"]
    assert ConversationMemory.get_pending_faculty(sess_id) is None


def test_garbage_input_returns_not_found(agent):
    for garbage in ["zzzz qqqq", "xkcd plmnbvcxz"]:
        direct = CampusKnowledgeTools.lookup_faculty_profile(FacultyProfileRequest(faculty_name=garbage), caller="test")
        assert direct["status"] == "NOT_FOUND"
        assert direct["total_matches"] == 0
        assert direct["faculty"] == []

        sess_id = f"test-garbage-{garbage.replace(' ', '_')}"
        ConversationMemory.clear_session(sess_id)
        chat_res = agent.execute_query(garbage, use_llm_synthesis=False, session_id=sess_id)
        assert chat_res["status"] == "NOT_FOUND"
        assert chat_res["tool_result"]["total_matches"] == 0
        assert chat_res["tool_result"]["faculty"] == []


def test_cabin_labels_unambiguous_and_ambiguous_from_graph_buildings(live_faculty):
    client = get_graph_client()
    bldg_map = client.get_building_code_map()
    assert len(bldg_map) > 0

    # Pick an unambiguous cabin (<CODE><sep><suffix>) and an ambiguous no-separator cabin (<CODE><digits>) from live Neo4j
    unambig_cabin = None
    unambig_code = None
    ambig_nosep_cabin = None

    codes_sorted = sorted(bldg_map.keys(), key=len, reverse=True)
    nosep_pat = re.compile(r"^(?:" + "|".join(re.escape(c) for c in codes_sorted) + r")\d+")

    for row in live_faculty:
        cab = (row.get("cabin") or "").strip()
        if not cab:
            continue
        code = extract_unambiguous_building_code(cab, building_map=bldg_map)
        if code and not unambig_cabin:
            unambig_cabin = cab
            unambig_code = code
        elif not code and nosep_pat.match(cab) and not ambig_nosep_cabin:
            ambig_nosep_cabin = cab
        if unambig_cabin and ambig_nosep_cabin:
            break

    assert unambig_cabin and unambig_code
    assert ambig_nosep_cabin

    # Unambiguous cabin attaches the live Neo4j Building.name
    assert describe_cabin_location(unambig_cabin, building_map=bldg_map) == f"{unambig_cabin} ({bldg_map[unambig_code]})"
    # Ambiguous no-separator cabin MUST be returned verbatim as stored (no guessed building or floor)
    assert describe_cabin_location(ambig_nosep_cabin, building_map=bldg_map) == ambig_nosep_cabin


def test_followup_suggestions_backed_by_registered_tools_only(agent, live_faculty):
    cfg = load_matching_config()["faculty_matching"]
    honorifics = cfg["honorifics"]

    # Pick a unique faculty member from the live graph
    counts = Counter(" ".join(strip_honorifics_and_tokenize(r["name"], honorifics)) for r in live_faculty)
    unique_row = next(
        r for r in live_faculty
        if counts[" ".join(strip_honorifics_and_tokenize(r["name"], honorifics))] == 1
        and len(strip_honorifics_and_tokenize(r["name"], honorifics)) >= 2
    )

    res = agent.execute_query(unique_row["name"], use_llm_synthesis=False, session_id="test-reg-suggestions")
    assert res["status"] == "SUCCESS"
    ans_lower = res["answer"].lower()
    # Unbacked follow-up actions must be completely gone
    for forbidden_phrase in ("teaching timetable", "courses in this department", "classrooms nearby"):
        assert forbidden_phrase not in ans_lower

    # Every suggestion must correspond to a registered tool allowed for student
    active_tools = agent._get_allowed_registered_tools("student")
    assert active_tools.issubset(set(TOOL_FUNC_MAP.keys()))
    for s in res.get("suggestions", []):
        s_low = s.lower()
        assert "who teaches in" not in s_low
        assert "teaching timetable" not in s_low
        assert "classrooms nearby" not in s_low
