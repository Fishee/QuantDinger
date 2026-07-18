import pytest

from app.services.strategy_v2 import StrategyV2ContractError, compile_strategy_v2, parse_instrument


def test_dataframe_result_cannot_be_used_as_a_boolean_condition():
    code = '''
def initialize(context):
    context.set_universe(["USStock:AAPL"])
    context.subscribe(frequency="1m")

def handle_data(context, data):
    bars = get_history(10, "1m", "close", "USStock:AAPL")
    if not bars:
        return
'''
    with pytest.raises(StrategyV2ContractError, match="strategyV2.dataframeTruthAmbiguous"):
        compile_strategy_v2(code)


def test_dataframe_result_explicit_length_check_is_allowed():
    code = '''
def initialize(context):
    context.set_universe(["USStock:AAPL"])
    context.subscribe(frequency="1m")

def handle_data(context, data):
    bars = get_history(10, "1m", "close", "USStock:AAPL")
    if len(bars) == 0:
        return
'''
    assert compile_strategy_v2(code).manifest.primary_frequency == "1m"


def test_instrument_parser_normalizes_ptrade_and_crypto_symbols():
    assert parse_instrument("600519.XSHG").key == "CNStock:600519.SH"
    assert parse_instrument("USStock:MSFT").key == "USStock:MSFT"
    assert parse_instrument("Crypto:BTCUSDT@okx:swap").key == "Crypto:BTC/USDT@okx:swap"
    assert parse_instrument("Crypto:BTC/USDT@swap").key == "Crypto:BTC/USDT@swap"


def test_manifest_discovers_static_multi_asset_strategy_and_schedule():
    code = """
def initialize(context):
    g.sec_dict = {
        "000063.XSHE": {"amount": 10000},
        "600519.XSHG": {"amount": 20000},
    }
    context.set_universe(list(g.sec_dict.keys()))
    context.subscribe(frequency="1d")
    context.set_warmup(60)
    run_daily(rebalance, time="09:35")

def rebalance(context, data=None):
    pass
"""
    compiled = compile_strategy_v2(code)
    manifest = compiled.manifest

    assert manifest.api_version == 2
    assert manifest.strategy_type == "portfolio"
    assert [item.symbol for item in manifest.universe.instruments] == ["000063.SZ", "600519.SH"]
    assert manifest.primary_frequency == "1d"
    assert manifest.warmup_bars == 60
    assert manifest.schedules[0].callback == "rebalance"
    assert manifest.schedules[0].time == "09:35"


def test_manifest_discovers_dynamic_index_universe_and_dependencies():
    code = """
def initialize(context):
    context.set_universe(index="000300.XBHS")
    context.subscribe(frequency="1d")
    run_weekly(rebalance, weekday=1, time="09:40")

def rebalance(context, data):
    scores = factor(["RSI", "ROE"])
    fundamentals = get_fundamentals(["PE", "PB"])
"""
    manifest = compile_strategy_v2(code).manifest

    assert manifest.strategy_type == "portfolio"
    assert manifest.universe.kind == "dynamic"
    assert manifest.universe.reference == "CNStock:000300.SH"
    assert manifest.factor_dependencies == ("ROE", "RSI")
    assert manifest.fundamental_dependencies == ("PB", "PE")
    assert manifest.schedules[0].frequency == "weekly"


def test_manifest_discovers_named_universe_pool():
    code = """
def initialize(context):
    context.set_universe(pool="sp500")
    context.subscribe(frequency="1d")
    run_weekly(rebalance)

def rebalance(context, data):
    for symbol in get_universe_stocks():
        order_target_percent(symbol, 0.0)
"""
    manifest = compile_strategy_v2(code).manifest

    assert manifest.strategy_type == "portfolio"
    assert manifest.universe.kind == "dynamic"
    assert manifest.universe.reference == "POOL:sp500"


def test_manifest_declares_contract_leverage_policy():
    code = """
def initialize(context):
    context.set_universe(["Crypto:BTC/USDT@okx:swap"])
    context.subscribe(frequency="1h")
    context.allow_leverage(5)

def handle_data(context, data):
    pass
"""
    manifest = compile_strategy_v2(code).manifest

    assert manifest.strategy_type == "cta"
    assert manifest.leverage_allowed is True
    assert manifest.max_leverage == 5
    assert manifest.primary_frequency == "1h"


def test_manifest_allows_exchange_agnostic_crypto_swap_leverage():
    code = """
def initialize(context):
    context.set_universe(["Crypto:BTC/USDT@swap"])
    context.subscribe(frequency="4h")
    context.allow_leverage(max_leverage=20)

def handle_data(context, data):
    pass
"""
    manifest = compile_strategy_v2(code).manifest

    assert manifest.leverage_allowed is True
    assert manifest.max_leverage == 20
    assert manifest.universe.instruments[0].exchange_id == ""
    assert manifest.universe.instruments[0].market_type == "swap"


def test_manifest_rejects_leverage_for_non_crypto_swap_instruments():
    for instrument in ("USStock:SPY", "Crypto:BTC/USDT@spot"):
        code = f"""
def initialize(context):
    context.set_universe(["{instrument}"])
    context.subscribe(frequency="1d")
    context.allow_leverage(2)

def handle_data(context, data):
    pass
"""
        try:
            compile_strategy_v2(code)
        except ValueError as exc:
            assert str(exc) == "strategyV2.leverageCryptoSwapOnly"
        else:
            raise AssertionError(f"leverage should be rejected for {instrument}")


def test_manifest_classifies_known_fundamental_factor_by_required_columns():
    code = """
def initialize(context):
    context.set_universe(index="INDEX:SP500")
    context.subscribe(frequency="1d")
    run_weekly(rebalance)

def rebalance(context, data):
    get_factors(get_index_stocks("INDEX:SP500"), "market_cap")
"""
    manifest = compile_strategy_v2(code).manifest

    assert manifest.factor_dependencies == ()
    assert manifest.fundamental_dependencies == ("MARKET_CAP",)
