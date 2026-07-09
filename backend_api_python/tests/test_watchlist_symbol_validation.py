from app.services.market import symbol_search, watchlist


class _CaptureCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def close(self):
        pass


class _CaptureConn:
    def __init__(self):
        self.cursor_obj = _CaptureCursor()
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True


def test_find_market_symbol_requires_exact_external_match(monkeypatch):
    monkeypatch.setattr(symbol_search, "seed_search_symbols", lambda **kwargs: [])
    monkeypatch.setattr(
        symbol_search,
        "_search_external_symbols",
        lambda market, keyword, limit, existing: [
            {"market": "USStock", "symbol": "AAP", "name": "Advance Auto Parts"}
        ],
    )

    assert symbol_search.find_market_symbol("USStock", "AAPL") is None


def test_find_market_symbol_accepts_exact_external_match(monkeypatch):
    monkeypatch.setattr(symbol_search, "seed_search_symbols", lambda **kwargs: [])
    monkeypatch.setattr(
        symbol_search,
        "_search_external_symbols",
        lambda market, keyword, limit, existing: [
            {"market": "USStock", "symbol": "AAPL", "name": "Apple Inc."}
        ],
    )

    assert symbol_search.find_market_symbol("USStock", "AAPL") == {
        "market": "USStock",
        "symbol": "AAPL",
        "name": "Apple Inc.",
    }


def test_crypto_search_keeps_seed_and_extends_with_usdc(monkeypatch):
    monkeypatch.setattr(
        symbol_search,
        "seed_search_symbols",
        lambda **kwargs: [{"market": "Crypto", "symbol": "BTC/USDT", "name": "Bitcoin"}],
    )
    monkeypatch.setattr(
        symbol_search,
        "_search_crypto_exchange",
        lambda keyword, limit, existing: [{"market": "Crypto", "symbol": "BTC/USDC", "name": "Bitcoin"}],
    )

    rows = symbol_search.search_market_symbols("Crypto", "BTC", 5)

    assert [r["symbol"] for r in rows] == ["BTC/USDT", "BTC/USDC"]


def test_crypto_usdc_explicit_pair_has_synthetic_fallback():
    rows = symbol_search._synthetic_crypto_pair_results("BTC/USDC", 5, set())

    assert rows == [{"market": "Crypto", "symbol": "BTC/USDC", "name": "Bitcoin"}]


def test_crypto_hot_symbols_reserve_usdc(monkeypatch):
    monkeypatch.setattr(
        symbol_search,
        "seed_get_hot_symbols",
        lambda **kwargs: [
            {"market": "Crypto", "symbol": f"COIN{i}/USDT", "name": f"Coin {i}"}
            for i in range(8)
        ],
    )

    rows = symbol_search.get_hot_symbols("Crypto", 8)
    symbols = [r["symbol"] for r in rows]

    assert len(rows) == 8
    assert "BTC/USDC" in symbols
    assert "ETH/USDC" in symbols


def test_crypto_hot_symbols_do_not_shrink_when_seed_already_has_usdc(monkeypatch):
    monkeypatch.setattr(
        symbol_search,
        "seed_get_hot_symbols",
        lambda **kwargs: [
            {"market": "Crypto", "symbol": "BTC/USDT", "name": "Bitcoin"},
            {"market": "Crypto", "symbol": "BTC/USDC", "name": "Bitcoin"},
            {"market": "Crypto", "symbol": "ETH/USDT", "name": "Ethereum"},
            {"market": "Crypto", "symbol": "ETH/USDC", "name": "Ethereum"},
        ],
    )

    rows = symbol_search.get_hot_symbols("Crypto", 4)

    assert [r["symbol"] for r in rows] == ["BTC/USDT", "BTC/USDC", "ETH/USDT", "ETH/USDC"]


def test_add_watchlist_rejects_crypto_symbol_not_in_registry(monkeypatch):
    monkeypatch.setattr(watchlist, "find_market_symbol", lambda market, symbol: None)
    monkeypatch.setattr(watchlist, "get_db_connection", lambda: (_ for _ in ()).throw(AssertionError("DB write should not happen")))

    ok, message = watchlist.add_watchlist_item(1, "Crypto", "AAPL")

    assert ok is False
    assert "AAPL/USDT" in message
    assert "not found on Crypto" in message


def test_add_watchlist_persists_only_after_exact_symbol_match(monkeypatch):
    conn = _CaptureConn()
    monkeypatch.setattr(
        watchlist,
        "find_market_symbol",
        lambda market, symbol: {"market": market, "symbol": symbol, "name": "Apple Inc."},
    )
    monkeypatch.setattr(watchlist, "persist_seed_name", lambda market, symbol, name: None)
    monkeypatch.setattr(watchlist, "get_db_connection", lambda: conn)

    ok, message = watchlist.add_watchlist_item(1, "USStock", "AAPL")

    assert ok is True
    assert message == "success"
    assert conn.committed is True
    assert conn.cursor_obj.executed
    _, params = conn.cursor_obj.executed[0]
    assert params == (1, "USStock", "AAPL", "Apple Inc.")
