---
name: sci-cart-run
description: Run Scientific Cartography diagnostics for a given date. Usage: /sci-cart-run YYYY-MM-DD
---

Run the Scientific Cartography diagnostic wrapper for the given date.

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
python3 tools/run_scientific_cartography_diagnostics.py \
  --as-of-date {args} \
  --snapshot-dir data/snapshots/{args} \
  --ctgov-cache data/snapshots/{args}/inputs \
  --output-dir artifacts/scientific_cartography/{args}
```

After running, report:
- Success or failure
- Output artifact directory
- Program count loaded
- Stage coverage (known %)
- Mechanism coverage (known %)
- Ticker linkage (%)
- Any warnings or errors
