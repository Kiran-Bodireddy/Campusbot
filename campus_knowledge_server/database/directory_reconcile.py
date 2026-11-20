"""Reconciles faculty records with the official SRM faculty directory.

The graph's faculty list comes from data/srmist_faculty_cabins.csv. For about 150 people that file
disagrees with the official directory scraped from their SRM profile pages (data/faculty_master.csv):
e.g. a Tamil department head filed under "Department of CTech" with a Tech Park cabin. Records are
linked exactly through the profile URL. When the departments really differ (not just "CTech" vs
"Computing Technologies"), the directory wins for department, designation and email, and a
building-only cabin that was derived from the wrong department is cleared.
"""
import csv
import logging
import os
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

CABIN_NOT_LISTED = "Not listed in the faculty directory"


def _read(path: str) -> List[Dict[str, str]]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _key(name: str) -> str:
    name = (name or "").lower().replace("&", " and ").replace("\u2013", "-")
    name = re.sub(r"\b(department|centre|center|school|faculty) (of|for)\b", " ", name)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", name)).strip()


def _same_department(a: str, b: str, normalize) -> bool:
    if normalize(a) == normalize(b):
        return True
    ka, kb = _key(a), _key(b)
    if not ka or not kb:
        return True
    return ka in kb or kb in ka                              # "Language" ~ "Language, Culture and Society"


def reconcile_faculty(faculty: List[Dict[str, Any]], data_dir: str, normalize_department_name) -> int:
    cabins = _read(os.path.join(data_dir, "srmist_faculty_cabins.csv"))
    directory = _read(os.path.join(data_dir, "faculty_master.csv"))
    if not cabins or not directory:
        return 0
    by_url = {(r.get("profile_url") or "").rstrip("/").lower(): r for r in directory if r.get("profile_url")}
    url_by_fid = {(r.get("facultyId") or "").strip(): (r.get("profileUrl") or "").rstrip("/").lower() for r in cabins}

    fixed = 0
    for fac in faculty:
        d = by_url.get(url_by_fid.get(fac.get("faculty_id_official", ""), ""))
        if not d:
            continue
        dir_dept = re.sub(r"\s+", " ", d.get("department") or "").strip()
        if not dir_dept or "](" in dir_dept:
            continue
        if _same_department(dir_dept, fac.get("department", ""), normalize_department_name):
            continue                                            # same department, different spelling
        old = (fac.get("department"), fac.get("cabin"))
        fac["department_in_cabins_file"] = fac.get("department", "")
        fac["department"] = dir_dept
        fac["normalized_department"] = normalize_department_name(dir_dept)
        if d.get("designation"):
            fac["designation"] = re.sub(r"\s+", " ", d["designation"]).strip()
        if d.get("email") and d["email"].lower() != (fac.get("email") or "").lower():
            fac["email_in_cabins_file"] = fac.get("email", "")
            fac["email"] = d["email"].strip()
        if not re.search(r"\d", fac.get("cabin") or ""):        # building guessed from the wrong department
            fac["cabin"] = CABIN_NOT_LISTED
        fac["record_corrected_from"] = "official faculty directory (profile page)"
        fixed += 1
        logger.debug("Directory correction for %s: %s -> %s", fac.get("name"), old, (fac["department"], fac["cabin"]))
    return fixed
