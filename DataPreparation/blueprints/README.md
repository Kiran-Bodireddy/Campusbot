# Property Graph Ontology Blueprint

This document defines the formal schema and ontology of the SRMIST Campus Knowledge Graph.

## 1. Graph Entity Types (Nodes)

* **`Course`**: 264 verified courses from Regulations 2021 curriculum PDFs (attributes: `code`, `name`, `credits`, `ltpc`, `department`, `semester_range`).
* **`Program`**: Accredited degree programs (B.Tech, M.Tech, MBBS, MBA, Law) with cutoffs and fees.
* **`FacultyMember`**: Verified academic instructors with designations, departments, and cabin allocations.
* **`Room`**: 264 instructional spaces across Kattankulathur buildings with seating capacities and equipment types.
* **`Building`**: 9 physical campus blocks (Tech Park, University Building, Bioengineering, etc.).

## 2. Graph Relationship Types (Edges)

1. `(:Course)-[:REQUIRES_PREREQUISITE]->(:Course)`: Directed dependency chain for academic progression.
2. `(:FacultyMember)-[:TEACHES]->(:Course)`: Verified teaching assignments.
3. `(:College)-[:OFFERS_PROGRAM]->(:Program)`: Academic program offerings.
4. `(:Room)-[:LOCATED_IN]->(:Building)`: Spatial infrastructure hierarchy.
5. `(:Course)-[:ALLOCATED_IN {day, slot}]->(:Room)`: Weekly class timetable allocation.

## 3. Storage & Engine
* Ingested into **Neo4j Enterprise / Community** via batch Cypher transactions.
* Queried at runtime via parameterized Cypher templates through `campus_tools.py`.
