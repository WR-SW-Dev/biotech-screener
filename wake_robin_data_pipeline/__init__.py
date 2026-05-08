"""Wake Robin Data Pipeline - Market data providers with Morningstar integration."""

from .market_data_provider import BatchPriceProvider, PriceDataProvider, get_adv, get_log_returns
from .morningstar_data_provider import (
    MORNINGSTAR_AVAILABLE,
    BatchMorningstarProvider,
    MorningstarDataProvider,
    check_morningstar_availability,
    get_daily_returns,
    get_morningstar_daily_returns_schema,
    get_morningstar_data_sets,
    get_prices,
)

__all__ = [
    # Morningstar provider
    "MorningstarDataProvider",
    "BatchMorningstarProvider",
    "MORNINGSTAR_AVAILABLE",
    "check_morningstar_availability",
    "get_daily_returns",
    "get_morningstar_data_sets",
    "get_morningstar_daily_returns_schema",
    # Market data provider
    "PriceDataProvider",
    "BatchPriceProvider",
    "get_prices",
    "get_log_returns",
    "get_adv",
]
