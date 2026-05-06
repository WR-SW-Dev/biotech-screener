"""Audit GNW Pass 2 hits from IR URL population log."""

import re

with open("artifacts/ir_url_population_run_2026-05-06.log") as f:
    content = f.read()
    lines = content.splitlines()

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
            results.append((ticker, gnw_domain, ir_url or "NONE"))
    i += 1

print(f"GNW Pass 2 attempts: {len(results)}")
print()
for ticker, domain, ir_url in results:
    print(f"{ticker:<12} src={domain}")
    print(f"             url={ir_url}")
