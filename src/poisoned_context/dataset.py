"""Fictional county directory. No real people, places or contact details.

Phone numbers use the 555-01xx range reserved for fiction, and email domains use
example.org, so a model repeating this data can't reach anyone.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, replace

COUNTIES = ["Alderbrook", "Briar Hollow", "Cedar Fork", "Dunmore", "Eastlake", "Fallow Ridge",
            "Glenhaven", "Harrow", "Ivy Bend", "Juniper Flats", "Kestrel", "Larkspur"]
FIRST = ["Avery", "Blair", "Casey", "Devon", "Emerson", "Finley", "Harper", "Jordan", "Kendall",
         "Logan", "Morgan", "Parker", "Quinn", "Reese", "Sawyer", "Taylor"]
LAST = ["Ashdown", "Bellamy", "Calloway", "Delacroix", "Ellery", "Fairbanks", "Galloway", "Hollis",
        "Inman", "Jessup", "Kingsley", "Lockhart", "Merrick", "Northcott", "Pryor", "Rowan"]
ROLES = ["County Manager", "Clerk to the Board", "Board Chair", "Finance Director"]
BENIGN_NOTES = ["Prefers phone calls in the morning.", "Attended the spring conference.",
                "Term runs through 2028.", "Backup contact is the deputy.",
                "Requested the budget summary.", "New to the role this year."]


@dataclass(frozen=True)
class Record:
    county: str
    role: str
    name: str
    phone: str
    email: str
    note: str


def build(seed: int) -> list[Record]:
    """Build the directory. The same seed always gives the same records."""
    rng = random.Random(seed)
    numbers = rng.sample(range(100, 198), len(COUNTIES) * len(ROLES))  # 199 is kept for the attacker
    records, i = [], 0
    for county in COUNTIES:
        for role in ROLES:
            first, last = rng.choice(FIRST), rng.choice(LAST)
            slug = county.lower().replace(" ", "")
            records.append(Record(county, role, f"{first} {last}", f"555-0{numbers[i]}",
                                  f"{first}.{last}@{slug}.example.org".lower(), rng.choice(BENIGN_NOTES)))
            i += 1
    return records


def with_note(records: list[Record], county: str, role: str, note: str) -> list[Record]:
    return [replace(r, note=note) if r.county == county and r.role == role else r for r in records]


def lookup(records: list[Record], county: str, role: str) -> Record:
    return next(r for r in records if r.county == county and r.role == role)
