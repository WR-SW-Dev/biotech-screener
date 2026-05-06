# IR URL Population — Session Notes (2026-05-06)

## Problem

300/341 tickers in `production_data/company_ir_sources.json` had empty
`company_ir_url`. All 300 fell back to GNW keyword search
(`globenewswire.com/Search?keyword=TICKER`) — no issuer filter, produces
off-topic results, classifier routes them to "other". Result: `other_share=55.7%`,
FAIL threshold >50%.

## Technique: Two-pass IR URL sourcing

### Pass 1: EDGAR XBRL namespace extraction

EDGAR 8-K filings embed company XBRL namespaces in `.txt` files:
```
xmlns:fdmt="http://www.4dmoleculartherapeutics.com/20260325"
```
This is extractable via regex on the first 200KB of the text file.

**Key regex:**
```python
xbrl_domains = re.findall(
    r'xmlns[^=]*=\s*"(https?://(?:www\.)?[a-z0-9][a-z0-9\-\.]+\.[a-z]{2,6})/\d{8}"',
    content,
    re.IGNORECASE,
)
excluded = {"xbrl.org", "w3.org", "sec.gov", "fasb.org", "ifrs.org", "xbrl.sec.gov"}
company_domains = [d for d in xbrl_domains if not any(ex in d for ex in excluded)]
```

**EDGAR endpoint sequence:**
```
https://www.sec.gov/files/company_tickers.json         → ticker → CIK
https://data.sec.gov/submissions/CIK{padded}.json      → CIK → accession numbers
https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{acc}-index.htm
https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{acc}.txt
```

Note: `website` and `investorWebsite` fields in submissions JSON are empty for
virtually all biotech tickers. Do not use them.

### Pass 2: GNW search → JSON-LD

GNW redirects `/Search?keyword=X` to `/en/search/keyword/X`. Parse the HTML for
news-release links, fetch the first matching release, extract `author.url` from
JSON-LD `<script type="application/ld+json">`:

```python
blobs = re.findall(r'application/ld\+json[^>]*>(.*?)</script>', html, re.DOTALL)
for blob in blobs:
    d = json.loads(blob.strip())
    author = d.get("author", {})
    url = author.get("url", "") or author.get("@id", "")
    if url and "globenewswire.com" not in url:
        return url.rstrip("/")  # e.g. "http://4dmoleculartherapeutics.com"
```

### IR probe path ordering

Must try IR subdomains BEFORE company domain paths. Some companies have short
paths like `/ir` that redirect to science/technology pages:

Confirmed bad redirect: `kymeratx.com/ir` → science resource page (kw match=False)
Correct URL: `investors.kymeratx.com/investor-relations` (kw match=True)

**Tier 1 (try first):** `investors.`, `investor-relations.`, `ir.` subdomains
**Tier 2 (fallback):** company domain + path list

Also: require a keyword match (`"press release"`, `"news release"`, `"announcements"`,
`"investor news"`) on the 200 response, not just HTTP 200. Otherwise `/ir` type
redirects to non-IR pages get accepted.

### CRITICAL: Skip entire subdomain on first SSL/timeout error

