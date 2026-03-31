// Frontend prototype — Rankings Table + Ticker Detail
// Built 2026-03-31, uses actual backend field names for direct FastAPI swap
// See memory: frontend_prototype_2026_03_31.md for wiring instructions
//
// Dependencies: react, framer-motion, lucide-react, recharts, shadcn/ui
// This is a prototype reference file, not a buildable component yet.
// Wire to backend by replacing mock data arrays with fetch() calls.

// [Full prototype code saved from Claude Chat canvas session]
// See the canvas export for the complete implementation.
//
// Key design decisions:
// - Mock data uses exact field names from rankings.csv, decision_portfolio.csv,
//   shadow positions, options diagnostics, and CRT resolutions
// - Client-side merge layer over backend objects (no new schema)
// - Tabs: Overview, Options, Portfolio, CRT
// - Scatter plot: opt_rr_25d vs catalyst_days, colored by tier
// - Score context bar chart: clinical_optionality_pct_dev, alpha_cohort_pct, actual_implied_move_pctile
// - CRT outcome strip: HIT/MISS/EXOGENOUS polarity
//
// To wire to backend:
//   1. Replace rankingsRows with: fetch('/api/rankings?date=latest').then(r => r.json())
//   2. Replace decisionPortfolioRows with: fetch('/api/decision_portfolio?date=latest')
//   3. Replace shadowPortfolioPositions with: fetch('/api/positions?date=latest')
//   4. Replace optionsDiagnosticsRows with: fetch('/api/options_diagnostics?date=latest')
//   5. Replace crtResolutionRows with: fetch('/api/crt/resolutions')
//   6. mergeTickerData() stays client-side — it joins the 5 API responses by ticker
