"""Turns times in a question into the timetable slots they cover.

"8-9:45" -> 08:45-09:35 (+09:45-10:35 not included: it starts at 9:45)
"2pm to 4pm" -> 14:30-15:20, 15:30-16:20 (13:30-14:20 overlaps 2:00-2:20 too, so it is included)
"10am" / "at 10:45" -> the slot running at that time (or the next one to start)
Slots come from config/matching_config.yaml (timetable_slots), never hard-coded here.
"""
import re
from typing import List, Optional, Tuple

from campus_knowledge_server.config.matching_config import get_slot_number_map


def _slots() -> List[Tuple[int, int, str]]:
    out = []
    for _, rng in sorted(get_slot_number_map().items()):
        a, b = rng.split("-")
        out.append((_mins(a), _mins(b), rng))
    return out


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _to_minutes(h: str, m: Optional[str], ampm: Optional[str]) -> int:
    hour, minute = int(h), int(m or 0)
    ampm = (ampm or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    elif not ampm and 1 <= hour <= 7:          # campus day runs 08:45-16:20, so "2" means 2 pm
        hour += 12
    return hour * 60 + minute


_T = r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?"
_RANGE = re.compile(r"\b" + _T + r"\s*(?:-|–|to|and|till|until)\s*" + _T + r"\b", re.IGNORECASE)
_SINGLE = re.compile(r"\b(?:at|@|around|by)?\s*(\d{1,2})(?:[:.](\d{2}))\s*(am|pm)?\b|\b(\d{1,2})\s*(am|pm)\b", re.IGNORECASE)


def slots_for_query(text: str) -> Optional[List[str]]:
    """Slots (as 'HH:MM-HH:MM') covered by the time or time range in the text, or None if no time is given."""
    slots = _slots()
    m = _RANGE.search(text)
    if m:
        h1, m1, ap1, h2, m2, ap2 = m.groups()
        if ap2 and not ap1 and int(h1) <= int(h2):
            ap1 = ap2                                  # "2 to 4pm" -> both pm
        start, end = _to_minutes(h1, m1, ap1), _to_minutes(h2, m2, ap2)
        if end <= start:
            end += 12 * 60 if end + 12 * 60 > start else 0
        covered = [rng for a, b, rng in slots if a < end and b > start]
        if covered:
            return covered
        nxt = [rng for a, b, rng in slots if a >= start]
        return nxt[:1] or None
    m = _SINGLE.search(text)
    if m:
        if m.group(4):
            t = _to_minutes(m.group(4), None, m.group(5))
        else:
            t = _to_minutes(m.group(1), m.group(2), m.group(3))
        for a, b, rng in slots:
            if a <= t < b:
                return [rng]
        nxt = [rng for a, b, rng in slots if a >= t]
        return nxt[:1] or None
    return None
