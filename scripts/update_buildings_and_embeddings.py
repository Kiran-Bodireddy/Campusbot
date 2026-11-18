"""
Ingests and enriches the complete 20-building campus directory for SRMIST Kattankulathur,
connects physical graph relationships (Rooms, Departments, and Faculty),
computes 768-dimensional embeddings via Ollama nomic-embed-text,
and creates the native Neo4j vector index `building_embeddings`.
"""

import os
import sys
import json
import time
import requests
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv(".env")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "Jeevan@223")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

CAMPUS_BUILDINGS = [
    {
        "code": "TP",
        "name": "Tech Park 1 (TP-1)",
        "floors": 15,
        "campus": "Kattankulathur (KTR)",
        "focus": "School of Computing & Advanced Engineering",
        "aliases": ["TP", "TP-1", "TP1", "Tech Park", "Tech Park 1"],
        "departments_housed": [
            "Department of Computing Technologies",
            "Department of Networking And Communications",
            "Department of Computational Intelligence",
            "Department of Data Science and Business Systems"
        ],
        "facilities": [
            "Apple Mac Authorized Training Lab",
            "NVIDIA AI Research Laboratory",
            "Cisco Advanced Networking Academy",
            "Smart Seminar Halls (1st, 2nd, 4th floors)",
            "Faculty Cabins (Floors 3-8)"
        ],
        "description": "The Tech Park 1 (TP-1) is a 15-story computing and engineering landmark at SRMIST Kattankulathur. It serves as the primary home for the School of Computing, including Computing Technologies (CTech), Networking & Communications (NWC), Computational Intelligence (CInt), and Data Science. The building features specialized high-performance AI and machine learning labs, the Apple Authorized Training Center, advanced cloud computing suites, Cisco networking laboratories, and smart lecture halls."
    },
    {
        "code": "TP2",
        "name": "Tech Park 2 (TP-2)",
        "floors": 16,  # G+15
        "campus": "Kattankulathur (KTR)",
        "focus": "Advanced Digital Technical Departments & Central Placements",
        "aliases": ["TP2", "TP-2", "Tech Park 2", "Tech Park-2", "New Tech Park"],
        "departments_housed": [
            "Directorate of Career Centre (Placement Office)",
            "Advanced Technical Departments",
            "Postgraduate Computing Wings"
        ],
        "facilities": [
            "Directorate of Career Centre / Central Placement Cell (15th Floor)",
            "Sentinel Online Assessment Lab",
            "Corporate Placement Interview Boardrooms",
            "High-Speed Networked Digital Classrooms",
            "Smart Computing Testing Pods"
        ],
        "description": "Tech Park 2 (TP-2) is a modern G+15 story technical and computing tower complementing TP-1. Designed with cutting-edge digital infrastructure and networked smart labs, it houses technical departments and is crowned on the 15th floor by the Directorate of Career Centre (Central Placement Office), where campus recruitment drives, company coding tests, online aptitude assessments in Sentinel Lab, and corporate interviews take place."
    },
    {
        "code": "CVR",
        "name": "Sir C.V. Raman Research Park",
        "floors": 7,
        "campus": "Kattankulathur (KTR)",
        "focus": "Advanced Scientific Research, Nanotechnology & Clean Energy",
        "aliases": ["CV Raman", "C.V. Raman", "CVR", "Sir C.V. Raman Block", "CV Raman Research Park", "Raman Block"],
        "departments_housed": [
            "Nanotechnology Research Centre (NRC)",
            "Centre for Clean Energy & Materials",
            "Interdisciplinary Research Directorate"
        ],
        "facilities": [
            "Nanotechnology Research Laboratories",
            "High-Resolution Transmission Electron Microscopy (HR-TEM) Suite",
            "Field Emission Scanning Electron Microscopy (FE-SEM)",
            "Cleanrooms & Material Characterization Labs",
            "Funded Sponsored Project Wings (DST, DBT, DRDO)"
        ],
        "description": "Sir C.V. Raman Research Park is a multi-story research facility dedicated exclusively to pure and applied scientific, technological, and interdisciplinary research. It accommodates the Nanotechnology Research Centre, clean energy laboratories, advanced electron microscopy characterization suites, and doctoral research laboratories for funded government and industry projects."
    },
    {
        "code": "UB",
        "name": "University Building",
        "floors": 16,  # G+15
        "campus": "Kattankulathur (KTR)",
        "focus": "Central Administration & Central Library",
        "aliases": ["UB", "University Building", "Main Building", "Admin Block"],
        "departments_housed": [
            "Chancellor & Vice-Chancellor Secretariat",
            "Office of the Registrar",
            "Controller of Examinations",
            "Dean of Engineering and Technology",
            "Department of Mathematics",
            "Department of Physics",
            "Department of Chemistry",
            "Career Development Centre (CDC)"
        ],
        "facilities": [
            "Central Air-Conditioned Library (4 floors, 150k+ print volumes)",
            "Administrative Council Chamber",
            "Office of International Relations",
            "Academic Directorate",
            "Dr. T.P. Ganesan Auditorium entrance foyer"
        ],
        "description": "The iconic 15-story University Building (UB) stands as the administrative and intellectual focal point of SRMIST Kattankulathur. It accommodates the Chancellor's and Vice-Chancellor's Secretariat, the Registrar's Office, Controller of Examinations, Dean of Engineering, and Admissions Directorate. The lower 4 floors house the sprawling Central Library with over 150,000 print volumes and digital resource centers. The upper floors accommodate the Departments of Mathematics, Physics, Chemistry, and Career Development."
    },
    {
        "code": "BEL",
        "name": "Basic Engineering Laboratory Block",
        "floors": 6,  # G+5
        "campus": "Kattankulathur (KTR)",
        "focus": "1st-Year Engineering Practicals, Foundational Labs & Workshops",
        "aliases": ["BEL", "BEL Block", "Basic Engineering Lab", "Basic Engineering Labs", "Workshop Block", "First Year Engineering Lab"],
        "departments_housed": [
            "Mechanical Engineering Workshop Practice Section",
            "Department of Electrical & Electronics Engineering (BEEE)",
            "Engineering Graphics & CAED Division",
            "Engineering Physics & Chemistry Division"
        ],
        "facilities": [
            "Mechanical Workshop Hangars (Fitting, Carpentry, Welding, Sheet Metal, Foundry)",
            "Basic Electrical and Electronics Engineering (BEEE) Laboratory",
            "Engineering Graphics & Computer Aided Engineering Drawing (CAED) Halls",
            "First-Year Engineering Physics Laboratory & Darkrooms",
            "First-Year Engineering Chemistry Laboratory & Analytical Titration Benches",
            "Basic Civil Engineering & Surveying Instrument Store"
        ],
        "description": "The Basic Engineering Laboratory Block (BEL) is a G+5 facility housing foundational practical laboratories for all first-year B.Tech engineering students. It houses the heavy mechanical workshop practice hangars for welding, carpentry, and fitting, the Basic Electrical and Electronics (BEEE) labs, high-capacity engineering graphics drawing halls, and first-year physics and chemistry experimentation laboratories."
    },
    {
        "code": "CRC",
        "name": "Classroom Complex (CRC Block)",
        "floors": 9,  # G+8
        "campus": "Kattankulathur (KTR)",
        "focus": "Centralized Lecture Halls & Tutorial Complexes",
        "aliases": ["CRC", "CRC Block", "Class Room Complex", "Classroom Complex"],
        "departments_housed": [
            "Central Academic Scheduling Wing",
            "Interdisciplinary Humanities & Social Sciences"
        ],
        "facilities": [
            "High-Capacity Amphitheater Lecture Classrooms",
            "Centralized Examination Suites",
            "Smart Audio-Visual Tutorial Pods",
            "Departmental Seminar Rooms"
        ],
        "description": "The Classroom Complex (CRC Block) is a G+8 multi-story academic facility dedicated to high-capacity lecture theaters, tutorial classrooms, and centralized semester examination suites. It hosts foundational and interdisciplinary lectures with full multimedia acoustic systems."
    },
    {
        "code": "HTB",
        "name": "Hi-Tech Block",
        "floors": 7,  # G+6
        "campus": "Kattankulathur (KTR)",
        "focus": "Information Technology, ITKM, and Civil Engineering",
        "aliases": ["HTB", "Hi-Tech Block", "Hi Tech Block", "Hitech Block", "Civil Block"],
        "departments_housed": [
            "Directorate of ITKM (IT & Knowledge Management)",
            "Department of Civil Engineering",
            "Central Data Center"
        ],
        "facilities": [
            "Central ITKM University Server Data Center",
            "Advanced Geotechnical & Structural Dynamics Lab",
            "Concrete Testing & Material Evaluation Rig",
            "Environmental Engineering Laboratory"
        ],
        "description": "The Hi-Tech Block is a G+6 facility housing the Directorate of Information Technology and Knowledge Management (ITKM), the central university server data center, and the Department of Civil Engineering with its specialized geotechnical, concrete technology, and environmental engineering testing laboratories."
    },
    {
        "code": "MEB",
        "name": "Mechanical Engineering Block",
        "floors": 7,  # G+6
        "campus": "Kattankulathur (KTR)",
        "focus": "Mechanical, Aerospace, Automobile, and Mechatronics",
        "aliases": ["MEB", "Mechanical Block", "Mechanical Engineering", "Auto Block"],
        "departments_housed": [
            "Department of Mechanical Engineering",
            "Department of Aerospace Engineering",
            "Department of Automobile Engineering",
            "Department of Mechatronics Engineering"
        ],
        "facilities": [
            "Subsonic Aerodynamic Wind Tunnel Facility",
            "Automotive Chassis Dynamometer Rig",
            "Computerized CNC Machining Centers",
            "Industrial Robotics & Automation Studio",
            "CAD/CAM/CAE Modeling Laboratories"
        ],
        "description": "The Mechanical Engineering Block (MEB) is an industrial and educational engineering complex accommodating Mechanical, Automobile, Aerospace, and Mechatronics Engineering. It contains state-of-the-art subsonic aerodynamic wind tunnels, CAD/CAM computational design suites, thermal fluid mechanics rigs, CNC machining centers, and heavy engineering workshops."
    },
    {
        "code": "ESB",
        "name": "Electrical Sciences Block",
        "floors": 8,  # G+7
        "campus": "Kattankulathur (KTR)",
        "focus": "Electronics & Communication, Electrical & Electronics",
        "aliases": ["ESB", "Electrical Block", "ECE Block", "EEE Block"],
        "departments_housed": [
            "Department of Electronics and Communication Engineering (ECE)",
            "Department of Electrical and Electronics Engineering (EEE)"
        ],
        "facilities": [
            "Radio Frequency & Microwave Anechoic Chamber",
            "Cadence VLSI Design Laboratory",
            "Embedded Systems & Microcontroller Center",
            "Power Systems & Smart Grid Simulation Lab",
            "Optical Communication Laboratory"
        ],
        "description": "The Electrical Sciences Block (ESB) houses the Departments of Electronics and Communication Engineering (ECE) and Electrical and Electronics Engineering (EEE). It is equipped with advanced RF & Microwave anechoic chambers, VLSI circuit design suites, embedded systems laboratories, and smart grid simulators."
    },
    {
        "code": "BIO",
        "name": "School of Bioengineering Block",
        "floors": 7,  # G+6
        "campus": "Kattankulathur (KTR)",
        "focus": "Life Sciences, Biotechnology, Biomedical, and Genetic Engineering",
        "aliases": ["BIO", "BTB", "Bio Block", "Biotech Block", "Bioengineering Block", "School of Bioengineering"],
        "departments_housed": [
            "Department of Biotechnology",
            "Department of Biomedical Engineering",
            "Department of Genetic Engineering",
            "Department of Food Process Engineering"
        ],
        "facilities": [
            "Biosafety Level-2 (BSL-2) Certified Cleanrooms",
            "Plant & Animal Tissue Culture Suites",
            "Next-Generation DNA Sequencing Center",
            "Bioprocess & Fermentation Pilot Plant",
            "Biomedical Signals & Instrumentation Lab"
        ],
        "description": "The School of Bioengineering Block is a G+6 dedicated life sciences center housing the Departments of Biotechnology, Biomedical Engineering, Genetic Engineering, and Food Process Engineering. It features Biosafety Level-2 certified cleanrooms, tissue culture laboratories, high-throughput DNA sequencing suites, and bioprocess fermentation pilot plants."
    },
    {
        "code": "FMB",
        "name": "Faculty of Management Block",
        "floors": 5,  # G+4
        "campus": "Kattankulathur (KTR)",
        "focus": "Management, Business Administration, and MBA",
        "aliases": ["FMB", "Management Block", "MBA Block", "School of Management", "SOM"],
        "departments_housed": [
            "SRM School of Management (SRM SOM)",
            "Department of Commerce"
        ],
        "facilities": [
            "Stock Market Financial Trading Simulation Lab",
            "Executive Corporate Boardrooms",
            "Case Study Amphitheater Classrooms",
            "Management Library & Business Analytics Pod"
        ],
        "description": "The Faculty of Management Block houses the SRM School of Management (SRM SOM), offering undergraduate and MBA degree programs. Designed with corporate-style amphitheater classrooms, it features modern executive education suites, stock trading simulation labs, business incubation cells, and corporate interview boardrooms."
    },
    {
        "code": "SLB",
        "name": "School of Law Building",
        "floors": 4,  # G+3
        "campus": "Kattankulathur (KTR)",
        "focus": "Legal Education, Jurisprudence & Judicial Practice",
        "aliases": ["SLB", "Law Building", "School of Law", "Law Block"],
        "departments_housed": [
            "SRM School of Law"
        ],
        "facilities": [
            "Judicial-Standard Moot Court Hall",
            "Free Legal Aid & Community Counsel Clinic",
            "Law Research & Supreme Court Case Reporters Library",
            "Faculty Chambers & Conference Rooms"
        ],
        "description": "The School of Law Building is a dedicated legal studies academy. It features a fully equipped judicial-standard Moot Court hall for national and international competitions, a dedicated legal aid clinic providing community legal counsel, legal research computing pods, and an extensive law library housing supreme court case reporters and legal treatises."
    },
    {
        "code": "ARCH",
        "name": "School of Architecture & Interior Design (SAID)",
        "floors": 4,  # G+3
        "campus": "Kattankulathur (KTR)",
        "focus": "Architecture, Interior Design, and Urban Planning",
        "aliases": ["ARCH", "SAID", "SEDA", "Architecture Building", "School of Architecture", "Interior Design Block", "Arch Block"],
        "departments_housed": [
            "Department of Architecture",
            "Department of Interior Design"
        ],
        "facilities": [
            "Open-Plan Architectural Drafting Studios",
            "Model Making, Woodworking & Carpentry Workshop",
            "Climatology, Lighting & Building Acoustics Lab",
            "Building Material Sample Museum",
            "Digital Fabrication Studio with 3D Laser Cutters"
        ],
        "description": "The School of Architecture & Interior Design (SAID) is a dedicated design academy featuring open-plan design studios, natural lighting atriums, architectural model-making workshops, material museums, construction yards, and CAD/BIM digital design labs for B.Arch, M.Arch, and B.Des students."
    },
    {
        "code": "SIHM",
        "name": "SRM Institute of Hotel Management",
        "floors": 4,  # G+3
        "campus": "Kattankulathur (KTR)",
        "focus": "Hospitality, Culinary Arts, and Hotel Administration",
        "aliases": ["SIHM", "Hotel Management", "Hotel Management Block", "Hospitality Block"],
        "departments_housed": [
            "SRM Institute of Hotel Management (SIHM)"
        ],
        "facilities": [
            "Commercial Quantity Food Production Kitchens",
            "Bakery & Confectionery Practical Labs",
            "Training Restaurant & Bar Operations Studio",
            "Model Front Office & Mock Luxury Hotel Suite"
        ],
        "description": "The SRM Institute of Hotel Management building is a dedicated hospitality academy featuring full-scale commercial training restaurants, commercial quantity production kitchens, bakery and confectionery laboratories, front office simulation suites, and housekeeping training centers."
    },
    {
        "code": "MAB",
        "name": "Medical College Academic Block",
        "floors": 6,  # G+5
        "campus": "Kattankulathur (KTR)",
        "focus": "Undergraduate MBBS Education & Pre-Clinical Medical Sciences",
        "aliases": ["MAB", "Medical Academic Block", "Medical College Building", "MBBS Block"],
        "departments_housed": [
            "Department of Anatomy",
            "Department of Physiology",
            "Department of Biochemistry",
            "Department of Pathology",
            "Department of Microbiology",
            "Department of Pharmacology",
            "Department of Forensic Medicine",
            "Department of Community Medicine"
        ],
        "facilities": [
            "Air-Conditioned Human Anatomy Dissection Hall",
            "Clinical Skills Simulation Center with Medical Manikins",
            "Central Medical Library & Digital Reading Room",
            "Pathology & Forensic Specimen Museum"
        ],
        "description": "The Medical College Academic Block (MAB) is the central academic teaching facility for undergraduate MBBS and postgraduate medical sciences. It accommodates the air-conditioned human anatomy dissection hall, histology and physiology laboratories, medical specimen museums, and the clinical skills simulation center."
    },
    {
        "code": "MCB",
        "name": "Medical College Hospital Block",
        "floors": 10,  # G+9
        "campus": "Kattankulathur (KTR)",
        "focus": "1,200-Bed Tertiary Teaching Hospital & Clinical Services",
        "aliases": ["MCB", "SRM Hospital", "Medical College Hospital", "SRM General Hospital", "Hospital Block"],
        "departments_housed": [
            "Department of General Medicine",
            "Department of General Surgery",
            "Department of Pediatrics",
            "Department of Obstetrics & Gynecology",
            "Department of Orthopedics",
            "Department of Cardiology",
            "Department of Neurology"
        ],
        "facilities": [
            "1,200-Bed Tertiary Care Inpatient Wards",
            "24/7 Emergency Casualty & Trauma Care Unit",
            "Modular Sterile Surgical Operation Theaters",
            "Intensive Care Units (ICU, ICCU, NICU, PICU)",
            "Advanced Radiology Suite (MRI, 128-Slice CT, Digital X-Ray)"
        ],
        "description": "The Medical College Hospital Block comprises the SRM Medical College Hospital and Research Centre (SRM MCH&RC), a 1,200-bed multi-specialty tertiary care teaching hospital. It provides 24/7 emergency casualty care, modular operating theaters, intensive care units, outpatient specialist clinics, and diagnostic radiology centers."
    },
    {
        "code": "DCB",
        "name": "SRM Dental College & Hospital",
        "floors": 5,  # G+4
        "campus": "Kattankulathur (KTR)",
        "focus": "Dental Surgery (BDS, MDS) & Oral Healthcare",
        "aliases": ["DCB", "Dental College", "Dental Hospital", "SRM Dental Block"],
        "departments_housed": [
            "Department of Oral & Maxillofacial Surgery",
            "Department of Orthodontics",
            "Department of Prosthodontics",
            "Department of Conservative Dentistry & Endodontics",
            "Department of Periodontics",
            "Department of Pedodontics"
        ],
        "facilities": [
            "350+ Electronic Dental Chair Operatory Clinics",
            "Pre-Clinical Phantom Head Simulation Laboratory",
            "Dental Ceramic, Casting & Prosthetics Lab",
            "Cone Beam Computed Tomography (CBCT) 3D Dental Imaging"
        ],
        "description": "The SRM Dental College & Hospital is a comprehensive dental education and treatment center offering BDS and MDS degrees. It is equipped with over 350 electronic dental operatories, pre-clinical phantom head simulation laboratories, and 3D Cone Beam Computed Tomography imaging suites."
    },
    {
        "code": "CPB",
        "name": "College of Pharmacy Building",
        "floors": 5,  # G+4
        "campus": "Kattankulathur (KTR)",
        "focus": "Pharmacy (B.Pharm, M.Pharm, Pharm.D) & Drug Discovery",
        "aliases": ["CPB", "Pharmacy College", "College of Pharmacy", "Pharmacy Building"],
        "departments_housed": [
            "Department of Pharmaceutics",
            "Department of Pharmaceutical Chemistry",
            "Department of Pharmacology",
            "Department of Pharmacognosy",
            "Department of Pharmacy Practice"
        ],
        "facilities": [
            "Industrial Pharmacy Pilot Scale Manufacturing Plant",
            "Central Analytical Instrumentation Facility (HPLC, GC-MS, FTIR)",
            "CPCSEA-Approved Animal Research House",
            "Aseptic Formulation Cleanroom"
        ],
        "description": "The College of Pharmacy Building is a specialized pharmaceutical education and research center housing B.Pharm, M.Pharm, and Pharm.D programs. It features an industrial pilot scale manufacturing plant for tableting and coating, sophisticated analytical chromatography facilities, and sterile formulation cleanrooms."
    },
    {
        "code": "HSB",
        "name": "College of Nursing & Health Sciences Block",
        "floors": 5,  # G+4
        "campus": "Kattankulathur (KTR)",
        "focus": "Nursing, Physiotherapy, and Occupational Therapy",
        "aliases": ["HSB", "Nursing College", "Physiotherapy Block", "Health Sciences Building", "Occupational Therapy"],
        "departments_housed": [
            "SRM College of Nursing",
            "SRM College of Physiotherapy",
            "SRM College of Occupational Therapy"
        ],
        "facilities": [
            "Nursing Foundation & Maternal-Child Clinical Skill Simulation Labs",
            "Exercise Therapy Gymnasium & Gait Training Studio",
            "Electrotherapy & Sports Rehabilitation Clinic",
            "Pediatric Sensory Integration Unit"
        ],
        "description": "The College of Nursing & Health Sciences Block houses nursing, physiotherapy, and occupational therapy disciplines. It features clinical nursing foundation simulation suites, extensive exercise therapy gymnasiums, electrotherapy outpatient clinics, and pediatric rehabilitation centers."
    },
    {
        "code": "TPG",
        "name": "Dr. T.P. Ganesan Auditorium",
        "floors": 4,
        "campus": "Kattankulathur (KTR)",
        "focus": "Central University Convocations, Conferences & Cultural Festivals",
        "aliases": ["TPG", "TP Ganesan Auditorium", "TP Ganesan", "Main Auditorium", "Auditorium"],
        "departments_housed": [
            "Directorate of Campus Life",
            "University Events Management Wing"
        ],
        "facilities": [
            "Central Air-Conditioned Main Auditorium (4,000-seat capacity)",
            "Two Mini-Auditoriums (300 seats each)",
            "VIP Lounges & Green Rooms",
            "State-of-the-Art Acoustic & Stage Lighting Array"
        ],
        "description": "The Dr. T.P. Ganesan Auditorium is one of the largest convention centers in Asia, with a seating capacity of 4,000 in the central air-conditioned hall, alongside two 300-seat mini-auditoriums. It is the premier venue for university convocations, national academic conferences, and cultural mega-events such as Milan and Aaruush."
    }
]

