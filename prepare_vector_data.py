import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_JSON = os.path.join(BASE_DIR, "srmist_programs_master.json")
OUTPUT_VECTOR_JSON = os.path.join(BASE_DIR, "srmist_vector_documents.json")

def format_document_text(p):
    """
    Constructs an optimal, semantically rich text representation 
    for dense vector embeddings (e.g. Sentence-BERT, OpenAI, Cohere, Gemini).
    """
    parts = []
    
    # 1. Header & Classification
    parts.append(f"Program Title: {p.get('program_name')}")
    if p.get('credential'):
        parts.append(f"Degree Awarded: {p.get('credential')}")
    parts.append(f"Level: {p.get('degree_level')}")
    parts.append(f"Faculty / College: {p.get('faculty')}")
    if p.get('department'):
        parts.append(f"Department: {p.get('department')}")
    
    # 2. Key Specs
    parts.append(f"Campuses Available: {p.get('campuses_available') or 'Main Campus'}")
    parts.append(f"Duration: {p.get('duration') or 'Standard Duration'}")
    if p.get('sanctioned_intake'):
        parts.append(f"Sanctioned Intake: {p.get('sanctioned_intake')} seats")
    
    # Fees
    if p.get('annual_fees_inr'):
        parts.append(f"Annual Tuition Fees: INR {p.get('annual_fees_inr'):,} ({p.get('annual_fees_raw')})")
    elif p.get('annual_fees_raw'):
        parts.append(f"Annual Fees: {p.get('annual_fees_raw')}")
        
    # Campus Offerings breakdown if available
    if p.get('offerings'):
        off_descs = []
        for o in p.get('offerings'):
            details = []
            if o.get('campus'): details.append(f"Campus: {o['campus']}")
            if o.get('intake'): details.append(f"Intake: {o['intake']}")
            if o.get('fees'): details.append(f"Fee: {o['fees']}")
            if o.get('duration'): details.append(f"Duration: {o['duration']}")
            if details:
                off_descs.append(" | ".join(details))
        if off_descs:
            parts.append("Campus-Specific Offerings:\n- " + "\n- ".join(off_descs))

    # 3. Eligibility (Crucial for admission queries)
    if p.get('eligibility_criteria'):
        parts.append(f"Eligibility & Admission Criteria: {p.get('eligibility_criteria')}")
        
    # 4. About the Program / Scope
    if p.get('about_program'):
        parts.append(f"Program Overview & Curriculum: {p.get('about_program')}")
        
    # 5. Career & Specializations
    if p.get('career_opportunities'):
        parts.append(f"Career Opportunities & Roles: {p.get('career_opportunities')}")
        
    # 6. Official URL
    parts.append(f"Official URL: {p.get('program_url')}")
    
    return "\n".join(parts)

def main():
    print(f"[+] Loading {INPUT_JSON} ...")
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        programs = json.load(f)

    vector_docs = []
    for p in programs:
        doc_text = format_document_text(p)
        
        # Metadata dictionary strictly formatted for Vector DB payload filtering
        # Note: Vector DBs like Chroma/Pinecone support str, int, float, bool in metadata
        metadata = {
            "program_id": int(p.get("program_id", 0)),
            "program_name": str(p.get("program_name") or ""),
            "degree_level": str(p.get("degree_level") or ""),
            "credential": str(p.get("credential") or ""),
            "faculty": str(p.get("faculty") or ""),
            "department": str(p.get("department") or ""),
            "duration": str(p.get("duration") or ""),
            "campuses": str(p.get("campuses_available") or ""),
            "annual_fees_inr": int(p.get("annual_fees_inr")) if p.get("annual_fees_inr") is not None else 0,
            "url": str(p.get("program_url") or "")
        }

        vector_docs.append({
            "id": f"srm_program_{p['program_id']}",
            "document": doc_text,
            "metadata": metadata
        })

    with open(OUTPUT_VECTOR_JSON, "w", encoding="utf-8") as f:
        json.dump(vector_docs, f, ensure_ascii=False, indent=2)

    print(f"[✔] Generated {len(vector_docs)} vector documents saved to: {OUTPUT_VECTOR_JSON}")

if __name__ == "__main__":
    main()
