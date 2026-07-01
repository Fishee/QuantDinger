from app.data_sources.alpaca_crypto import AlpacaCryptoDataSource
from app.data_sources.factory import DataSourceFactory


class _FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


def test_alpaca_crypto_source_formats_and_sorts_bars(monkeypatch):
    calls = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["url"] = url
        calls["params"] = params
        calls["headers"] = headers
        calls["timeout"] = timeout
        return _FakeResponse(
            {
                "bars": {
                    "BTC/USD": [
                        {
                            "t": "2026-06-30T10:01:00Z",
                            "o": 101,
                            "h": 103,
                            "l": 100,
                            "c": 102,
                            "v": 2.5,
                            "vw": 101.7,
                        },
                        {
                            "t": "2026-06-30T10:00:00.123456789Z",
                            "o": 100,
                            "h": 102,
                            "l": 99,
                            "c": 101,
                            "v": 1.5,
                            "vw": 100.7,
                        },
                    ]
                }
            }
        )

    monkeypatch.setattr("app.data_sources.alpaca_crypto.requests.get", fake_get)

    rows = DataSourceFactory.get_kline(
        market="Crypto",
        symbol="BTC/USDT",
        timeframe="1m",
        limit=5,
        exchange_id="alpaca",
        market_type="spot",
        exchange_config={"api_key": "key", "secret_key": "secret"},
    )

    assert calls["url"] == AlpacaCryptoDataSource.API_URL
    assert calls["params"]["symbols"] == "BTC/USD"
    assert calls["params"]["timeframe"] == "1Min"
    assert calls["params"]["limit"] == 5
    assert calls["headers"]["APCA-API-KEY-ID"] == "key"
    assert calls["headers"]["APCA-API-SECRET-KEY"] == "secret"
    assert [row["close"] for row in rows] == [101.0, 102.0]
    assert [row["time"] for row in rows] == sorted(row["time"] for row in rows)


def test_alpaca_crypto_source_maps_hour_and_day_timeframes(monkeypatch):
    seen_timeframes = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen_timeframes.append(params["timeframe"])
        return _FakeResponse(
            {
                "bars": {
                    "BTC/USD": [
                        {
                            "t": "2026-06-30T10:00:00Z",
                            "o": 100,
                            "h": 101,
                            "l": 99,
                            "c": 100.5,
                            "v": 1,
                        }
                    ]
                }
            }
        )

    monkeypatch.setattr("app.data_sources.alpaca_crypto.requests.get", fake_get)
    source = AlpacaCryptoDataSource({"api_key": "key", "secret_key": "secret"})

    assert source.get_kline("BTC/USD", "1h", 1)
    assert source.get_kline("BTC/USD", "1d", 1)
    assert seen_timeframes == ["1Hour", "1Day"]


def test_alpaca_crypto_source_request_failure_returns_empty(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse({"message": "bad request"}, status_code=400, text="bad request")

    monkeypatch.setattr("app.data_sources.alpaca_crypto.requests.get", fake_get)
    source = AlpacaCryptoDataSource({"api_key": "key", "secret_key": "secret"})

    assert source.get_kline("BTC/USD", "1m", 5) == []


def test_alpaca_crypto_live_before_time_uses_latest_bars_shape(monkeypatch):
    calls = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["params"] = dict(params or {})
        return _FakeResponse(
            {
                "bars": {
                    "BTC/USD": [
                        {
                            "t": "2026-06-30T10:00:00Z",
                            "o": 100,
                            "h": 101,
                            "l": 99,
                            "c": 100.5,
                            "v": 1,
                        }
                    ]
                }
            }
        )

    monkeypatch.setattr("app.data_sources.alpaca_crypto.requests.get", fake_get)
    monkeypatch.setattr("app.data_sources.alpaca_crypto.AlpacaCryptoDataSource._is_near_now", lambda ts: True)

    source = AlpacaCryptoDataSource({"api_key": "key", "secret_key": "secret"})
    assert source.get_kline("BTC/USD", "1m", 5, before_time=1)
    assert calls["params"] == {
        "symbols": "BTC/USD",
        "timeframe": "1Min",
        "limit": 5,
    }
