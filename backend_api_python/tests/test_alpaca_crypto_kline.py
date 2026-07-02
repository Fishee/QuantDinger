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
    assert source.get_kline("BTC/USD", "4h", 1)
    assert source.get_kline("BTC/USD", "1d", 1)
    assert seen_timeframes == ["1Hour", "4Hour", "1Day"]


def test_alpaca_crypto_source_falls_back_to_hourly_for_4h(monkeypatch):
    seen = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.append(dict(params or {}))
        if params["timeframe"] == "4Hour":
            return _FakeResponse({"message": "unsupported timeframe"}, status_code=400, text="unsupported")
        bars = []
        base_ts = 1_800_000_000
        for i in range(8):
            bars.append(
                {
                    "t": base_ts + i * 3600,
                    "o": 100 + i,
                    "h": 101 + i,
                    "l": 99 + i,
                    "c": 100.5 + i,
                    "v": 1 + i,
                }
            )
        return _FakeResponse({"bars": {"BTC/USD": bars}})

    monkeypatch.setattr("app.data_sources.alpaca_crypto.requests.get", fake_get)
    source = AlpacaCryptoDataSource({"api_key": "key", "secret_key": "secret"})

    rows = source.get_kline("BTC/USD", "4h", 2)

    assert [call["timeframe"] for call in seen] == ["4Hour", "1Hour"]
    assert seen[1]["limit"] == 8
    assert len(rows) == 2
    assert rows[0]["open"] == 100.0
    assert rows[0]["high"] == 104.0
    assert rows[0]["low"] == 99.0
    assert rows[0]["close"] == 103.5
    assert rows[0]["volume"] == 10.0
    assert rows[1]["open"] == 104.0
    assert rows[1]["close"] == 107.5


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
