import os
import sys
import json
import chromadb

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VECTOR_FILE = os.path.join(BASE_DIR, "srmist_vector_documents.json")
CHROMA_DIR = os.path.join(BASE_DIR, "chroma_srm_db")

def main():
    print("="*70)
    print(" SRMIST Academic Programs - Vector Database Indexing & Search Demo ")
    print("="*70)

    # 1. Initialize Persistent ChromaDB Client
    print(f"\n[+] Initializing persistent ChromaDB at: {CHROMA_DIR} ...")
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    
    # 2. Create or Get Collection
    # Chroma uses its standard default embedding model (all-MiniLM-L6-v2) automatically
    collection = client.get_or_create_collection(
        name="srmist_programs",
        metadata={"description": "SRMIST Complete Academic Catalog Embeddings"}
    )

    # 3. Check if already populated
    existing_count = collection.count()
    print(f"[+] Current collection documents count: {existing_count}")

    if existing_count < 400:
        print(f"[+] Loading vector documents from {VECTOR_FILE} ...")
        with open(VECTOR_FILE, "r", encoding="utf-8") as f:
            docs = json.load(f)

        ids = [d["id"] for d in docs]
        documents = [d["document"] for d in docs]
        metadatas = [d["metadata"] for d in docs]

        print(f"[+] Indexing {len(docs)} documents into ChromaDB (batching 100 at a time)...")
        batch_size = 100
        for i in range(0, len(docs), batch_size):
            end_idx = min(i + batch_size, len(docs))
            collection.add(
                ids=ids[i:end_idx],
                documents=documents[i:end_idx],
                metadatas=metadatas[i:end_idx]
            )
            print(f"    Indexed {end_idx}/{len(docs)} documents...")
        print("[✔] Embedding & indexing complete!")
    else:
        print("[✔] Collection is already indexed and ready!")

    # 4. Demonstrate Semantic Searches
    queries = [
        {
            "title": "Query 1: Pure Semantic Search (AI & Robotics)",
            "query": "Artificial intelligence, deep learning, autonomous systems and robotics engineering",
            "filter": None,
            "n_results": 3
        },
        {
            "title": "Query 2: Eligibility-Based Query (Commerce background wanting Analytics)",
            "query": "I completed 12th standard in commerce and want to study business analytics or finance",
            "filter": {"degree_level": "Undergraduate (UG)"},
            "n_results": 3
        },
        {
            "title": "Query 3: Hybrid Search (Engineering with Fee Filter < 3,00,000 INR)",
            "query": "Engineering and technology courses focusing on core infrastructure or mechanics",
            "filter": {
                "$and": [
                    {"faculty": "Faculty of Engineering & Technology"},
                    {"annual_fees_inr": {"$gt": 0}},
                    {"annual_fees_inr": {"$lt": 300000}}
                ]
            },
            "n_results": 3
        }
    ]

    print("\n" + "="*70)
    print(" Running Semantic Queries against Vector DB ")
    print("="*70)

    for q in queries:
        print(f"\n>>> {q['title']}")
        print(f"    Prompt: \"{q['query']}\"")
        if q['filter']:
            print(f"    Metadata Filter: {q['filter']}")

        results = collection.query(
            query_texts=[q["query"]],
            n_results=q["n_results"],
            where=q["filter"]
        )

        for i in range(len(results['ids'][0])):
            doc_id = results['ids'][0][i]
            meta = results['metadatas'][0][i]
            dist = results['distances'][0][i] if 'distances' in results and results['distances'] else None
            
            fee_str = f"₹ {meta['annual_fees_inr']:,}" if meta.get('annual_fees_inr') else "N/A"
            print(f"\n    Result #{i+1} [Distance: {dist:.4f}]" if dist is not None else f"\n    Result #{i+1}")
            print(f"    * Program: {meta['program_name']} ({meta['degree_level']})")
            print(f"    * Faculty: {meta['faculty']} | Dept: {meta['department']}")
            print(f"    * Annual Fee: {fee_str} | Campus: {meta['campuses']}")
            print(f"    * URL: {meta['url']}")

    print("\n" + "="*70)
    print("[✔] Vector Database is fully functional and ready for LangChain / LlamaIndex / RAG!")
    print("="*70)

if __name__ == "__main__":
    main()
