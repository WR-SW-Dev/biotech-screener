#!/usr/bin/env python3
"""yfinance 429 canary: lightweight rate-limit health check.

Probes 3 stable tickers and appends a JSONL status line to
logs/yfinance_canary.log. Intended to run every 30 min via cron so a
rate-limit event is detected before the 4:30 PM production run hits it.

Exit codes: 0 = OK, 1 = rate-limited or fetch failed.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

CANARY_TICKERS = ["AMGN", "IBB", "ABBV"]
LOG_PATH = Path(__file__).parent.parent / "logs" / "yfinance_canary.log"


def _probe() -> dict:
    hits = 0
    failed = []

    for ticker in CANARY_TICKERS:
        try:
            hist = yf.Ticker(ticker).history(period="1d")
            if hist is None or hist.empty:
                failed.append(ticker)
        except Exception as e:
            err = str(e)
            if "429" in err or "Too Many Requests" in err or "Expecting value" in err:
                hits += 1
            failed.append(ticker)

    ok = len(failed) == 0
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "status": "ok" if ok else ("rate_limited" if hits > 0 else "failed"),
        "rate_limit_hits": hits,
        "failed": failed,
    }


def main() -> int:
    result = _probe()

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(result) + "\n")

    if result["status"] != "ok":
        print(f"yfinance canary FAIL: {result}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
