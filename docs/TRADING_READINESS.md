# Trading System Readiness: Go / No-Go Status

## Summary

**Dry-run (blotter generation only): ✅ GO**
**Live execution (real MCP calls): ⏸ NO-GO (stubs only)**

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

- ✅ Tier C filtered out
- ✅ Catalyst ≤7 days filtered out
- ✅ Max 10% per name
- ✅ Min $1 order size
- ✅ No margin, no shorts, no options

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

### robinhood_execute_trades_v2_mcp.py

**Status:** ⏸ NO-GO (stubs only)

- Loads blotter ✅
- Prompts for approval ✅
- Has `review_and_place_orders()` with MCP comments (TODO: uncomment + wire)
- Generates fake order IDs ❌
- Does NOT call real Robinhood MCP tools ❌

**To use for real execution:**
- Uncomment the MCP calls in `review_and_place_orders()`
- Replace `review_equity_order_stub()` with real `mcp_call("review_equity_order", ...)`
- Replace `place_equity_order_stub()` with real `mcp_call("place_equity_order", ...)`
- Use returned `order_id` from real response

---

## Recommended Path to Live Trading

### Option A: Wire v2 Scripts (1-2 hours)

1. Update `fetch_real_quotes()` in `robinhood_top30_trade_plan_v2_mcp.py`
2. Update `review_and_place_orders()` in `robinhood_execute_trades_v2_mcp.py`
3. Test dry-run with real quotes
4. Test approval flow
5. Test live execution on Agentic account ($100)

### Option B: Build Claude Code Agent (2-4 hours, recommended)

1. Write a Claude Code agent that orchestrates the full flow
2. Agent calls:
   - `load_snapshot()` (local)
   - `mcp_call("get_equity_quotes", ...)` (real)
   - `mcp_call("get_portfolio", ...)` (real)
   - `mcp_call("review_equity_order", ...)` per order (real)
   - `mcp_call("place_equity_order", ...)` per order (real)
3. Agent handles all logic in one place (no executor script needed)
4. Direct access to MCP tools, no stubs

**Recommendation:** Option B is cleaner. The v2 scripts are reference implementations; the real system should call MCP directly.

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
✅ Real quotes (not stubs)
✅ Real Robinhood review before approval
✅ No orders placed without "EXECUTE APPROVED ORDERS"
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
