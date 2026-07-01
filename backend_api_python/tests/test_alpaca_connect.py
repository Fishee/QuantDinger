from decimal import ROUND_DOWN
from uuid import UUID
from unittest.mock import MagicMock, patch

from app.services.alpaca_trading.client import (
    AlpacaClient,
    AlpacaConfig,
    OrderResult,
    _alpaca_decimal_float,
    _as_str_id,
    _format_alpaca_error,
    _id_log_prefix,
    normalize_base_url,
)
from app.services.live_trading.execution import _place_alpaca_order


def test_as_str_id_from_uuid():
    uid = UUID("12345678-1234-5678-1234-567812345678")
    assert _as_str_id(uid) == "12345678-1234-5678-1234-567812345678"
    assert _id_log_prefix(uid) == "12345678-123"


@patch("app.services.alpaca_trading.client._ensure_alpaca")
def test_alpaca_connect_stores_string_account_id(mock_ensure):
    mock_modules = {
        "TradingClient": MagicMock(),
        "StockHistoricalDataClient": MagicMock(),
        "CryptoHistoricalDataClient": MagicMock(),
    }
    mock_ensure.return_value = mock_modules

    account = MagicMock()
    account.id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    account.status = "ACTIVE"

    trading = MagicMock()
    trading.get_account.return_value = account
    mock_modules["TradingClient"].return_value = trading

    client = AlpacaClient(
        AlpacaConfig(api_key="PKtest", secret_key="secret", paper=True)
    )
    assert client.connect() is True
    assert client._account_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert isinstance(client._account_id, str)


@patch("app.services.alpaca_trading.client._ensure_alpaca")
def test_alpaca_connect_does_not_fail_when_data_client_init_fails(mock_ensure):
    mock_modules = {
        "TradingClient": MagicMock(),
        "StockHistoricalDataClient": MagicMock(side_effect=TypeError("unexpected sandbox")),
        "CryptoHistoricalDataClient": MagicMock(side_effect=TypeError("unexpected sandbox")),
    }
    mock_ensure.return_value = mock_modules

    account = MagicMock()
    account.id = UUID("bbbbbbbb-cccc-dddd-eeee-ffffffffffff")
    account.status = "ACTIVE"

    trading = MagicMock()
    trading.get_account.return_value = account
    mock_modules["TradingClient"].return_value = trading

    client = AlpacaClient(AlpacaConfig(api_key="PKtest", secret_key="secret", paper=True))
    assert client.connect() is True
    assert client._account_id == "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"


def test_alpaca_normalize_base_url_ignores_data_and_stream_urls():
    assert normalize_base_url("https://data.alpaca.markets/v1beta3/crypto/us/bars") is None
    assert normalize_base_url("https://stream.data.alpaca.markets/v1beta3/crypto/us") is None
    assert normalize_base_url("wss://stream.data.alpaca.markets/v1beta3/crypto/us") is None


def test_alpaca_normalize_base_url_keeps_trading_hosts_host_level():
    assert normalize_base_url("https://paper-api.alpaca.markets/v2") == "https://paper-api.alpaca.markets"
    assert normalize_base_url("https://api.alpaca.markets/v2/account") == "https://api.alpaca.markets"


def test_alpaca_config_key_prefix_overrides_stale_paper_flag():
    assert AlpacaConfig(api_key="PKtest", secret_key="secret", paper=False).paper is True
    assert AlpacaConfig(api_key="AKtest", secret_key="secret", paper=True).paper is False


def test_alpaca_rest_400_error_mentions_trading_rest_base_url():
    msg = _format_alpaca_error(Exception("400 invalid syntax"), context="REST account")
    assert "trading REST" in msg
    assert "data.alpaca.markets" in msg


def test_alpaca_client_stores_connect_error():
    client = AlpacaClient(AlpacaConfig(api_key="", secret_key="", paper=True))

    assert client.connect() is False
    assert "empty api_key" in client.last_error


def test_alpaca_decimal_float_caps_order_precision():
    assert _alpaca_decimal_float("58200.0000000004") == 58200.0
    assert _alpaca_decimal_float("1.1234567899") == 1.12345679
    assert _alpaca_decimal_float("0.034121000000000004", rounding=ROUND_DOWN) == 0.034121


@patch("app.services.alpaca_trading.client.time.sleep")
@patch("app.services.alpaca_trading.client._ensure_alpaca")
def test_alpaca_limit_order_submits_normalized_precision(mock_ensure, _mock_sleep):
    class OrderSide:
        BUY = "buy"
        SELL = "sell"

    class TimeInForce:
        GTC = "gtc"
        DAY = "day"

    limit_request = MagicMock(return_value="limit-request")
    mock_ensure.return_value = {
        "LimitOrderRequest": limit_request,
        "OrderSide": OrderSide,
        "TimeInForce": TimeInForce,
    }

    order = MagicMock()
    order.id = "alp-1"
    order.filled_qty = "0"
    order.filled_avg_price = "0"
    order.status = "new"
    order.qty = "0.034121"
    order.submitted_at = ""

    trading = MagicMock()
    trading.submit_order.return_value = order
    trading.get_order_by_id.return_value = order

    client = AlpacaClient(AlpacaConfig(api_key="PKtest", secret_key="secret", paper=True))
    client._trading_client = trading
    client._account_id = "acct-1"

    result = client.place_limit_order(
        symbol="BTC/USD",
        side="buy",
        quantity=0.034121000000000004,
        price=58200.0000000004,
        market_type="crypto",
    )

    assert result.success is True
    assert limit_request.call_args.kwargs["qty"] == 0.034121
    assert limit_request.call_args.kwargs["limit_price"] == 58200.0


def test_place_alpaca_order_treats_slash_symbol_as_crypto():
    class FakeAlpaca:
        def place_market_order(self, **kwargs):
            self.kwargs = kwargs
            return OrderResult(
                success=True,
                order_id="alp-1",
                filled=0.01,
                avg_price=65000,
                status="filled",
                raw={},
            )

    client = FakeAlpaca()
    result = _place_alpaca_order(
        client,
        signal_type="open_long",
        symbol="BTC/USD",
        amount=0.01,
        exchange_config={"exchange_id": "alpaca", "market_type": "spot"},
        client_order_id="coid-1",
    )

    assert result.exchange_id == "alpaca"
    assert client.kwargs["market_type"] == "crypto"
    assert client.kwargs["client_order_id"] == "coid-1"
