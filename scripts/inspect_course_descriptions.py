import json, os, glob
from dotenv import load_dotenv
from neo4j import GraphDatabase, READ_ACCESS

load_dotenv(".env")

with open("Datasets/courses.json", "r", encoding="utf-8") as f:
    cs = json.load(f)

print(f"Datasets/courses.json count: {len(cs)}")
print("Keys:", list(cs[0].keys()))
for code in ["21CSC206T", "21CSO451T", "21AIC202J", "21CSC205P"]:
    row = next((c for c in cs if c.get("code") == code), None)
    if row:
        print(f"\n--- {code} ({row.get('name')}) ---")
        print("  description:", repr((row.get("description") or "")[:400]))
        for k, v in row.items():
            if k not in ("code", "name", "description"):
                print(f"  {k}: {str(v)[:140]}")

# Check how many courses have broken/garbled/truncated descriptions (like 'Program Outcomes (PO)')
po_boiler = sum(1 for c in cs if "program outcomes" in (c.get("description") or "").lower() or "the purpose of learning this course is to:" in (c.get("description") or "").lower())
short_desc = sum(1 for c in cs if len((c.get("description") or "").strip()) < 60)
print(f"\nQuality audit on Datasets/courses.json: boilerplate_PO_prefix={po_boiler}/{len(cs)}, short(<60 chars)={short_desc}/{len(cs)}")

# Check what other files exist in Datasets/ and root
print("\nFiles in Datasets/:")
for p in sorted(glob.glob("Datasets/*")):
    print(f"  {p} ({os.path.getsize(p)} bytes)")
print("\nFiles in campus_knowledge_server/data/:")
for p in sorted(glob.glob("campus_knowledge_server/data/**/*", recursive=True)):
    if os.path.isfile(p):
        print(f"  {p} ({os.path.getsize(p)} bytes)")
