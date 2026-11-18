"""
extract_syllabus_structured.py
-------------------------------
Extract structured course data from common-courses-syllabus-2021.pdf.
Outputs campus_knowledge_server/data/courses/syllabus_extracted.json.

After extraction, shows 3 sample records for user inspection before any Neo4j update.
"""

import re
import json
import sys
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # fallback


# ── paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "campus_knowledge_server" / "data" / "courses" / "common-courses-syllabus-2021.pdf"
COURSES_JSON = ROOT / "Datasets" / "courses.json"
OUT_PATH = ROOT / "campus_knowledge_server" / "data" / "courses" / "syllabus_extracted.json"

# Fix Windows path escape issues - use forward slashes
PDF_PATH = Path(str(PDF_PATH))
COURSES_JSON = Path(str(COURSES_JSON))
OUT_PATH = Path(str(OUT_PATH))


# ── noise patterns to strip ────────────────────────────────────────────────────
HEADER_RE = re.compile(
    r"^B\.Tech\s*/\s*M\.Tech.*Control\s*Copy\s*$",
    re.IGNORECASE | re.MULTILINE,
)
PAGE_NUM_RE = re.compile(r"^\d+\s*$", re.MULTILINE)

PO_COLUMN_WORDS = {
    "Engineering Knowledge", "Problem Analysis", "Design/development of solutions",
    "Design/development of", "Conduct investigations of complex problems",
    "Conduct investigations", "of complex problems", "Modern Tool Usage",
    "The engineer and society", "The engineer and", "Environment & Sustainability",
    "Environment &", "Sustainability", "Ethics", "Individual & Team Work",
    "Individual &", "Team Work", "Communication", "Project Mgt. & Finance",
    "Project Mgt.", "& Finance", "Life Long Learning", "PSO-1", "PSO-2", "PSO-3",
    "Program Outcomes (PO)", "Programme Outcomes (PO)",
    "Program\nSpecific\nOutcomes", "Program Specific Outcomes",
    "Program\nOutcomes", "Programme\nOutcomes",
}

# Additional inline PO-word fragments that contaminate CLR/CO text
# These appear adjacent (not on their own line) after the main text in the PDF stream
PO_INLINE_FRAGMENTS = re.compile(
    r"\s+(?:solutions?\s+of\s+complex\s+problems?|solutions|society|sustainability|ethics|communication|"
    r"team\s+work|individual\s*&?\s*team|modern\s+tool|environment\s*&?\s*sustainability|life\s+long|"
    r"project\s+mgt|engineering\s+knowledge|problem\s+analysis|"
    r"design\s*\/?\s*development\s+of|conduct\s+investigations?\s+of\s+complex|"
    r"conduct\s+investigations?|pso-\d+|&\s*finance|long\s+learning)"
    r"(?:\s+(?:solutions?\s+of\s+complex\s+problems?|solutions|society|sustainability|ethics|communication|"
    r"team\s+work|individual|modern\s+tool|environment|life\s+long|"
    r"project\s+mgt|engineering\s+knowledge|problem\s+analysis|"
    r"design\s*\/?\s*development|conduct\s+investigations?|pso-\d+|&\s*finance|long\s+learning))*\s*$",
    re.IGNORECASE,
)

# Lines that are purely PO mapping digits / dashes
PO_ROW_RE = re.compile(r"^[\d\s\-]+$")
# Line like "1 2 3 4 5 6 7 8 9 10 11 12"
PO_HEADER_NUM_RE = re.compile(r"^(\s*\d+\s*){4,}$")

COURSE_CODE_RE = re.compile(r"\b(21[A-Z]{2,3}\d{3,4}\s?[A-Z])\b")


def normalize_code(code: str) -> str:
    """Remove internal spaces from course codes like '21ECO101 T' -> '21ECO101T'."""
    return code.replace(" ", "")


def clean_text(raw: str) -> str:
    """Remove page headers and standalone page numbers only (preserve domain words in syllabus/textbooks)."""
    text = HEADER_RE.sub("", raw)
    text = PAGE_NUM_RE.sub("", text)
    return text


