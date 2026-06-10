# Trading System Readiness: Go / No-Go Status

## Summary

**Stage 1 — Blotter Generation: ✅ GO** (real guardrails, stub prices)
**Stage 2 — Stub Simulator: ✅ PASS** (approval flow works, no real orders placed)
**Live Execution (real MCP calls): ❌ NO-GO** (requires Claude Code agent, not this script)

---

## Dry-Run: Blotter Generation ✅

The v2 scripts can generate a complete order blotter with all guardrails applied.

### Command

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener

python3 tools/robinhood_top30_trade_plan_v2_mcp.py \
  --top-k 15 \
  --target-gross-dollars 100 \
  --account agentic \
  --max-single-name-pct 10 \
  --min-order-dollars 1
```

### Output

- Loads latest biotech screener snapshot
- Selects top 15 eligible names (Tier A/B, catalyst ≥8 days)
- Allocates $100 equally across positions
- Generates blotter with:
  - ticker, rank, tier, catalyst_days
  - estimated_price (stub $50, **NOT real quotes**)
  - fractional_quantity
  - notional_dollars
- Saves JSON to `artifacts/trading/robinhood_top15_plan_YYYY-MM-DD.json`

### Guardrails Applied

- ✅ Catalyst ≤7 days filtered out (only guardrail on rank selection)
- ✅ Tier is informational only — A/B/C all included if catalyst ≥ 8 days
- ✅ Max 10% per name
- ✅ Min $1 order size
- ✅ No margin, no shorts, no options, no after-hours

### What It Does NOT Do

- ❌ Does NOT fetch real Robinhood quotes
- ❌ Does NOT check real buying power
- ❌ Does NOT call review_equity_order
- ❌ Does NOT place orders
- ❌ Uses stub prices ($50/share)

---

## Live Execution: Next Steps ⏸

For real $100 / top-15 trading, a Claude Code agent must:

1. **Load snapshot** (done in v2)
2. **Select top 15** (done in v2)
3. **Fetch real quotes** via `mcp_call("get_equity_quotes", {"symbols": tickers})`
4. **Get buying power** via `mcp_call("get_portfolio", {"account_number": "802349084"})`
5. **Scale orders** if buying power < target
6. **Call review_equity_order** for each proposed trade:
   ```
   review_result = mcp_call("review_equity_order", {
     "account_number": "802349084",
     "symbol": ticker,
     "side": "buy",
     "type": "market",
     "quantity": str(fractional_qty),
   })
   ```
7. **Handle rejections** (Robinhood may reject orders below minimum notional)
8. **Show revised blotter** to user with review results
9. **Require explicit approval**: "EXECUTE APPROVED ORDERS"
10. **Call place_equity_order** for each approved order:
    ```
    ref_id = uuid.uuid4()
    placed = mcp_call("place_equity_order", {
      "account_number": "802349084",
      "symbol": ticker,
      "side": "buy",
      "type": "market",
      "quantity": str(qty),
      "ref_id": str(ref_id),
    })
    ```
11. **Log order IDs** from returned results

---

## Current v2 Script Status

### robinhood_top30_trade_plan_v2_mcp.py

**Status:** ✅ READY for dry-run, ⏸ TODO for real quotes

- Generates blotters correctly
- Applies all guardrails
- Has `fetch_real_quotes()` hook (TODO: wire MCP call)
- Uses stubs by default

**To use with real quotes in a Claude Code agent:**
- Replace `fetch_real_quotes()` stub with actual `mcp_call("get_equity_quotes", ...)`

### robinhood_execute_trades_v2_mcp.py — STUB SIMULATOR ONLY

**Status:** ✅ PASS (stub simulation), ❌ NOT FOR LIVE TRADING

**What it does:**
- ✅ Loads blotter
- ✅ Reviews orders (all marked "OK")
- ✅ Prompts for explicit approval (`EXECUTE APPROVED ORDERS`)
- ✅ Simulates order placement with stub order IDs prefixed `STUB_ORDER_`
- ✅ Logs execution artifact with `execution_mode: "STUB_SIMULATION"` and `live_orders_placed: false`
- ✅ Prevents `--skip-approval + --live-mcp` combo
- ✅ Rejects `--live-mcp` flag with clear error message

**What it does NOT do:**
- ❌ Does NOT call real Robinhood MCP tools
- ❌ Does NOT place real orders
- ❌ Does NOT return real order IDs
- ❌ Does NOT update account balances

**Important:**
- This script is for **approval flow testing only**
- Stub PASS does **NOT** imply live trading readiness
- Stub order IDs (e.g., `STUB_ORDER_COGT_abc12345`) are NOT real Robinhood order IDs
- The artifact explicitly marks execution as stub simulation

**For real $100 / top-15 trading:**
- Use a Claude Code agent with direct Robinhood MCP calls (see "Option B" below)
- The agent must call:
  - `mcp__robinhood-trading__get_equity_quotes`
  - `mcp__robinhood-trading__review_equity_order`
  - `mcp__robinhood-trading__place_equity_order`
  - `mcp__robinhood-trading__get_portfolio` (for buying power check)

---

## LIVE TRADING REQUIRES CLAUDE CODE AGENT (Not This Script)

The stub scripts (`robinhood_top30_trade_plan_v2_mcp.py`, `robinhood_execute_trades_v2_mcp.py`) are for:
- ✅ Blotter generation and structure validation
- ✅ Guardrails testing
- ✅ Approval flow UX testing (with stubs)

They are **NOT** intended for live execution. To trade real dollars on the Agentic account:

### Build a Claude Code Agent

Write a Claude Code agent that:

1. **Loads the snapshot** → `load_snapshot()`
2. **Selects top K** → `select_top_k(portfolio, k=15)`
3. **Applies guardrails** → `apply_trading_guardrails(positions)`
4. **Fetches real quotes** → `mcp_call("get_equity_quotes", {"symbols": tickers})`
5. **Checks buying power** → `mcp_call("get_portfolio", {"account_number": "802349084"})`
6. **Reviews each order** → `mcp_call("review_equity_order", {...})` per order
7. **Shows user the blotter** with real prices, estimated costs, buying power
8. **Requires explicit approval** → User types exactly: `EXECUTE APPROVED ORDERS`
9. **Places orders** → `mcp_call("place_equity_order", {...})` per approved order
10. **Logs execution** with real order IDs and status

**Why this approach:**
- Direct access to real Robinhood MCP tools (no stubs)
- All decisions in one context (no script-to-script passing)
- Fail-closed on missing data (quotes, buying power, MCP availability)
- Full audit trail with real order IDs
- No confusion between stub and live execution

**Timeline:**
- Agent development: ~2-3 hours
- Testing on Agentic: ~1 hour
- Go-live: ~2026-06-12 (pending approval)

---

## Testing Checklist Before Live

- [ ] Snapshot loads correctly
- [ ] Top 15 selection works
- [ ] Guardrails filter correctly
- [ ] Real quotes fetch (not stubs)
- [ ] Fractional quantities calculated correctly
- [ ] Buying power check passes
- [ ] review_equity_order accepts all orders (or gracefully handles rejects)
- [ ] Blotter shows all details correctly
- [ ] Approval prompt requires exact phrase
- [ ] place_equity_order returns real order IDs
- [ ] Execution artifact logs order IDs

---

## Hard Rules (Non-Negotiable)

✅ Agentic account only ($100 cash limit)
✅ Buy-only (no sells)
✅ Fractional shares allowed
✅ Catalyst ≥ 8 days (imminent catalysts excluded)
✅ Real quotes (not stubs)
✅ Real Robinhood review before approval (stage 2)
✅ No orders placed without "EXECUTE APPROVED ORDERS"
✅ Tier is informational (all A/B/C included if catalyst allows)
✅ Fail-closed if snapshot/quote/cash/MCP missing

---

## Next Steps

1. **Immediate (now):** Use dry-run to generate blotter
   ```bash
   python3 tools/robinhood_top30_trade_plan_v2_mcp.py --top-k 15 --target-gross-dollars 100 --account agentic --min-order-dollars 1
   ```

2. **Near-term (1-2 days):** Build Claude Code agent with real MCP calls

3. **Testing (2-3 days):** Verify full flow on Agentic account

4. **Live (4-5 days):** Execute real $100 trade

---

## Files

- **Dry-run script:** `tools/robinhood_top30_trade_plan_v2_mcp.py`
- **Executor stub:** `tools/robinhood_execute_trades_v2_mcp.py` (reference only, has TODO comments)
- **Test plan:** `docs/TEST_PLAN_AGENTIC_ACCOUNT.md`
- **Operating guide:** `docs/ROBINHOOD_TRADING_GUIDE.md`
- **This doc:** `docs/TRADING_READINESS.md`
