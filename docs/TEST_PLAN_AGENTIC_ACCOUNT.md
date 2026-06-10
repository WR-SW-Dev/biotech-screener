# Test Plan: Agentic Account Trading System

## Overview

End-to-end testing of the two-stage review-first Robinhood trading system on the Agentic cash account ($100 buying power).

**Account Details:**
- Name: Agentic (individual cash account)
- Number: 802349084
- Type: Cash (no margin)
- Buying Power: $100
- Agentic Allowed: ✓ True (MCP trading enabled)

## Test Phases

### Phase 1: Stage 1 Dry-Run (Review Only)

**Goal:** Generate trade plan, verify blotter structure, no orders placed.

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener

# Option A: Conservative (top 15, $5 minimum order)
python3 tools/robinhood_top30_trade_plan_v2_mcp.py \
  --top-k 15 \
  --target-gross-dollars 100 \
  --account agentic \
  --min-order-dollars 5 \
  --dry-run

# Option B: Full diversification (top 30, fractional shares)
python3 tools/robinhood_top30_trade_plan_v2_mcp.py \
  --top-k 30 \
  --target-gross-dollars 100 \
  --account agentic \
  --min-order-dollars 1 \
  --dry-run
```

**Expected Output (Option A - top 15, $5 min):**
- ✓ Snapshot loaded (2026-06-10)
- ✓ 15 eligible tickers selected
- ✓ 15 orders generated (unless catalyst guardrail removes some)
- ✓ ~$6.67 per order (~$100 total gross)
- ✓ Includes all tiers (A/B/C) if catalyst ≥ 8 days
- ✓ Blotter saved to `artifacts/trading/robinhood_top15_plan_2026-06-10.json`

**Expected Output (Option B - top 30, $1 min, fractional):**
- ✓ Snapshot loaded (2026-06-10)
- ✓ 30 eligible tickers selected
- ✓ ~30 orders generated unless catalyst guardrail removes some
- ✓ ~$3.33 per order (~$100 total gross)
- ✓ Includes all tiers (A/B/C) if catalyst ≥ 8 days
- ✓ Fractional shares: e.g., 0.0667 shares @ $50 = $3.33
- ✓ Blotter saved to `artifacts/trading/robinhood_top30_plan_2026-06-10.json`

**Both options:**
- ✓ No orders placed
- ✓ Status: `PENDING_HUMAN_REVIEW`

**Verification:**
```bash
# Check blotter structure
cat artifacts/trading/robinhood_top15_plan_2026-06-10.json | jq '.metadata, .plan | keys'

# Expected:
# {
#   "timestamp": "2026-06-10T...",
#   "snapshot_date": "2026-06-10",
#   "mode": "DRY_RUN",
#   "top_k": 15,
#   "account": "agentic",
#   ...
# }
# Plan: n_orders, gross_notional_dollars, orders[]
```

---

### Phase 2: Blotter Inspection

**Goal:** Manually review generated orders, verify guardrails applied.

```bash
cat artifacts/trading/robinhood_top15_plan_2026-06-10.json | jq '.plan.orders | .[] | {ticker, quantity, estimated_price, notional_dollars, reason}'
```

**Checklist:**
- [ ] All tickers have catalyst ≥ 8 days
- [ ] Tier is included in order reason (informational, not filtering)
- [ ] Per-name notional ≤ 5% of $100
- [ ] All orders ≥ min order size ($1 for fractional, $5 for conservative)
- [ ] Tickers match top K screener picks (COGT rank 1, DNTH rank 2, etc.)
- [ ] Includes all tiers (A/B/C) if catalyst allows
- [ ] Fractional shares supported for small orders (e.g., 0.0667 shares)

**Example Acceptable Blotter (top 15, $5 min):**
```json
{
  "ticker": "COGT",
  "quantity": 0.1,
  "estimated_price": 50.0,
  "notional_dollars": 5.0,
  "reason": "Rank 1, Tier A"
}
```

**Example Acceptable Blotter (top 30, $1 min, fractional):**
```json
{
  "ticker": "COGT",
  "quantity": 0.0667,
  "estimated_price": 50.0,
  "notional_dollars": 3.33,
  "reason": "Rank 1, Tier A"
},
{
  "ticker": "DNTH",
  "quantity": 0.0666,
  "estimated_price": 50.0,
  "notional_dollars": 3.33,
  "reason": "Rank 2, Tier A"
}
```

Note: Robinhood may reject very small notional orders. Stage 2 will drop orders that fail `review_equity_order`.

---

### Phase 3: Stage 2 Execution (Dry-Run, No MCP)

**Goal:** Test approval flow (no actual orders, MCP stubs).

```bash
python3 tools/robinhood_execute_trades_v2_mcp.py \
  --blotter artifacts/trading/robinhood_top15_plan_2026-06-10.json \
  --account agentic \
  --account-number 802349084 \
  --skip-approval
