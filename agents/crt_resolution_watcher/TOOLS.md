# TOOLS.md — CRT Resolution Watcher Agent

## Count resolutions

```bash
find data/snapshots/resolutions -name "*.json" -not -name "calibration*" -not -name "manual*" -not -name "watchlist*" | wc -l
```

## List recent resolutions

```bash
ls -lt data/snapshots/resolutions/2026-*/*.json | head -10
```

## Read a resolution record

```bash
cat data/snapshots/resolutions/2026-04/BIIB_2026-04-03.json
```

## Rebuild CRT×options join

```bash
python scripts/research/build_crt_options_join.py
```

Output: `output/catalyst_ev/crt_options_join.json`

## Rebuild event move table from CRT outcomes

```bash
python scripts/research/rebuild_event_move_table.py
```

Output: `data/research/event_move_table.json` (merged with existing)

## Check join table summary

```bash
python -c "import json; d=json.load(open('output/catalyst_ev/crt_options_join.json')); print(f'N={d[\"n_resolutions\"]}, opts={d[\"n_with_options\"]}, hard={d[\"n_hard_catalyst\"]}')"
```

## Cadence

- Daily after production run (18:00 ET)
- Immediate run when a new resolution file appears
