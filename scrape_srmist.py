import os
import re
import sys
import json
import time
import random
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)

SITEMAP_URL = "https://www.srmist.edu.in/program_cpt-sitemap.xml"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.srmist.edu.in/program-finder/"
}

def get_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    adapter = requests.adapters.HTTPAdapter(max_retries=3, pool_connections=20, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def fetch_sitemap_urls(session):
    print(f"[+] Fetching sitemap from {SITEMAP_URL} ...")
    resp = session.get(SITEMAP_URL, timeout=15)
    resp.raise_for_status()
    
    # Parse URL entries with lastmod
    entries = re.findall(r'<url>(.*?)</url>', resp.text, re.DOTALL)
    urls_meta = []
    for entry in entries:
        loc_m = re.search(r'<loc><!\[CDATA\[(.*?)\]\]></loc>|<loc>(.*?)</loc>', entry)
        lastmod_m = re.search(r'<lastmod><!\[CDATA\[(.*?)\]\]></lastmod>|<lastmod>(.*?)</lastmod>', entry)
        if loc_m:
            url = loc_m.group(1) or loc_m.group(2)
            lastmod = (lastmod_m.group(1) or lastmod_m.group(2)) if lastmod_m else ""
            urls_meta.append({"url": url.strip(), "lastmod": lastmod.strip()})
            
    print(f"[+] Discovered {len(urls_meta)} program URLs from sitemap.")
    return urls_meta

def infer_degree_level(name, credential="", schema_type=""):
    name_low = name.lower()
    cred_low = credential.lower()
    type_low = schema_type.lower()
    
    if any(k in name_low or k in cred_low for k in ["ph.d", "phd", "doctoral", "doctor of"]):
        return "Doctoral / Ph.D."
    elif any(k in name_low or k in cred_low for k in ["fellowship"]):
        return "Fellowship"
    elif any(k in name_low or k in cred_low for k in ["diploma", "certificate", "pg diploma", "post graduate diploma", "pgd"]):
        return "Diploma / Certificate"
    elif any(k in name_low or k in cred_low for k in ["m.tech", "m.sc", "m.a", "m.com", "mba", "m.b.a", "m.arch", "m.des", "ll.m", "llm", "mpt", "mot", "mph", "m.pharm", "md", "ms", "master", "m.ed", "m.optom"]):
        return "Postgraduate (PG)"
    elif any(k in name_low or k in cred_low for k in ["b.tech", "b.sc", "b.a", "b.com", "bba", "b.b.a", "b.arch", "b.des", "ll.b", "llb", "bpt", "bot", "b.pharm", "mbbs", "bds", "b.ed", "b.optom", "bachelor"]):
        return "Undergraduate (UG)"
    elif "master" in type_low:
        return "Postgraduate (PG)"
    elif "bachelor" in type_low:
        return "Undergraduate (UG)"
    else:
        return "Undergraduate (UG)" if "b." in name_low else ("Postgraduate (PG)" if "m." in name_low else "Specialized / Other")

def infer_credential(name):
    # Regex to extract degree credential prefix
    match = re.search(r'\b(B\.Tech|M\.Tech|B\.Sc|M\.Sc|B\.A|M\.A|B\.Com|M\.Com|BBA|MBA|B\.Arch|M\.Arch|B\.Des|M\.Des|LL\.B|LL\.M|BPT|MPT|BOT|MOT|B\.Pharm|M\.Pharm|Pharm\.D|MBBS|BDS|MD|MS|MDS|Ph\.D|MPH|B\.Ed|M\.Ed|PGD[A-Z]*)\b', name, re.IGNORECASE)
    if match:
        return match.group(0).upper()
    return ""

def clean_fees_numeric(fees_str):
    if not fees_str:
        return None
    # If it says "refer to" or doesn't have an explicit price
    if any(k in fees_str.lower() for k in ["refer to", "as per", "to be announced", "tba"]):
        return None
    # Remove academic years like 2024-2025, 2025-2026, 2026-2027
    cleaned_str = re.sub(r'202[0-9]\s*-\s*202[0-9]', '', fees_str)
    # Find all numeric digit groups with commas
    nums = re.findall(r'(\d[\d,]+)', cleaned_str)
    if nums:
        cleaned = nums[0].replace(',', '')
        try:
            val = int(cleaned)
            # Filter out standalone 4-digit years like 2024, 2025, 2026 if unlikely to be annual fee
            if val in [2022, 2023, 2024, 2025, 2026, 2027] and "₹" not in fees_str and "inr" not in fees_str.lower():
                return None
            return val
        except:
            return None
    return None

def parse_program_page(html, url, lastmod=""):
    soup = BeautifulSoup(html, 'html.parser')
    
    # 1. Program Name
    h1 = soup.find('h1')
    program_name = h1.get_text(strip=True) if h1 else ""
    if not program_name:
        title = soup.title.get_text(strip=True) if soup.title else ""
        program_name = title.split('–')[0].split('-')[0].strip()
        
    # Clean program name
    program_name = re.sub(r'\s+', ' ', program_name).strip()
    
    # 2. Schema.org JSON-LD parsing
    schema_desc = ""
    schema_credential = ""
    schema_type = ""
    career_ops = []
    
    for s in soup.find_all('script', type='application/ld+json'):
        if not s.string:
            continue
        try:
            data = json.loads(s.string)
            graph = data.get('@graph', [data]) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            for node in graph:
                if not isinstance(node, dict):
                    continue
                node_type = str(node.get('@type', ''))
                if "EducationalOccupationalProgram" in node_type or "Course" in node_type:
                    if not schema_desc and node.get('description'):
                        schema_desc = node.get('description')
                    if not schema_credential and node.get('educationalCredentialAwarded'):
                        schema_credential = str(node.get('educationalCredentialAwarded'))
                    if not schema_type and node.get('programType'):
                        schema_type = str(node.get('programType'))
                    if node.get('occupationalCategory'):
                        cats = node.get('occupationalCategory')
                        if isinstance(cats, list):
                            career_ops.extend(cats)
                        elif isinstance(cats, str):
                            career_ops.append(cats)
        except:
            pass

    # 3. Faculty & Department
    faculty = ""
    department = ""
    
    college_el = soup.find(class_=re.compile(r'item-college\b', re.I))
    if college_el:
        faculty = college_el.get_text(strip=True)
        
    dept_el = soup.find(class_=re.compile(r'item-department\b', re.I))
    if dept_el:
        department = dept_el.get_text(strip=True)
        
    # Fallback to breadcrumbs if not found
    if not faculty or not department:
        breadcrumb = soup.find(class_=re.compile(r'breadcrumb', re.I))
        if breadcrumb:
            b_texts = [re.sub(r'\s+', ' ', t).strip() for t in breadcrumb.stripped_strings]
            for it in b_texts:
                if not faculty and ("Faculty" in it or "College of" in it or "School of" in it):
                    faculty = it
                elif not department and "Department" in it:
                    department = it

    # Default fallback for faculty based on program name if still empty
    if not faculty:
        name_lower = program_name.lower()
        if "tech" in name_lower or "engineering" in name_lower:
            faculty = "Faculty of Engineering & Technology"
        elif "mba" in name_lower or "management" in name_lower:
            faculty = "Faculty of Management"
        elif "mbbs" in name_lower or "medicine" in name_lower or "health" in name_lower or "nursing" in name_lower or "pharmacy" in name_lower or "physiotherapy" in name_lower:
            faculty = "Medicine & Health Sciences"
        elif "law" in name_lower or "ll.b" in name_lower or "ll.m" in name_lower:
            faculty = "Faculty of Law"
        elif "agriculture" in name_lower:
            faculty = "College of Agriculture Sciences"
        else:
            faculty = "Faculty of Liberal Arts & Business Studies"

    # 4. Campus Offerings (Repeaters)
    offerings = []
    repeater = soup.find('div', class_=re.compile(r'program-repeater\b'))
    if repeater:
        container = repeater.find('div', class_=re.compile(r'jet-listing-grid__items')) or repeater
        posts_dict = {}
        for it in container.find_all('div', recursive=False):
            post_id = "default"
            for c in it.get('class', []):
                if c.startswith('jet-listing-dynamic-post-'):
                    post_id = c
                    break
            fields = it.find_all(class_=re.compile(r'dynamic-field__content'))
            texts = [f.get_text(strip=True) for f in fields]
            if len(texts) >= 2:
                lbl = texts[0].lower()
                val = texts[1]
                if post_id not in posts_dict:
                    posts_dict[post_id] = {"campus": "", "intake": "", "fees": "", "duration": ""}
                if "campus" in lbl:
                    posts_dict[post_id]["campus"] = val
                elif "intake" in lbl:
                    posts_dict[post_id]["intake"] = val
                elif "fee" in lbl:
                    posts_dict[post_id]["fees"] = val
                elif "duration" in lbl:
                    posts_dict[post_id]["duration"] = val
                    
        for pid, off in posts_dict.items():
            if any(off.values()):
                offerings.append(off)

    # 5. Summary metrics across offerings
    campuses_list = list(dict.fromkeys([o['campus'] for o in offerings if o.get('campus')]))
    campuses_str = ", ".join(campuses_list) if campuses_list else "Kattankulathur (Main Campus)"
    
    durations_list = list(dict.fromkeys([o['duration'] for o in offerings if o.get('duration')]))
    duration_str = ", ".join(durations_list) if durations_list else ""
    
    intakes_list = [o['intake'] for o in offerings if o.get('intake')]
    intake_str = ", ".join(intakes_list) if intakes_list else ""
    
    fees_list = [o['fees'] for o in offerings if o.get('fees')]
    fees_raw = ", ".join(fees_list) if fees_list else ""
    numeric_fees = [clean_fees_numeric(f) for f in fees_list if clean_fees_numeric(f)]
    annual_fees_inr = numeric_fees[0] if numeric_fees else None

    # 6. About the Program
    about_text = schema_desc
    about_h = soup.find(lambda el: el.name in ['h2', 'h3'] and 'about the program' in el.get_text().lower())
    if about_h:
        parent = about_h.find_parent('section') or about_h.find_parent('div')
        ps = parent.find_all(['p', 'span'])
        extracted = " ".join([re.sub(r'\s+', ' ', p.get_text(strip=True)) for p in ps if len(p.get_text(strip=True)) > 20])
        if extracted:
            about_text = extracted

    # 7. Eligibility Criteria
    eligibility_text = ""
    elig_h = soup.find(lambda el: el.name in ['h2', 'h3'] and 'eligibility' in el.get_text().lower())
    if elig_h:
        parent = elig_h.find_parent('section') or elig_h.find_parent('div')
        items = parent.find_all(['p', 'li'])
        clean_items = []
        for it in items:
            t = re.sub(r'\s+', ' ', it.get_text(strip=True))
            if t and not any(k in t.lower() for k in ["eligibility", "how to apply", "register", "step 1"]):
                clean_items.append(t)
        if clean_items:
            eligibility_text = " ".join(dict.fromkeys(clean_items))
        else:
            raw = parent.get_text(" ", strip=True).replace(elig_h.get_text(strip=True), "").strip()
            eligibility_text = re.sub(r'\s+', ' ', raw)

    # 8. Inferred fields
    credential = schema_credential or infer_credential(program_name)
    degree_level = infer_degree_level(program_name, credential, schema_type)

    return {
        "program_name": program_name,
        "degree_level": degree_level,
        "credential": credential,
        "faculty": faculty,
        "department": department,
        "campuses_available": campuses_str,
        "duration": duration_str,
        "sanctioned_intake": intake_str,
        "annual_fees_raw": fees_raw,
        "annual_fees_inr": annual_fees_inr,
        "eligibility_criteria": eligibility_text,
        "about_program": about_text,
        "career_opportunities": ", ".join(dict.fromkeys(career_ops)),
        "program_url": url,
        "last_updated": lastmod,
        "offerings": offerings
    }

def scrape_worker(item, session):
    url = item["url"]
    lastmod = item.get("lastmod", "")
    slug = url.strip('/').split('/')[-1]
    cache_file = os.path.join(CACHE_DIR, f"{slug}.html")
    
    html = None
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                html = f.read()
        except:
            html = None
            
    if not html:
        try:
            time.sleep(random.uniform(0.05, 0.15))
            r = session.get(url, timeout=15)
            if r.status_code == 200:
                html = r.text
                with open(cache_file, "w", encoding="utf-8") as f:
                    f.write(html)
            else:
                print(f"[!] Warning: HTTP {r.status_code} on {url}")
                return None
        except Exception as e:
            print(f"[!] Error fetching {url}: {e}")
            return None
            
    try:
        data = parse_program_page(html, url, lastmod)
        return data
    except Exception as e:
        print(f"[!] Error parsing {url}: {e}")
        return None

def main():
    print("="*70)
    print(" SRMIST Comprehensive Academic Programs Scraper & Master Generator ")
    print("="*70)
    
    session = get_session()
    urls_meta = fetch_sitemap_urls(session)
    total_urls = len(urls_meta)
    
    results = []
    print(f"\n[+] Starting parallel scraping with 12 workers...")
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(scrape_worker, item, session): item for item in urls_meta}
        completed = 0
        for fut in as_completed(futures):
            completed += 1
            res = fut.result()
            if res:
                results.append(res)
            if completed % 50 == 0 or completed == total_urls:
                elapsed = time.time() - start_time
                print(f"    Progress: {completed}/{total_urls} ({completed/total_urls*100:.1f}%) in {elapsed:.1f}s | Success: {len(results)}")

    print(f"\n[+] Scraping completed in {time.time() - start_time:.1f}s! Total valid programs: {len(results)}")
    
    # Sort results by degree_level and program_name
    results.sort(key=lambda x: (x['degree_level'], x['faculty'], x['program_name']))
    
    # Assign program_id
    for idx, item in enumerate(results, 1):
        item["program_id"] = idx

    # 1. Master Programs Dataset (Program-level)
    master_programs = []
    offerings_rows = []
    
    for item in results:
        p_row = {
            "Program ID": item["program_id"],
            "Program Name": item["program_name"],
            "Degree Level": item["degree_level"],
            "Credential": item["credential"],
            "Faculty / College": item["faculty"],
            "Department": item["department"],
            "Campuses Available": item["campuses_available"],
            "Duration": item["duration"],
            "Sanctioned Intake": item["sanctioned_intake"],
            "Annual Fees (INR)": item["annual_fees_inr"],
            "Annual Fees (Raw)": item["annual_fees_raw"],
            "Eligibility Criteria": item["eligibility_criteria"],
            "About Program": item["about_program"],
            "Career Opportunities": item["career_opportunities"],
            "Program URL": item["program_url"],
            "Last Modified": item["last_updated"]
        }
        master_programs.append(p_row)
        
        # Campus Offerings rows
        if item["offerings"]:
            for off in item["offerings"]:
                off_row = {
                    "Program ID": item["program_id"],
                    "Program Name": item["program_name"],
                    "Degree Level": item["degree_level"],
                    "Faculty / College": item["faculty"],
                    "Department": item["department"],
                    "Campus": off.get("campus") or "Main Campus",
                    "Sanctioned Intake": off.get("intake") or item["sanctioned_intake"],
                    "Annual Fees": off.get("fees") or item["annual_fees_raw"],
                    "Annual Fees (Numeric INR)": clean_fees_numeric(off.get("fees")) or item["annual_fees_inr"],
                    "Duration": off.get("duration") or item["duration"],
                    "Program URL": item["program_url"]
                }
                offerings_rows.append(off_row)
        else:
            offerings_rows.append({
                "Program ID": item["program_id"],
                "Program Name": item["program_name"],
                "Degree Level": item["degree_level"],
                "Faculty / College": item["faculty"],
                "Department": item["department"],
                "Campus": item["campuses_available"],
                "Sanctioned Intake": item["sanctioned_intake"],
                "Annual Fees": item["annual_fees_raw"],
                "Annual Fees (Numeric INR)": item["annual_fees_inr"],
                "Duration": item["duration"],
                "Program URL": item["program_url"]
            })

    # DataFrames
    df_programs = pd.DataFrame(master_programs)
    df_offerings = pd.DataFrame(offerings_rows)

    # 2. Save Master JSON
    json_path = os.path.join(BASE_DIR, "srmist_programs_master.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"[+] Saved Master JSON: {json_path} ({len(results)} programs)")

    # 3. Save Master CSVs
    csv_prog_path = os.path.join(BASE_DIR, "srmist_programs_master.csv")
    df_programs.to_csv(csv_prog_path, index=False, encoding="utf-8-sig")
    print(f"[+] Saved Master CSV: {csv_prog_path} ({len(df_programs)} rows)")

    csv_off_path = os.path.join(BASE_DIR, "srmist_campus_offerings_master.csv")
    df_offerings.to_csv(csv_off_path, index=False, encoding="utf-8-sig")
    print(f"[+] Saved Campus Offerings CSV: {csv_off_path} ({len(df_offerings)} rows)")

    # 4. Summary tables
    faculty_summary = df_programs.groupby("Faculty / College").agg(
        Total_Programs=("Program ID", "count"),
        Avg_Annual_Fee_INR=("Annual Fees (INR)", "mean")
    ).reset_index()
    faculty_summary["Avg_Annual_Fee_INR"] = faculty_summary["Avg_Annual_Fee_INR"].round(0)

    degree_summary = df_programs.groupby("Degree Level").agg(
        Total_Programs=("Program ID", "count"),
        Avg_Annual_Fee_INR=("Annual Fees (INR)", "mean")
    ).reset_index()
    degree_summary["Avg_Annual_Fee_INR"] = degree_summary["Avg_Annual_Fee_INR"].round(0)

    campus_summary = df_offerings.groupby("Campus").agg(
        Total_Offerings=("Program ID", "count")
    ).reset_index().sort_values(by="Total_Offerings", ascending=False)

    # 5. Save Formatted Excel Workbook
    xlsx_path = os.path.join(BASE_DIR, "srmist_programs_master.xlsx")
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df_programs.to_excel(writer, sheet_name="All Programs", index=False)
        df_offerings.to_excel(writer, sheet_name="Campus Offerings", index=False)
        faculty_summary.to_excel(writer, sheet_name="Faculty Summary", index=False)
        degree_summary.to_excel(writer, sheet_name="Degree Level Summary", index=False)
        campus_summary.to_excel(writer, sheet_name="Campus Summary", index=False)
        
    print(f"[+] Saved Formatted Master Excel: {xlsx_path} (5 sheets)")
    print("\n[✔] Data scraping and structured master files generation complete!")

if __name__ == "__main__":
    main()
