from app.services.strategy import _normalize_alpaca_crypto_strategy_config


def test_alpaca_crypto_swap_create_payload_is_normalized_to_spot():
    exchange_config = {"exchange_id": "alpaca", "market_type": "swap"}
    trading_config = _normalize_alpaca_crypto_strategy_config(
        exchange_id="alpaca",
        market_category="Crypto",
        trading_config={"market_type": "swap", "symbol": "BTC/USD"},
        exchange_config=exchange_config,
    )

    assert trading_config["market_type"] == "spot"
    assert exchange_config["market_type"] == "spot"


def test_alpaca_crypto_perp_alias_is_normalized_to_spot():
    trading_config = _normalize_alpaca_crypto_strategy_config(
        exchange_id="alpaca",
        market_category="Crypto",
        trading_config={"market_type": "perpetual"},
    )

    assert trading_config["market_type"] == "spot"


def test_other_crypto_exchanges_keep_swap_market_type():
    trading_config = _normalize_alpaca_crypto_strategy_config(
        exchange_id="binance",
        market_category="Crypto",
        trading_config={"market_type": "swap"},
    )

    assert trading_config["market_type"] == "swap"


def test_alpaca_crypto_spot_cleans_exchange_config_market_type():
    exchange_config = {"exchange_id": "alpaca", "market_type": "swap"}
    trading_config = _normalize_alpaca_crypto_strategy_config(
        exchange_id="alpaca",
        market_category="Crypto",
        trading_config={"market_type": "spot"},
        exchange_config=exchange_config,
    )

    assert trading_config["market_type"] == "spot"
    assert exchange_config["market_type"] == "spot"


def test_unknown_alpaca_crypto_market_type_still_reaches_policy():
    trading_config = _normalize_alpaca_crypto_strategy_config(
        exchange_id="alpaca",
        market_category="Crypto",
        trading_config={"market_type": "margin"},
    )

    assert trading_config["market_type"] == "margin"