def _clean_clr_co_scope(scope: str) -> str:
    """Strip PO/PSO matrix header words and numeric mapping rows ONLY within CLR/CO sections."""
    text = scope
    # Strip multi-word and standalone-line PO headers (order longest first)
    for word in sorted(PO_COLUMN_WORDS, key=len, reverse=True):
        # For single generic words like 'Ethics' or 'Communication', only strip if on its own line
        if " " not in word and "\n" not in word and "-" not in word:
            text = re.sub(rf"(?m)^\s*{re.escape(word)}\s*$", "", text)
        else:
            text = text.replace(word, "")
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if PO_HEADER_NUM_RE.match(stripped):
            continue
        if PO_ROW_RE.match(stripped) and len(stripped) > 2:
            tokens = stripped.split()
            if len(tokens) >= 4:
                continue
        lines.append(line)
    return "\n".join(lines)


# ── section detectors ──────────────────────────────────────────────────────────
CLR_RE = re.compile(r"CLR-(\d+)\s*[:\.]?\s*(.*?)(?=CLR-\d+|CO-\d+|Unit[-\s]|Module[-\s]|Learning\s+Resources|Learning\s+Assessment|$)", re.DOTALL)
CO_RE  = re.compile(r"CO-(\d+)\s*[:\.]?\s*(.*?)(?=CO-\d+|Unit[-\s]|Module[-\s]|Learning\s+Resources|Learning\s+Assessment|$)", re.DOTALL)

UNIT_RE = re.compile(
    # Handles multiple formats:
    # Format A: "Unit-1 - Title\n9 Hours\n..." (dash separator, hours on next line)
    # Format B: "Unit-1 - Title       9 Hours\n..."  (dash, hours same line)
    # Format C: "Unit 1: Title\n9 Hours\n..." (colon separator, hours on next line)
    r"(?:Unit|Module)\s*-?\s*(\d+)\s*[-–:]\s*([^\n]+?)\s*\n?\s*(\d+)\s*Hour[s]?\s*\n(.*?)(?=(?:Unit|Module)\s*-?\s*\d+|Learning\s+Resources|Learning\s+Assessment|$)",
    re.DOTALL | re.IGNORECASE,
)

RESOURCES_RE = re.compile(
    r"Learning\s+Resources?\s*\n(.*?)(?=Learning\s+Assessment|Course\s+Designers|$)",
    re.DOTALL | re.IGNORECASE,
)
TEXTBOOK_LINE_RE = re.compile(r"^\s*(\d+)\.\s*(.+)$", re.MULTILINE)

ASSESSMENT_RE = re.compile(
    r"Learning\s+Assessment\s*(.*?)(?=Course\s+Designers|$)",
    re.DOTALL | re.IGNORECASE,
)
CLA1_RE  = re.compile(r"CLA-?1[^(]*\(?\s*(\d+)\s*%\s*\)?")
CLA2_RE  = re.compile(r"CLA-?2[^(]*\(?\s*(\d+)\s*%\s*\)?")
FINAL_RE = re.compile(r"(?:Final|Summative|Examination)[^(]*\(?\s*(\d+)\s*%\s*\)?")


def _strip_po_tail(text: str) -> str:
    """Remove trailing PO-mapping digits/dashes and stray PO column words from a CO/CLR line."""
    # strip trailing digit-dash rows first
    cleaned = re.sub(r"\s+([\d\-\s]+)$", "", text.strip()).strip()
    # strip inline PO-word noise appended by PDF column ordering
    cleaned = PO_INLINE_FRAGMENTS.sub("", cleaned).strip()
    # strip "Course Outcomes (CO): At the end..." if it leaked into CLR tail
    cleaned = re.sub(
        r"\s*Course\s+Outcomes?\s*\(?CO\)?\s*[:\.]?.*$",
        "", cleaned, flags=re.DOTALL | re.IGNORECASE,
    ).strip()
    # strip everything from "engineering knowledge" onwards (PO header paragraph leaked in full)
    cleaned = re.sub(
        r"\s+engineering\s+knowledge\b.*$",
        "", cleaned, flags=re.DOTALL | re.IGNORECASE,
    ).strip()
    return cleaned


