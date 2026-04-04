"""Bayesian Biotech Event EV Engine (Spec 057).

Research-only parallel engine for modeling biotech catalysts as
probabilistic events with scenario expected value.

Six layers:
    1. Catalyst Graph   — unified event object
    2. Timing Hazard    — when it will really happen
    3. Outcome Model    — HIT / MISS / MIXED probabilities
    4. Expectation      — what the market already prices
    5. Payoff Engine    — branch-conditional moves + EV
    6. Portfolio Layer  — risk-adjusted sizing

Usage:
    from event_ev.ev_calculator import EventEVCalculator
    calc = EventEVCalculator(as_of_date=date(2026, 4, 4))
    results = calc.run(catalyst_nodes, market_data)
"""

__version__ = "0.1.0"
