"""Audit GNW Pass 2 hits, classify good vs bad."""

import re

with open("artifacts/ir_url_population_run_2026-05-06.log") as f:
    lines = f.readlines()

results = []
i = 0
while i < len(lines):
    line = lines[i]
    if "company site via GNW JSON-LD" in line and "Pass 1" not in line:
        m = re.search(r"INFO\s+(\S+): company site via GNW JSON-LD = (.+)", line)
        if m:
            ticker = m.group(1)
            gnw_domain = m.group(2).strip()
            ir_url = None
            for j in range(i + 1, min(i + 5, len(lines))):
                m2 = re.search(r"INFO\s+" + re.escape(ticker) + r": IR URL = (.+)", lines[j])
                if m2:
                    ir_url = m2.group(1).strip()
                    break
            results.append((ticker, gnw_domain, ir_url))
    i += 1

BAD_SRC_KEYWORDS = [
    "law",
    "legal",
    "fistel",
    "pomerantz",
    "kuehn",
    "glancy",
    "kaskel",
    "royaltypharma",
    "standardbio",
    "orchestrabiomed",
    "dragonflyenergy",
    "bfalaw",
    "novabridge",
    "voyageracq",
    "temenos",
    "researchandmarkets",
    "snsinsider",
    "delveinsight",
    "prophecy",
    "usanewsgroup",
    "ownify",
    "anantara",
    "humaninterest",
    "usmint",
    "gildan",
    "virbac",
    "cerecor",
    "invaldalt",
    "prfoods",
    "lxp.com",
    "zlk.com",
    "virtualinvestor",
    "dawnproject",
    "irdirect",
    "er-kim",
    "georgetown.edu",
    "globenewswire.com/ir",
    "johnsonfistel",
    "preludetx",  # ABCL is AbCellera, not Prelude
    "castlebiosciences",  # SLN is Silence Therapeutics, not Castle
]

DEFINITELY_BAD = []
GOOD_WITH_URL = []
NO_URL = []

for ticker, domain, ir_url in results:
    domain_lower = domain.lower()
    is_bad_src = any(kw in domain_lower for kw in BAD_SRC_KEYWORDS)

    if is_bad_src and ir_url:
        DEFINITELY_BAD.append((ticker, domain, ir_url))
    elif ir_url:
        GOOD_WITH_URL.append((ticker, domain, ir_url))
    else:
        NO_URL.append((ticker, domain))

print("=== DEFINITELY BAD (wrong company URL assigned -- needs to be nulled) ===")
for t, d, u in DEFINITELY_BAD:
    print(f"  {t:<8}  src={d}")
    print(f"           url={u}")

print()
print("=== GOOD URLs ===")
for t, d, u in GOOD_WITH_URL:
    print(f"  {t:<8}  {u}")

print()
print(
    f"Summary: {len(DEFINITELY_BAD)} bad-with-url to null | {len(GOOD_WITH_URL)} good URLs | "
    f"{len(NO_URL)} stayed empty (fine)"
)
print()
print("Tickers to null:", [t for t, d, u in DEFINITELY_BAD])
