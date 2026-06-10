# Robinhood Trading System — Review-First, Approval-Required

Two-stage execution system for biotech screener top-K portfolio construction.

## Quick Start

### Stage 1: Generate Trade Plan (Review Only)

```bash
python3 tools/robinhood_top30_trade_plan.py \
  --top-k 15 \
  --target-gross-dollars 100 \
  --account agentic
```

Output: Human-readable blotter + JSON artifact in `artifacts/trading/`

**Example output:**
```
✓ Loaded snapshot from 2026-06-10 (0 days old)
✓ Selected top 15 eligible tickers
✓ 13 positions pass guardrails

PROPOSED ORDERS
  1. BUY 0.100 COGT @ $50.00 = $5.00  (Rank 1, Tier A)
  2. BUY 0.100 DNTH @ $50.00 = $5.00  (Rank 2, Tier A)
  ... (11 more)

SUMMARY
  Orders: 13
  Gross Notional: $65.00
  Status: PENDING_HUMAN_REVIEW

✓ Blotter saved: artifacts/trading/robinhood_top15_plan_2026-06-10.json
```

### Stage 2: Review & Execute (Approval Required)

**Only after reviewing the blotter above:**

```bash
python3 tools/robinhood_execute_trades.py \
  --blotter artifacts/trading/robinhood_top15_plan_2026-06-10.json \
  --account agentic
```

Output: Each order reviewed, then **prompts for approval:**

```
ORDER REVIEW
✓  1. BUY 0.100 COGT @ $50.00 = $5.00
      Review: OK | Slippage: 5 bps
✓  2. BUY 0.100 DNTH @ $50.00 = $5.00
      Review: OK | Slippage: 5 bps
... (11 more)

⚠️  EXECUTION APPROVAL REQUIRED
Review the orders above carefully.
To proceed with LIVE execution, type exactly:
  EXECUTE APPROVED ORDERS

>> [TYPE HERE]
```

**Type exactly:** `EXECUTE APPROVED ORDERS`

Orders are placed, execution logged to `artifacts/trading/execution_*.json`.

## Guardrails Enforced

### Hard Execution Limits

- **No options, margin, shorts, crypto, after-hours**
- **Tier A/B only** — Tier C positions dropped
- **Catalyst ≥8 days** — avoid imminent catalysts in new positions
- **Max 5% per name** (configurable)
- **Min order size $5** (configurable)
- **Min cash reserve $5** (configurable)

### Fail-Closed Behavior

Script refuses to trade if:
- Snapshot is >7 days old
- Decision portfolio missing
- Account/holdings/cash data missing or stale

## Command-Line Reference

### Trade Plan Generation

```bash
python3 tools/robinhood_top30_trade_plan.py \
  [--snapshot latest|YYYY-MM-DD]    # Default: latest snapshot
  [--top-k N]                        # Default: 30
  [--account NAME]                   # agentic|roth|traditional|default
  [--target-gross-dollars AMOUNT]    # Default: 100.0
  [--max-single-name-pct PCT]        # Default: 5.0
  [--min-cash-reserve-dollars AMT]   # Default: 5.0
  [--min-order-dollars AMT]          # Default: 5.0
  [--allow-sells]                    # Allow selling non-screen holdings (default: false)
  [--dry-run]                        # Default: true (generate only)
```

### Order Execution

```bash
python3 tools/robinhood_execute_trades.py \
  --blotter PATH                     # Path to trade plan JSON
  [--account NAME]                   # Default: agentic
  [--skip-approval]                  # Skip approval prompt (testing only)
```

## Workflow Examples

### Example 1: Top 15, $100 Target, Agentic Account

```bash
# Stage 1: Generate
python3 tools/robinhood_top30_trade_plan.py \
  --top-k 15 \
  --target-gross-dollars 100 \
  --account agentic

# Review the blotter... then

# Stage 2: Execute
python3 tools/robinhood_execute_trades.py \
  --blotter artifacts/trading/robinhood_top15_plan_2026-06-10.json \
  --account agentic
```

### Example 2: Top 30, $500 Target, Roth IRA

```bash
# Generate (no execution)
python3 tools/robinhood_top30_trade_plan.py \
  --top-k 30 \
  --target-gross-dollars 500 \
  --account roth \
  --max-single-name-pct 3

# Review blotter, then execute
python3 tools/robinhood_execute_trades.py \
  --blotter artifacts/trading/robinhood_top30_plan_2026-06-10.json \
  --account roth
```

### Example 3: Single Name, Manual Approval

```bash
python3 tools/robinhood_top30_trade_plan.py \
  --top-k 1 \
  --target-gross-dollars 50 \
  --account agentic

python3 tools/robinhood_execute_trades.py \
  --blotter artifacts/trading/robinhood_top1_plan_2026-06-10.json
```

## Audit Trail

Every execution generates two JSON artifacts:

1. **Trade Plan** (Stage 1): `artifacts/trading/robinhood_topK_plan_YYYY-MM-DD.json`
   - Snapshot date, eligible tickers, guardrails, order list
   - Metadata: account, limits, mode (DRY_RUN/EXECUTION)

2. **Execution Log** (Stage 2): `artifacts/trading/execution_YYYYMMDD_HHMMSS.json`
   - Review results per order
   - Order IDs placed
   - Timestamp, approval status

## Design Principles

### 1. Review-First

No orders are placed by default. Generation (`--dry-run`) is the default.

### 2. Approval-Required

Execution requires explicit human input: `EXECUTE APPROVED ORDERS`.

### 3. Fail-Closed

If snapshot is stale, data is missing, or guardrails fail, the script exits with an error. It does not silently degrade or place orders.

### 4. Deterministic

Same snapshot + same parameters = same order list (no randomness).

### 5. Auditable

Every decision recorded in JSON artifacts with timestamps, guardrail decisions, and review results.

## Testing (Development)

```bash
# Generate without snapshot validation (for unit testing)
python3 tools/robinhood_top30_trade_plan.py --dry-run

# Execute with skipped approval (for CI/testing)
python3 tools/robinhood_execute_trades.py \
  --blotter artifacts/trading/... \
  --skip-approval
```

## Integration: Cloud Agent

(TODO) Set up a cloud routine that:

1. Runs `robinhood_top30_trade_plan.py` daily
2. Generates blotter
3. Posts blotter to Slack or email
4. Waits for human approval message
5. Calls `robinhood_execute_trades.py` on approval
6. Logs execution results

Example Slack approval flow:

```
Bot: Review the attached blotter.
     To approve, reply with: EXECUTE APPROVED ORDERS

User: EXECUTE APPROVED ORDERS

Bot: ✓ Orders placed. Execution logged.
```
