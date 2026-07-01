#!/usr/bin/env python3
"""Check Alpaca trading REST credentials and crypto bars wiring."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.data_sources.factory import DataSourceFactory
from app.services.live_trading.factory import create_alpaca_client


def _env(*keys: str) -> str:
    for key in keys:
        value = os.getenv(key)
        if value and value.strip():
            return value.strip()
    return ""


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return value[:2] + "***"
    return value[:4] + "..." + value[-4:]


def main() -> int:
    api_key = _env("ALPACA_API_KEY", "APCA_API_KEY_ID", "ALPACA_KEY_ID")
    secret_key = _env("ALPACA_SECRET_KEY", "APCA_API_SECRET_KEY", "ALPACA_API_SECRET")
    base_url = _env("ALPACA_BASE_URL", "APCA_API_BASE_URL")
    if not api_key or not secret_key:
        print("Missing ALPACA_API_KEY/APCA_API_KEY_ID or ALPACA_SECRET_KEY/APCA_API_SECRET_KEY")
        return 2

    cfg = {
        "exchange_id": "alpaca",
        "api_key": api_key,
        "secret_key": secret_key,
        "base_url": base_url,
    }
    print(f"key={_mask(api_key)} base_url={base_url or '<empty>'}")

    try:
        client = create_alpaca_client(cfg)
        status = client.get_connection_status()
        print(f"trading_rest=OK host={status.get('base_url')} paper={status.get('paper')}")
    except Exception as exc:
        print(f"trading_rest=FAIL {exc}")
        return 1

    rows = DataSourceFactory.get_kline(
        market="Crypto",
        symbol="BTC/USD",
        timeframe="1m",
        limit=5,
        exchange_id="alpaca",
        market_type="spot",
        exchange_config=cfg,
    )
    print(f"crypto_bars={len(rows)}")
    if rows:
        print(f"first={rows[0]}")
        print(f"last={rows[-1]}")
    return 0 if len(rows) >= 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