When probing IR subdomains, if the first path on a subdomain hits SSLError or
ReadTimeout, ALL remaining paths on that subdomain will also fail (DNS resolves
but TLS is broken, or the host just doesn't listen). Skip the entire subdomain
immediately — don't try the remaining 12+ paths.

Confirmed failure: `investors.crisprtx.com` — first path gets SSLError, subsequent
paths all ReadTimeout (5s each). Naively probing all 13 paths = 75s stall per ticker.
With subdomain-skip: move to `ir.crisprtx.com` immediately → correct URL found.

**Implementation pattern:**
```python
# Group candidates by base URL (scheme://netloc)
by_base = defaultdict(list)
for candidate in candidates:
    p = urlparse(candidate)
    base_key = f"{p.scheme}://{p.netloc}"
    by_base[base_key].append(candidate)

for base_key, paths in by_base.items():
    skip_base = False
    for candidate in paths:
        if skip_base:
            break
        try:
            resp = requests.get(candidate, timeout=5, ...)
            ...
        except (SSLError, ReadTimeout, ConnectTimeout):
            skip_base = True  # abandon entire subdomain
        except RequestException:
            pass  # 404 etc — keep trying other paths on same base
```

Timeout: 5s per request (not 8s or 10s). Biotechs with broken IR subdomains hang
at the TCP/TLS layer and won't recover with more time.

## Confirmed results

| Ticker | Method | IR URL found |
|--------|--------|-------------|
| FDMT   | edgar_xbrl_probe | https://ir.4dmoleculartherapeutics.com/press-releases |
| KYMR   | edgar_xbrl_probe | https://investors.kymeratx.com/news-events/press-releases |
| IMVT   | edgar_xbrl_probe | https://www.immunovant.com/investors |
| CRSP   | edgar_xbrl_probe | https://ir.crisprtx.com/news-releases (investors.crisprtx.com SSL-dead, skipped) |
| CGON   | edgar_xbrl_probe | https://ir.cgoncology.com/ |
| ARTV   | edgar_xbrl_probe | https://www.artivabio.com/news/ |
| BCAX   | edgar_xbrl_probe | https://ir.bicara.com/ |
| PRAX   | edgar_xbrl_probe | https://investors.praxismedicines.com/press-releases |
| NMRA   | edgar_xbrl_probe | https://ir.neumoratx.com/ |
| ACRV   | edgar_xbrl_probe | https://ir.acrivon.com/ |
| ADMA   | edgar_xbrl_probe | https://ir.admabiologics.com/press-releases |
| ADPT   | edgar_xbrl_probe | https://investors.adaptivebiotech.com/investor-relations |
| AKTX   | edgar_xbrl_probe | http://akaritx.com/press-releases/ |
| ALDX   | edgar_xbrl_probe | https://ir.aldeyra.com/press-releases |
| CRMD   | edgar_xbrl_probe | http://cormedix.com/press-releases/ |
| CRNX   | edgar_xbrl_probe | https://crinetics.com/news-events/?filter=press-releases |
| VRTX   | edgar_xbrl_probe | https://investors.vrtx.com/investor-relations |

Note: ABUS had `globenewswire.com` in its XBRL namespace (unusual filer) — falls
through to Pass 2. AGIO domain found (`agios.com`) but IR probe failed — another
Pass 2 candidate. ALGS XBRL pointed to `imetrix.edgar-online.com` (third-party
filing aggregator) — filter this domain out as a known false positive.

## Live hit rate (2026-05-06 full run, observed)

Pass 1 checkpoints:
- 57/300: 74 hits (initial estimate ~65%)
- 113/300: 74 hits (65% hit rate)
- 145/300: 91 hits (63%)
- 171/300: 102 hits (60%)
- 217/300: 133 hits (61%)
- 265/300: 166 hits (63%)

Pass 1 settled at ~62-63% for 300 small/mid-cap biotech tickers (lower than the
initial 75-85% estimate from large-cap benchmarks like VRTX). Small-cap and recent
IPO filers have sparser 8-K XBRL history, pulling the hit rate down.

Pass 2 (GNW JSON-LD) was running on ~108 misses after Pass 1 completed. Early
checkpoints: 15/108 = ~5 additional hits, 32/108 = ~9 additional hits. Final
combined Pass 1+2 rate expected ~65-70%.

## Additional false-positive domain to filter

`imetrix.edgar-online.com` — third-party EDGAR filing aggregator, appears in XBRL
namespace for some tickers (confirmed ALGS). Add to `excluded` set in the regex filter:

```python
excluded = {"xbrl.org", "w3.org", "sec.gov", "fasb.org", "ifrs.org",
            "xbrl.sec.gov", "imetrix.edgar-online.com", "edgar-online.com"}
```

## API quirks

- GNW `/issuer/TICKER` → 404. GNW org IDs in news-release URL paths are release IDs, not stable org IDs.
- GNW `/Search?keyword=TICKER` → 301 redirect to `/en/search/keyword/TICKER`. Use the redirect URL directly.
- EDGAR rate limit best practice: include `User-Agent: WakeRobinBiotechScreener research@wakerobincapital.com`. 1.5s between requests.
- EDGAR submissions JSON `investorWebsite` field: empty for ~100% of tested biotechs (FDMT, MRNA, REGN, KYMR all empty).

## Script location and tool selection

**Use `tools/populate_ir_sources.py`** — NOT `tools/populate_ir_urls.py`.

Two scripts exist; they are different tools:
- `populate_ir_sources.py` — EDGAR 8-K XBRL extraction + GNW JSON-LD two-pass (the right one)
- `populate_ir_urls.py` — EDGAR `submissions/CIK*.json` investorWebsite field + URL slug pattern HEAD probing

`populate_ir_urls.py` pitfalls (why it fails):
- Uses EDGAR `investorWebsite`/`website` submission fields → empty for ~100% of biotechs
- Pattern HEAD probing on WSL2 stalls: Cloudflare 403s + 500ms delay × 9 slug patterns = hangs
- `--skip-head` flag exists but leaves only EDGAR misses → 0 results (confirmed: all 5 test tickers = `edgar_no_url`)

`populate_ir_sources.py` written 2026-05-06. Full run launched as background process.

## Running the full population job

```bash
# Smoke test one ticker first (15s)
python3 tools/populate_ir_sources.py --ticker VRTX --verbose

# Full run — launch as background job (90-120 min for 300 tickers)
# mcp_terminal background=True with notify_on_complete=True
python3 tools/populate_ir_sources.py --dry-run > artifacts/ir_url_population_run_YYYY-MM-DD.log 2>&1
# Then review log for summary, then re-run without --dry-run to apply

# Check progress while running
tail -f artifacts/ir_url_population_run_YYYY-MM-DD.log

# After completion: review artifacts/ir_url_population_YYYY-MM-DD.md for method breakdown
```

Observed pace: ~18s/ticker (EDGAR calls + subdomain probing + rate limit).
Expected runtime for 300 tickers: 90-120 min.
Output: updated `company_ir_sources.json` + `artifacts/ir_url_population_YYYY-MM-DD.md`.

## Code executor pitfall

`mcp_execute_code` using `terminal()` inside the sandbox returns empty output for
`mcp_terminal`-style commands -- the sandbox tool runs but produces nothing visible.
Use `mcp_terminal` directly for any shell commands against the screener repo.
`mcp_execute_code` is only reliable for pure-Python (no subprocess/terminal wrappers).
