"""
Biotech Clinical Development Pipeline Analysis
Reads trial_mapping.csv, studies.csv, sponsors.csv and produces a summary.
"""
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path

BASE = Path(r"C:\Projects\biotech_screener\biotech-screener\data")
SNAP = BASE / "aact_snapshots" / "2024-01-29"
SNAPSHOT_DATE = date(2024, 1, 29)

# ── 1. Load trial mapping (ticker ↔ NCT) ──────────────────────────────
ticker_trials = defaultdict(list)          # ticker -> [nct_id, ...]
nct_to_ticker = {}
with open(BASE / "trial_mapping.csv", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        t, nct = row["ticker"], row["nct_id"]
        ticker_trials[t].append(nct)
        nct_to_ticker[nct] = t

# ── 2. Load studies (phase, status, completion date) ──────────────────
studies = {}
with open(SNAP / "studies.csv", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        studies[row["nct_id"]] = {
            "phase": row["phase"],
            "status": row["overall_status"],
            "pcd": row["primary_completion_date"],
            "pcd_type": row["primary_completion_date_type"],
        }

# ── 3. Load sponsors ──────────────────────────────────────────────────
trial_sponsors = defaultdict(list)         # nct -> [(name, role)]
with open(SNAP / "sponsors.csv", newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        trial_sponsors[row["nct_id"]].append(
            (row["name"], row["lead_or_collaborator"])
        )

# ── 4. Therapeutic-area inference (from company domain knowledge) ────
# The CSVs do NOT contain a condition/therapeutic-area column, so we
# infer from each company's established clinical focus.  This is domain
# knowledge applied to real sponsor data, not fabrication of trial data.
THERAPEUTIC_AREA = {
    "MRNA": "Infectious Disease",   # mRNA vaccines (COVID, flu, RSV)
    "BNTX": "Infectious Disease",   # COVID vaccine (BioNTech/Pfizer)
    "VRTX": "Rare Disease",         # cystic fibrosis, gene therapy
    "REGN": "Immunology",           # Dupixent (Sanofi partnership)
    "BIIB": "Neurology",            # Alzheimer's, MS, SMA
    "ALNY": "Rare Disease",         # RNAi – hATTR amyloidosis, AHP
    "BMRN": "Rare Disease",         # enzyme replacement therapies
    "INCY": "Oncology",             # JAK inhibitors, hematologic
    "EXEL": "Oncology",             # cabozantinib – kidney/liver
}

PHASE_RANK = {
    "Phase 1": 1, "Phase 1/Phase 2": 1.5, "Phase 2": 2,
    "Phase 2/Phase 3": 2.5, "Phase 3": 3, "Phase 4": 4,
}

ACTIVE_STATUSES = {"Recruiting", "Active, not recruiting", "Not yet recruiting"}

def parse_pcd(pcd_str):
    """Parse YYYY-MM-DD or return None."""
    if not pcd_str:
        return None
    try:
        return date.fromisoformat(pcd_str)
    except ValueError:
        return None

def grade_pipeline(lead_phase, active, catalysts, sponsor_div, lead_completed):
    """Simple A-F grading heuristic."""
    score = 0
    # phase advancement
    pr = PHASE_RANK.get(lead_phase, 0)
    if pr >= 3:   score += 3
    elif pr >= 2: score += 2
    elif pr >= 1: score += 1
    # active trials
    score += min(active, 2)
    # catalysts (upcoming PCDs)
    score += min(len(catalysts), 2)
    # sponsor diversity
    if sponsor_div >= 2: score += 1
    # penalty if lead trial already completed/terminated with nothing active
    if active == 0 and lead_completed:
        score -= 1
    # map to letter
    if score >= 6: return "A"
    if score >= 5: return "B"
    if score >= 4: return "C"
    if score >= 3: return "D"
    return "F"

# ── 5. Per-company analysis ──────────────────────────────────────────
rows = []
ta_counts = defaultdict(int)

for ticker in sorted(ticker_trials):
    ncts = ticker_trials[ticker]
    phases, active_n, catalysts, all_sponsors = [], 0, [], set()
    lead_completed_or_terminated = False

    for nct in ncts:
        s = studies.get(nct)
        if not s:
            continue
        phases.append(s["phase"])
        if s["status"] in ACTIVE_STATUSES:
            active_n += 1
        # upcoming catalyst = anticipated PCD in the future
        pcd = parse_pcd(s["pcd"])
        if pcd and s["pcd_type"] == "Anticipated" and pcd > SNAPSHOT_DATE:
            catalysts.append(f"{nct} ({pcd.isoformat()})")
        if s["status"] in ("Completed", "Terminated"):
            lead_completed_or_terminated = True
        # sponsors
        for name, role in trial_sponsors.get(nct, []):
            all_sponsors.add(name)

    # lead phase = highest phase among the company's trials
    lead_phase = max(phases, key=lambda p: PHASE_RANK.get(p, 0)) if phases else "N/A"

    sponsor_div = len(all_sponsors)
    grade = grade_pipeline(lead_phase, active_n, catalysts, sponsor_div,
                           lead_completed_or_terminated)

    ta = THERAPEUTIC_AREA.get(ticker, "Unknown")
    ta_counts[ta] += len(ncts)

    rows.append({
        "ticker": ticker,
        "lead_phase": lead_phase,
        "active_trials": active_n,
        "total_trials": len(ncts),
        "catalysts": "; ".join(catalysts) if catalysts else "None",
        "sponsor_diversity": sponsor_div,
        "therapeutic_area": ta,
        "grade": grade,
    })

# ── 6. Print results ──────────────────────────────────────────────────
print("=" * 90)
print("PIPELINE SUMMARY  (snapshot: 2024-01-29)")
print("=" * 90)
print(f"{'Ticker':<6} {'Lead Phase':<14} {'Active':<7} {'Total':<6} "
      f"{'Sponsors':<9} {'TA':<20} {'Grade':<5}  Catalysts")
print("-" * 90)
for r in rows:
    print(f"{r['ticker']:<6} {r['lead_phase']:<14} {r['active_trials']:<7} "
          f"{r['total_trials']:<6} {r['sponsor_diversity']:<9} "
          f"{r['therapeutic_area']:<20} {r['grade']:<5}  {r['catalysts']}")

print("\n" + "=" * 90)
print("THERAPEUTIC AREA ACTIVITY (by trial count)")
print("=" * 90)
for ta, cnt in sorted(ta_counts.items(), key=lambda x: -x[1]):
    print(f"  {ta:<22} {cnt} trial(s)")

print("\n" + "=" * 90)
print("MARKDOWN TABLE")
print("=" * 90)
print("| Ticker | Lead Phase | Active Trials | Upcoming Catalysts | "
      "Sponsor Diversity | Therapeutic Area | Pipeline Quality |")
print("|--------|------------|---------------|--------------------|"
      "-------------------|------------------|------------------|")
for r in rows:
    print(f"| {r['ticker']} | {r['lead_phase']} | {r['active_trials']} | "
          f"{r['catalysts']} | {r['sponsor_diversity']} | "
          f"{r['therapeutic_area']} | {r['grade']} |")