def extract_header(page_text: str) -> dict:
    """Extract code, name, category, ltpc, dept, prereqs from page header."""
    result = {
        "code": None, "name": None, "category": None,
        "ltpc": None, "credits": None, "department": None,
        "prerequisites_raw": "Nil", "corequisites_raw": "Nil",
        "progressive_courses_raw": "Nil",
    }

    # Course code
    codes = COURSE_CODE_RE.findall(page_text)
    if codes:
        result["code"] = normalize_code(codes[0])

    # Name: appears after "Course\nName" or "CourseName" (may span multiple lines)
    name_m = re.search(
        r"Course\s*\n?\s*Name\s*\n?\s*([A-Z0-9][A-Z0-9 &,\-/\(\)–—:\n]+?)(?:\s*\n\s*Course|\s*\n\s*L\b)",
        page_text, re.IGNORECASE,
    )
    if name_m:
        clean_name = re.sub(r"\s+", " ", name_m.group(1)).strip()
        result["name"] = clean_name.title()

    # Category
    cat_m = re.search(r"Course\s*\n?\s*Category\s*\n?\s*([A-Z])\s*\n?\s*([A-Z ]+)", page_text)
    if cat_m:
        result["category"] = cat_m.group(2).strip().title()

    # LTPC
    ltpc_m = re.search(r"L\s*\n\s*T\s*\n\s*P\s*\n\s*C\s*\n\s*(\d)\s*\n\s*(\d)\s*\n\s*(\d)\s*\n\s*(\d)", page_text)
    if ltpc_m:
        l, t, p, c = ltpc_m.groups()
        result["ltpc"] = f"{l}-{t}-{p}-{c}"
        result["credits"] = int(c)

    # Department
    dept_m = re.search(r"Course\s+Offering\s+Department\s*\n?\s*(.+?)(?:\n|Data\s+Book)", page_text, re.IGNORECASE)
    if dept_m:
        result["department"] = dept_m.group(1).strip()

    # Pre/Co/Progressive
    pre_m = re.search(r"Pre-?requisite\s*\n?\s*Courses?\s*\n?\s*(.+?)(?:\n|Co-?\s*requisite)", page_text, re.IGNORECASE | re.DOTALL)
    if pre_m:
        result["prerequisites_raw"] = pre_m.group(1).strip()

    co_m = re.search(r"Co-?\s*requisite\s*\n?\s*Courses?\s*\n?\s*(.+?)(?:\n|Progressive)", page_text, re.IGNORECASE | re.DOTALL)
    if co_m:
        result["corequisites_raw"] = co_m.group(1).strip()

    prog_m = re.search(r"Progressive\s*\n?\s*Courses?\s*\n?\s*(.+?)(?:\n|Course\s+Offering)", page_text, re.IGNORECASE | re.DOTALL)
    if prog_m:
        result["progressive_courses_raw"] = prog_m.group(1).strip()

    return result


def extract_clrs(cleaned: str) -> list[str]:
    """Extract Course Learning Rationale items (CLR-1 to CLR-5 max)."""
    # Bound to the CLR section: between "Course Learning Rationale" and "Course Outcomes"
    clr_section_m = re.search(
        r"Course\s+Learning\s+Rationale.*?The\s+purpose\s+of\s+learning\s+this\s+course\s+is\s+to\s*:\s*\n(.*?)(?=Course\s+Outcomes?|$)",
        cleaned, re.DOTALL | re.IGNORECASE,
    )
    scope = _clean_clr_co_scope(clr_section_m.group(1) if clr_section_m else cleaned)

    clrs = []
    seen_nums = set()
    for m in CLR_RE.finditer(scope):
        n = int(m.group(1))
        if n in seen_nums or n > 5:
            break
        seen_nums.add(n)
        body = _strip_po_tail(m.group(2))
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            clrs.append(f"CLR-{n}: {body}")
    return clrs


def extract_cos(cleaned: str) -> list[str]:
    """Extract Course Outcome items."""
    cos = []
    # Try between "Course Outcomes" section header and next section
    co_section = re.search(
        r"Course\s+Outcomes?\s*\(CO\)[:\.]?.*?At the end.*?\n(.*?)(?=Unit[-\s\d]|Module[-\s\d]|Learning\s+Resources|Learning\s+Assessment)",
        cleaned, re.DOTALL | re.IGNORECASE,
    )
    scope = _clean_clr_co_scope(co_section.group(1) if co_section else cleaned)

    for m in CO_RE.finditer(scope):
        n = m.group(1)
        body = _strip_po_tail(m.group(2))
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            cos.append(f"CO-{n}: {body}")
    return cos


def extract_units(cleaned: str) -> list[dict]:
    """Extract syllabus units, stopping at first repeated unit number (cross-course bleed)."""
    units = []
    seen_nums = set()
    for m in UNIT_RE.finditer(cleaned):
        unit_num = int(m.group(1))
        # Stop if we see a repeated unit number (next course's units bleeding in)
        if unit_num in seen_nums:
            break
        seen_nums.add(unit_num)
        unit_title = m.group(2).strip().rstrip("-–—").strip()
        hours      = int(m.group(3))
        topics_raw = m.group(4)
        # Clean up topics
        topics = re.sub(r"\s+", " ", topics_raw).strip()
        # Remove Tutorial lines (keep only lecture topics)
        topics = re.sub(r"Tutorial\s*\n.*", "", topics, flags=re.DOTALL).strip()
        if topics:
            units.append({
                "unit": unit_num,
                "title": unit_title,
                "hours": hours,
                "topics": topics,
            })
    return units