```

**Expected Output:**
- ✓ Blotter loaded
- ✓ Orders reviewed (13 lines, "OK" status)
- ✓ Approval skipped (testing mode)
- ✓ Orders "placed" with stub order IDs
- ✓ Execution logged to `artifacts/trading/execution_YYYYMMDD_HHMMSS.json`

**Verification:**
```bash
# Check execution artifact
ls -lh artifacts/trading/execution_*.json
cat artifacts/trading/execution_*.json | jq '.placed_orders | .[] | {ticker, order_id, placed_at}'

# Expected: 13 orders with fake order IDs, status PENDING
```

---

### Phase 4: Approval Flow (Interactive Test)

**Goal:** Test human approval mechanism.

```bash
python3 tools/robinhood_execute_trades_v2_mcp.py \
  --blotter artifacts/trading/robinhood_top15_plan_2026-06-10.json \
  --account agentic
```

**Test 1: Cancel execution (no approval)**
```
Review the orders above carefully.

To proceed with LIVE execution, type exactly:
  EXECUTE APPROVED ORDERS

>> some other text

❌ Execution cancelled. Orders NOT placed.
```

✓ **Expected:** Script exits, no orders placed

**Test 2: Approve execution**
```
>> EXECUTE APPROVED ORDERS

✓  1. Placed: COGT   0.100 shares | Order ID: ORDER_COGT_abc12345
✓  2. Placed: DNTH   0.100 shares | Order ID: ORDER_DNTH_def67890
...
✓ Execution logged: artifacts/trading/execution_20260610_120000.json
✓ 13 orders placed successfully
```

✓ **Expected:** All orders logged, execution artifact created

---

## Phase 5: MCP Integration Test (Cloud Agent Context)

When running as a cloud agent, replace stubs with real MCP calls.

### 5a: Fetch Real Quotes

```python
# In robinhood_top30_trade_plan_v2_mcp.py

if args.fetch_real_quotes:
    # Call MCP to get quotes
    symbols = [pos["ticker"] for pos in eligible]
    quotes = mcp_tool_call("get_equity_quotes", {"symbols": symbols})
    quotes_map = {q["symbol"]: q["last_trade_price"] for q in quotes}
```

### 5b: Real review_equity_order

```python
# In robinhood_execute_trades_v2_mcp.py

review_result = mcp_tool_call("review_equity_order", {
    "account_number": "802349084",
    "symbol": "COGT",
    "side": "buy",
    "type": "market",
    "quantity": "0.1",
})

# Returns: {estimated_cost, current_price, buying_power, alerts}
```

### 5c: Real place_equity_order

```python
ref_id = str(uuid.uuid4())
place_result = mcp_tool_call("place_equity_order", {
    "account_number": "802349084",
    "symbol": "COGT",
    "side": "buy",
    "type": "market",
    "quantity": "0.1",
    "ref_id": ref_id,
})

