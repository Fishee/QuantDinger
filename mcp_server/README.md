# QuantDinger MCP Server

The MCP server is a thin, tenant-scoped wrapper over `/api/agent/v1`. It exposes market data, chart-indicator authoring, Strategy API V2 deployment and backtesting, bounded job polling, runtime controls, and explicitly confirmed quick orders.

## Install and run

```bash
pip install -e ./mcp_server
export QUANTDINGER_BASE_URL=http://localhost:8888
export QUANTDINGER_AGENT_TOKEN=qd_agent_xxx
quantdinger-mcp
```

The default transport is `stdio`. Set `QUANTDINGER_MCP_TRANSPORT` to `sse` or `streamable-http` for a network transport. Optional limits include `QUANTDINGER_TIMEOUT_S`, `QUANTDINGER_MCP_JOB_STREAM_MAX_EVENTS`, `QUANTDINGER_MCP_JOB_STREAM_MAX_SECONDS`, and `QUANTDINGER_MCP_JOB_POLL_MAX_SECONDS`.

Never place an agent token in prompts, logs, screenshots, source control, or MCP configuration that will be shared. Responses redact credential fields, and clients must not attempt to recover them.

## Tool surface

| Tool group | Scope | Purpose |
|---|---:|---|
| `whoami`, `check_health` | R/public | Identity, allowlists, and liveness |
| `list_markets`, `search_symbols`, `get_klines`, `get_price` | R | Market discovery and data |
| `get_indicator_authoring_contract`, `validate_indicator_code`, `save_indicator`, `list_indicators`, `get_indicator` | R/W | Chart-only indicators |
| `create_strategy`, `update_strategy`, `list_strategies`, `get_strategy` | R/W | Strategy API V2 deployments |
| `submit_backtest` | B | Strategy API V2 backtest job |
| `list_jobs`, `get_job`, `wait_for_job`, `stream_job_until_done` | R | Bounded async-job access |
| `runtime_overview`, `stop_strategy` | R/T | Runtime inspection and confirmed stop |
| `place_quick_order` | T | Explicitly confirmed quick order |
| `list_portfolio_positions`, `list_paper_orders` | R | Portfolio and paper-order reads |

`stop_strategy` requires `confirm_stop=true`. `place_quick_order` requires `confirm_order=true`; a live-capable token also requires `confirm_live_trading=true`. Optional `tp_price` and `sl_price` protection are forwarded to the shared Quick Trade execution path. Server-side trading flags and token allowlists still apply; a live-capable token receives an error instead of silently falling back to paper when live trading is disabled.

## Strategy API V2 workflow

Executable strategy code must define `initialize(context)` and declare its universe and subscriptions. It must provide `handle_data`, `on_rebalance`, or a scheduled callback. The manifest owns instruments, markets, frequencies, factor dependencies, warmup, and leverage policy.

Create a stopped deployment from a saved source:

```text
create_strategy(
  name="btc-momentum",
  source_id=12,
  initial_capital=10000,
  execution_mode="signal",
  params={"lookback": 40}
)
```

Run a backtest directly from V2 code:

```text
submit_backtest(
  code="...Strategy API V2 Python...",
  start_date="2025-01-01",
  end_date="2025-12-31",
  initial_capital=10000,
  params={"lookback": 40},
  idempotency_key="btc-momentum-2025"
)
```

Market, symbol, and timeframe are not backtest parameters. They come from the compiled strategy manifest. Use `wait_for_job` or `stream_job_until_done` to obtain the result.

Indicators are chart-only. Validate and save them through the indicator tools, then convert the idea into Strategy API V2 code before using `submit_backtest` or `create_strategy`.

## Development

```bash
pip install -e './mcp_server[dev]'
pytest mcp_server/tests
```
