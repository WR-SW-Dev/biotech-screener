# Fixture for feature-exports.yml (semgrep --test pairs by filename).
#
# One SNAPSHOT_COLUMNS tuple exercises all four rules at once: priced_move_pct
# is OMITTED (its rule must fire), the other three are PRESENT (their rules
# must stay silent — proving the pattern-not-regex required-substring logic).

# ruleid: rankings-required-field-priced_move_pct
SNAPSHOT_COLUMNS = (
    "short_interest_pct",
    "close_price",
    "market_cap_mm",
    # priced_move_pct intentionally omitted
)