# Returns: {id, status, estimated_cost, expires_at}
```

---

## Safety Checklist Before Live Execution

### Code-Level

- [ ] Stage 1 (`robinhood_top30_trade_plan_v2_mcp.py`):
  - [ ] Never calls `place_equity_order` or `review_equity_order`
  - [ ] Uses stub prices or fetches real quotes via MCP
  - [ ] Saves blotter to `artifacts/trading/` with timestamp
  - [ ] Status: `PENDING_HUMAN_REVIEW` (always)

- [ ] Stage 2 (`robinhood_execute_trades_v2_mcp.py`):
  - [ ] Calls `review_equity_order` before `place_equity_order`
  - [ ] Requires exact phrase: `EXECUTE APPROVED ORDERS`
  - [ ] Exits with status 0 if not approved
  - [ ] Uses UUIDs for `ref_id` (idempotency)
  - [ ] Logs execution to `artifacts/trading/execution_*.json`

### Account-Level

- [ ] Account number: `802349084` (Agentic, correct)
- [ ] Account type: Cash (no margin)
- [ ] Buying power: $100 (sufficient for $65-75 gross orders)
- [ ] Agentic allowed: ✓ True
- [ ] MCP authenticated: ✓ Confirmed (earlier transcript)

### Guardrail-Level

- [ ] No Tier C or lower tickers ✓
- [ ] No catalysts ≤7 days ✓
- [ ] Max 5% per name ($5) ✓
- [ ] Min order size $5 ✓
- [ ] Snapshot <3 days old ✓ (2026-06-10 current)

---

## Rollback Plan

If something goes wrong:

1. **Before Stage 2:** Delete the blotter, regenerate with Stage 1
2. **After Stage 2 (before MCP integration):** Stub orders don't affect account, safe to rerun
3. **After real MCP orders placed:** Contact Robinhood support with order IDs to cancel

---

## Success Criteria

**Phase 1 & 2 PASS:**
- Blotter generated correctly with catalyst guardrail (≥8d) applied
- 15 orders for top-15 ($100 gross, ~$6.67 each), unless catalyst removes some
- Includes all tiers (A/B/C) in orders; tier is informational only

**Phase 3 PASS:**
- Execution workflow runs without errors
- Approval flow blocks unmatched input
- Artifact logged correctly

**Phase 4 PASS:**
- Interactive approval works as expected
- Rejecting input prevents execution
- Accepting input logs execution

**Phase 5 PASS (after MCP integration):**
- Real quotes fetched correctly
- review_equity_order called, returns order review
- place_equity_order called after approval
- Real order IDs returned and logged

---

## Command Sequence (Copy-Paste Ready)

```bash
# Setup
cd /mnt/c/Projects/biotech_screener/biotech-screener

# Phase 1: Generate
python3 tools/robinhood_top30_trade_plan_v2_mcp.py \
  --top-k 15 \
  --target-gross-dollars 100 \
  --account agentic

# Phase 2: Inspect
jq '.plan.orders | length' artifacts/trading/robinhood_top15_plan_2026-06-10.json

# Phase 3: Test execution (skip approval)
python3 tools/robinhood_execute_trades_v2_mcp.py \
  --blotter artifacts/trading/robinhood_top15_plan_2026-06-10.json \
  --account agentic \
  --skip-approval

# Phase 4: Test approval flow (interactive)
python3 tools/robinhood_execute_trades_v2_mcp.py \
  --blotter artifacts/trading/robinhood_top15_plan_2026-06-10.json \
  --account agentic
# Type: EXECUTE APPROVED ORDERS (to approve)
```

---

## Known Limitations (v2 with Stubs)

- [ ] Real quotes not fetched (uses $50 stub)
- [ ] review_equity_order/place_equity_order stubbed
- [ ] No real orders placed
- [ ] No account balance updated

**Resolution:** Wire MCP in cloud agent context, test phases 5a-5c

---

## Questions?

If test fails at any phase, check:

1. **Snapshot missing?** → Run `run_phase2_daily.py` to generate
2. **Guardrails too strict?** → Adjust `--min-order-dollars`, `--max-single-name-pct`
3. **Blotter invalid?** → Check JSON structure with `jq`
4. **Approval not working?** → Ensure exact match: `EXECUTE APPROVED ORDERS`
5. **MCP not available?** → Running locally? Stage 1 dry-run still works with stubs