def extract_textbooks(cleaned: str) -> list[str]:
    """Extract multi-line numbered textbook references cleanly."""
    res_m = RESOURCES_RE.search(cleaned)
    if not res_m:
        return []
    section = res_m.group(1)
    # Match each numbered entry across wrapped lines until the next numbered item or end
    entry_re = re.compile(r"(?m)^\s*\d+\.\s*(.*?)(?=^\s*\d+\.\s|\Z)", re.DOTALL)
    books = []
    for m in entry_re.finditer(section):
        citation = re.sub(r"\s+", " ", m.group(1)).strip()
        if len(citation) > 10:
            books.append(citation)
    return books


def extract_assessment(cleaned: str) -> dict:
    """Extract assessment weights."""
    result = {}
    ass_m = ASSESSMENT_RE.search(cleaned)
    if not ass_m:
        return result
    section = ass_m.group(1)
    m1 = CLA1_RE.search(section)
    m2 = CLA2_RE.search(section)
    mf = FINAL_RE.search(section)
    if m1:
        result["cla1_weight_pct"] = int(m1.group(1))
    if m2:
        result["cla2_weight_pct"] = int(m2.group(1))
    if mf:
        result["final_exam_weight_pct"] = int(mf.group(1))
    return result


def build_description(clrs: list[str], units: list[dict]) -> str:
    """Build a clean description paragraph from CLRs and unit titles."""
    parts = []
    if clrs:
        # First CLR gives the gist
        parts.append(clrs[0].replace("CLR-1: ", "").strip().capitalize() + ".")
    if units:
        titles = [u["title"] for u in units[:5]]
        parts.append("Topics covered: " + ", ".join(titles) + ".")
    return " ".join(parts)


# ── page grouping ──────────────────────────────────────────────────────────────

def group_pages(doc) -> list[tuple[int, str]]:
    """
    Return list of (start_page_idx, combined_text) for each course.
    A new course starts when a page contains a valid course code in its first 500 chars
    AND also has 'Course Outcomes' or 'CLR-' (i.e. not just TOC).
    """
    groups: list[tuple[int, str]] = []
    current_pages: list[str] = []
    current_start: int = -1

    for i in range(len(doc)):
        raw = doc[i].get_text()
        head = raw[:600]
        codes = COURSE_CODE_RE.findall(head)
        is_course_start = (
            codes
            and ("Course Outcomes" in raw or "CLR-" in raw or "CO-1" in raw)
            and ("Course\nName" in raw or "CourseName" in raw or "PROFESSIONAL" in raw
                 or "OPEN ELECTIVE" in raw or "PROFESSIONAL CORE" in raw
                 or "ELECTIVE" in raw or "Course\nCategory" in raw
                 or "Course \nCategory" in raw or "Course\n\nCategory" in raw
                 or re.search(r"Course\s+Category", raw))
        )
        if is_course_start:
            if current_pages and current_start >= 0:
                groups.append((current_start, "\n".join(current_pages)))
            current_pages = [raw]
            current_start = i
        else:
            if current_start >= 0:
                current_pages.append(raw)

    if current_pages and current_start >= 0:
        groups.append((current_start, "\n".join(current_pages)))

    return groups


# ── main extraction ────────────────────────────────────────────────────────────

def extract_all(pdf_path: Path) -> dict[str, dict]:
    doc = fitz.open(str(pdf_path))
    print(f"PDF opened: {len(doc)} pages")

    groups = group_pages(doc)
    print(f"Course blocks found: {len(groups)}")

    results: dict[str, dict] = {}
    skipped = 0

    for start_idx, raw_combined in groups:
        cleaned = clean_text(raw_combined)

        hdr = extract_header(raw_combined)   # use raw for header (regex on raw)
        code = hdr.get("code")
        if not code:
            skipped += 1
            continue
        code = normalize_code(code)

        clrs  = extract_clrs(cleaned)
        cos   = extract_cos(cleaned)
        units = extract_units(cleaned)
        books = extract_textbooks(cleaned)
        assessment = extract_assessment(cleaned)
        description = build_description(clrs, units)

        results[code] = {
            "code":                    code,
            "name":                    hdr["name"],
            "category":                hdr["category"],
            "ltpc":                    hdr["ltpc"],
            "credits":                 hdr["credits"],
            "department":              hdr["department"],
            "prerequisites_raw":       hdr["prerequisites_raw"],
            "corequisites_raw":        hdr["corequisites_raw"],
            "progressive_courses_raw": hdr["progressive_courses_raw"],
            "course_rationale":        clrs,
            "course_outcomes":         cos,
            "syllabus_units":          units,
            "textbooks":               books,
            "assessment_summary":      assessment,
            "description":             description,
            "has_detailed_syllabus":   True,
            "_pdf_start_page":         start_idx + 1,  # 1-indexed for debugging
        }

    print(f"Extracted: {len(results)} courses  |  Skipped (no code): {skipped}")
    return results


