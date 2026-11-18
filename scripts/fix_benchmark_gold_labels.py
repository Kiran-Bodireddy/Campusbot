import json

DATASET_PATH = "campus_knowledge_server/eval/benchmark_dataset.json"

with open(DATASET_PATH, "r", encoding="utf-8") as f:
    ds = json.load(f)

UPDATES = {
    "SH-41": {
        "gold_entities": [{"type": "room", "id": "MEB-104"}],
        "source": "campus_graph_unified.json -> rooms (MEB-301 has capacity=35 < 60; MEB-104 has capacity>=60 and is vacant Mon 08:45-09:35 in schedules)"
    },
    "SH-45": {
        "gold_entities": [{"type": "course", "id": "21CSC316J"}],
        "source": "Datasets/courses.json -> code='21CSC316J', name='Cloud Architecture And Protocols'"
    },
    "SH-46": {
        "gold_entities": [{"type": "course", "id": "21CSC501T"}],
        "source": "Datasets/courses.json -> code='21CSC501T', name='Natural Language Processing Techniques'"
    },
    "SH-47": {
        "gold_entities": [{"type": "course", "id": "21CSC305T"}],
        "source": "Datasets/courses.json -> code='21CSC305T', name='Blockchain Using Cryptography'"
    },
    "SH-48": {
        "gold_entities": [{"type": "course", "id": "21CSC205P"}],
        "source": "Datasets/courses.json -> code='21CSC205P', name='Database Management Systems'"
    },
    "SH-49": {
        "gold_entities": [{"type": "course", "id": "21MEO106T"}],
        "source": "Datasets/courses.json -> code='21MEO106T', name='Introduction To Robotics'"
    },
    "SH-50": {
        "gold_entities": [{"type": "program", "id": "PROG-308"}],
        "source": "admission_eligibility_master.json -> program_id='PROG-308', B.Tech CSE w/s AI & ML (PROG-101 was M.Tech Biomedical Engg)"
    },
    "SH-51": {
        "gold_entities": [{"type": "program", "id": "PROG-166"}],
        "source": "admission_eligibility_master.json -> program_id='PROG-166', MBA. Business Administration (PROG-201 was M.D.S. Prosthodontics)"
    },
    "SH-52": {
        "gold_entities": [{"type": "program", "id": "PROG-093"}],
        "source": "admission_eligibility_master.json -> program_id='PROG-093', M.Tech. Artificial Intelligence (PROG-109 was M.Tech EV Tech)"
    },
    "SH-53": {
        "gold_entities": [{"type": "program", "id": "PROG-076"}],
        "source": "admission_eligibility_master.json -> program_id='PROG-076', first B.Tech entry (PROG-101 was M.Tech Biomedical Engg)"
    },
    "SH-54": {
        "gold_entities": [{"type": "program", "id": "PROG-084"}],
        "source": "admission_eligibility_master.json -> program_id='PROG-084', first M.Tech entry (M.Tech CyberSecurity)"
    },
    "SH-55": {
        "gold_entities": [{"type": "program", "id": "PROG-317"}],
        "source": "admission_eligibility_master.json -> program_id='PROG-317', B.Tech. Biotechnology (PROG-115 was M.Tech Genetic Engg)"
    },
    "SH-61": {
        "gold_params": {"program_query": "Computer Science and Engineering", "semester": 3},
        "gold_entities": [{"type": "course", "id": "21CSC201J"}],
        "source": "curricula_semester_master.json -> B.Tech in CSE Sem 3 contains 21CSC201J (Data Structures And Algorithms); fixed param key to program_query"
    },
    "SH-62": {
        "gold_params": {"program_query": "Artificial Intelligence", "semester": 4},
        "gold_entities": [{"type": "course", "id": "21AIC202J"}],
        "source": "curricula_semester_master.json -> B.Tech in AI Sem 4 contains 21AIC202J; fixed param key to program_query"
    },
    "SH-63": {
        "gold_params": {"program_query": "Computer Science and Engineering", "semester": 1},
        "gold_entities": [{"type": "course", "id": "21MAB101T"}],
        "source": "curricula_semester_master.json -> B.Tech in CSE Sem 1 contains 21MAB101T (Calculus And Linear Algebra; 21MAT101T does not exist)"
    },
    "SH-64": {
        "gold_params": {"program_query": "Mechanical Engineering", "semester": 5},
        "gold_entities": [{"type": "course", "id": "21MEC301T"}],
        "source": "curricula_semester_master.json -> B.Tech in Mechanical Engineering Sem 5 contains 21MEC301T (Thermal Systems Engineering); fixed param key"
    },
    "SH-65": {
        "gold_params": {"program_query": "Computer Science and Engineering", "semester": 6},
        "gold_entities": [{"type": "course", "id": "21CSC303J"}],
        "source": "curricula_semester_master.json -> B.Tech in CSE Sem 6 contains 21CSC303J (Software Engineering); 21CSC401J is not in Sem 6"
    },
    "MH-01": {
        "gold_entities": [{"type": "course", "id": "21CSC206T"}, {"type": "faculty", "id": "FAC-0223"}],
        "source": "campus_graph_unified.json -> teaching_assignments for 21CSC206T lists FAC-0223 (Dr. Nithyakani P), not FAC-0170"
    },
    "MH-03": {
        "gold_params": {"program_query": "Computer Science and Engineering", "semester": 3},
        "gold_entities": [{"type": "course", "id": "21CSC201J"}],
        "source": "curricula_semester_master.json -> B.Tech in CSE Sem 3 contains 21CSC201J; fixed param key to program_query"
    },
    "MH-05": {
        "gold_entities": [{"type": "course", "id": "21CSC206T"}],
        "source": "campus_graph_unified.json -> schedules for 21CSC206T are TP-102/TP-302 (not TP-101), and lookup_course returns Course entity 21CSC206T"
    },
    "MH-07": {
        "query": "What degree programs require 21MAB101T in their first year curriculum?",
        "gold_params": {"program_query": "Computer Science and Engineering", "semester": 1},
        "gold_entities": [{"type": "course", "id": "21MAB101T"}],
        "source": "curricula_semester_master.json -> Sem 1 Calculus code is 21MAB101T (21MAT101T does not exist)"
    },
    "MH-09": {
        "gold_params": {"program_query": "Artificial Intelligence", "semester": 4},
        "gold_entities": [{"type": "course", "id": "21AIC202J"}],
        "source": "curricula_semester_master.json -> B.Tech in AI Sem 4 contains 21AIC202J; fixed param key to program_query"
    },
    "MH-12": {
        "gold_entities": [{"type": "program", "id": "PROG-308"}],
        "source": "admission_eligibility_master.json -> program_id='PROG-308', B.Tech CSE w/s AI & ML (PROG-109 was M.Tech EV Tech)"
    }
}

changed = 0
for item in ds:
    qid = item["id"]
    if qid in UPDATES:
        upd = UPDATES[qid]
        old_p = item.get("gold_params")
        old_e = item.get("gold_entities")
        if "query" in upd:
            item["query"] = upd["query"]
        if "gold_params" in upd:
            item["gold_params"] = upd["gold_params"]
        if "gold_entities" in upd:
            item["gold_entities"] = upd["gold_entities"]
        item["gold_source"] = upd["source"]
        changed += 1
        print(f"Updated {qid}: old_gold={old_e} -> new_gold={item['gold_entities']} | source={upd['source']}")

with open(DATASET_PATH, "w", encoding="utf-8") as f:
    json.dump(ds, f, indent=2)

print(f"\nTotal items updated in {DATASET_PATH}: {changed}")