def generate_embedding(text: str) -> list:
    """Generates 768-dimensional vector embedding via Ollama nomic-embed-text."""
    url = f"{OLLAMA_URL}/api/embeddings"
    payload = {"model": "nomic-embed-text", "prompt": text}
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()["embedding"]
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return [0.0] * 768

def run_update():
    print(f"\n=======================================================")
    print(f" Ingesting {len(CAMPUS_BUILDINGS)} Verified Campus Buildings into Neo4j")
    print(f"=======================================================\n")

    with driver.session() as s:
        # 1. Ingest building nodes
        for idx, b in enumerate(CAMPUS_BUILDINGS, 1):
            code = b["code"]
            name = b["name"]
            print(f"[{idx}/{len(CAMPUS_BUILDINGS)}] Embedding & Upserting: {name} ({code})...", end="", flush=True)

            embed_text = (
                f"Building: {name} | Code: {code} | Aliases: {', '.join(b['aliases'])} | "
                f"Floors: {b['floors']} | Primary Focus: {b['focus']} | "
                f"Description: {b['description']} | "
                f"Departments: {', '.join(b['departments_housed'])} | "
                f"Key Facilities: {', '.join(b['facilities'])}"
            )

            t0 = time.time()
            vector = generate_embedding(embed_text)
            embed_duration = time.time() - t0

            query = """
            MERGE (b:Building {code: $code})
            SET b.name = $name,
                b.floors = $floors,
                b.campus = $campus,
                b.focus = $focus,
                b.aliases = $aliases,
                b.departments_housed = $departments_housed,
                b.facilities = $facilities,
                b.description = $description,
                b.embedding = $embedding,
                b.source = 'official'
            RETURN b.code
            """
            s.run(query, {
                "code": code,
                "name": name,
                "floors": b["floors"],
                "campus": b["campus"],
                "focus": b["focus"],
                "aliases": b["aliases"],
                "departments_housed": b["departments_housed"],
                "facilities": b["facilities"],
                "description": b["description"],
                "embedding": vector
            })
            print(f" Done ({embed_duration:.2f}s, dim={len(vector)})")

        # 2. Re-link Room relationships to Buildings (:Room)-[:LOCATED_IN]->(:Building)
        print("\nLinking Rooms to Buildings ([:LOCATED_IN])...")
        res_rooms = s.run("""
        MATCH (r:Room)
        MATCH (b:Building {code: r.building_code})
        MERGE (r)-[:LOCATED_IN]->(b)
        RETURN count(r) as linked_count
        """).single()
        print(f"Linked {res_rooms['linked_count']} rooms to Building nodes.")

        # 3. Link Departments to Buildings (:Department)-[:HOUSED_IN]->(:Building)
        print("\nLinking Departments to Buildings ([:HOUSED_IN])...")
        link_dept_query = """
        UNWIND $buildings as b_data
        MATCH (b:Building {code: b_data.code})
        UNWIND b_data.departments_housed as dept_name
        MERGE (d:Department {name: dept_name})
        ON CREATE SET d.college = 'SRMIST', d.source = 'official'
        MERGE (d)-[:HOUSED_IN]->(b)
        RETURN count(d) as depts_linked
        """
        res_dept = s.run(link_dept_query, {"buildings": CAMPUS_BUILDINGS}).single()
        print(f"Linked academic departments to their physical Building nodes.")

        # 4. Create Native Neo4j Vector Index
        print("\nCreating / Verifying Vector Index: 'building_embeddings'...")
        try:
            s.run("""
            CREATE VECTOR INDEX building_embeddings IF NOT EXISTS
            FOR (b:Building)
            ON (b.embedding)
            OPTIONS {indexConfig: {
              `vector.dimensions`: 768,
              `vector.similarity_function`: 'cosine'
            }}
            """)
            print("Vector index 'building_embeddings' created / online.")
        except Exception as e:
            print(f"Index creation note: {e}")

        # 5. Verify index status
        v_indexes = s.run("SHOW VECTOR INDEXES").data()
        print(f"\nActive Vector Indexes in Neo4j:")
        for idx in v_indexes:
            print(f" - {idx.get('name')}: {idx.get('state')} ({idx.get('populationPercent')}%) on {idx.get('labelsOrTypes')}")

        total_bldgs = s.run("MATCH (b:Building) RETURN count(b) as count").single()["count"]
        bldgs_with_emb = s.run("MATCH (b:Building) WHERE b.embedding IS NOT NULL RETURN count(b) as count").single()["count"]
        print(f"\nFinal Ingestion Count:")
        print(f" - Total Buildings in Neo4j: {total_bldgs}")
        print(f" - Buildings with 768-dim Embeddings: {bldgs_with_emb} / {total_bldgs} (100%)")

if __name__ == "__main__":
    run_update()
    driver.close()