def coverage_report(extracted: dict[str, dict], courses_json: Path):
    """Print coverage stats."""
    with open(courses_json, encoding="utf-8") as f:
        graph_courses = json.load(f)

    graph_codes = {c["code"] for c in graph_courses}
    pdf_codes   = set(extracted.keys())

    overlap  = pdf_codes & graph_codes
    pdf_only = pdf_codes - graph_codes
    empty_co = [c for c, v in extracted.items() if not v["course_outcomes"]]

    print("\n── Coverage Report ──────────────────────────────────────")
    print(f"  Graph courses (courses.json): {len(graph_codes)}")
    print(f"  Extracted from PDF:           {len(pdf_codes)}")
    print(f"  Overlap (will update graph):  {len(overlap)}")
    print(f"  PDF-only (not in graph):      {len(pdf_only)}: {sorted(pdf_only)}")
    print(f"  Empty course_outcomes:        {len(empty_co)}: {empty_co[:10]}")
    print("─────────────────────────────────────────────────────────\n")
    return overlap, pdf_only, empty_co


def show_samples(extracted: dict[str, dict], codes: list[str]):
    """Pretty-print sample records for user inspection."""
    print("\n══════════════════════════════════════════════════════════")
    print("  SAMPLE RECORDS — please inspect before Neo4j update")
    print("══════════════════════════════════════════════════════════")
    for code in codes:
        rec = extracted.get(code)
        if not rec:
            print(f"  [{code}] NOT FOUND in extracted data\n")
            continue
        print(f"\n{'─'*60}")
        print(f"  Code:       {rec['code']}")
        print(f"  Name:       {rec['name']}")
        print(f"  Category:   {rec['category']}")
        print(f"  LTPC:       {rec['ltpc']}  Credits: {rec['credits']}")
        print(f"  Department: {rec['department']}")
        print(f"  Prereqs:    {rec['prerequisites_raw']}")
        print(f"  Coreqs:     {rec['corequisites_raw']}")
        print(f"  Progressive:{rec['progressive_courses_raw']}")
        print(f"\n  Course Rationale ({len(rec['course_rationale'])} items):")
        for clr in rec["course_rationale"]:
            print(f"    {clr}")
        print(f"\n  Course Outcomes ({len(rec['course_outcomes'])} items):")
        for co in rec["course_outcomes"]:
            print(f"    {co}")
        print(f"\n  Syllabus Units ({len(rec['syllabus_units'])} units):")
        for u in rec["syllabus_units"]:
            topics_preview = u["topics"][:120] + "..." if len(u["topics"]) > 120 else u["topics"]
            print(f"    Unit {u['unit']} [{u['hours']}h] {u['title']}")
            print(f"      {topics_preview}")
        print(f"\n  Textbooks ({len(rec['textbooks'])}):")
        for b in rec["textbooks"][:3]:
            print(f"    - {b[:100]}")
        print(f"\n  Assessment: {rec['assessment_summary']}")
        print(f"\n  Description (auto-built):")
        print(f"    {rec['description']}")
        print(f"  PDF start page: {rec['_pdf_start_page']}")


if __name__ == "__main__":
    print(f"PDF: {PDF_PATH}")
    print(f"Output: {OUT_PATH}\n")

    extracted = extract_all(PDF_PATH)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(extracted, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(extracted)} records → {OUT_PATH}")

    overlap, pdf_only, empty_co = coverage_report(extracted, COURSES_JSON)

    # Show 3 samples
    sample_codes = ["21CSC206T", "21CSO451T", "21IPC501J"]
    show_samples(extracted, sample_codes)

    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Inspect the records above. If they look correct,")
    print("  run the Neo4j update script next.")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
