"""Alpaca crypto market-data source."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from app.data_sources.base import BaseDataSource, TIMEFRAME_SECONDS
from app.services.alpaca_trading.symbols import normalize_symbol
from app.utils.logger import get_logger

logger = get_logger(__name__)


_FRACTIONAL_SECONDS_RE = re.compile(r"\.(\d{6})\d+")


class AlpacaCryptoDataSource(BaseDataSource):
    """Fetch Alpaca crypto spot bars from the v1beta3 data API."""

    name = "Alpaca/Crypto"
    API_URL = "https://data.alpaca.markets/v1beta3/crypto/us/bars"

    TIMEFRAME_MAP = {
        "1m": "1Min",
        "5m": "5Min",
        "15m": "15Min",
        "30m": "30Min",
        "1h": "1Hour",
        "1H": "1Hour",
        "4h": "4Hour",
        "4H": "4Hour",
        "1d": "1Day",
        "1D": "1Day",
    }

    def __init__(
        self,
        exchange_config: Optional[Dict[str, Any]] = None,
        *,
        timeout: Optional[float] = None,
    ):
        self.exchange_config = exchange_config if isinstance(exchange_config, dict) else {}
        self.timeout = timeout if timeout is not None else self._env_timeout()

    def get_kline(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        before_time: Optional[int] = None,
        after_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch Alpaca crypto spot K-lines and normalize them to QuantDinger rows."""
        klines: List[Dict[str, Any]] = []
        alpaca_symbol = normalize_symbol(symbol, "crypto", market_hint="Crypto")
        alpaca_timeframe = self._alpaca_timeframe(timeframe)

        if not alpaca_symbol:
            logger.warning("Alpaca crypto bars: empty symbol from %r", symbol)
            return []
        if not alpaca_timeframe:
            logger.warning(
                "Alpaca crypto bars: unsupported timeframe=%r for symbol=%s",
                timeframe,
                alpaca_symbol,
            )
            return []

        try:
            request_limit = max(1, min(int(limit or 1), 10000))
        except Exception:
            request_limit = 1

        raw_bars = self._request_raw_bars(
            alpaca_symbol,
            alpaca_timeframe,
            request_limit,
            timeframe,
            before_time,
            after_time,
        )
        resample_bucket = 1
        source_request_limit = request_limit
        if not raw_bars and self._qd_timeframe(timeframe) == "4H":
            # Some Alpaca deployments accept 4Hour directly; others do not.
            # Fall back to 1Hour bars and aggregate into 4H buckets.
            source_request_limit = max(4, min(10000, request_limit * 4))
            logger.warning(
                "Alpaca crypto bars: falling back to 1Hour source for 4H resample "
                "symbol=%s limit=%s",
                alpaca_symbol,
                source_request_limit,
            )
            raw_bars = self._request_raw_bars(
                alpaca_symbol,
                "1Hour",
                source_request_limit,
                "1h",
                before_time,
                after_time,
            )
            resample_bucket = 4

        if not raw_bars:
            logger.warning(
                "Alpaca crypto bars: no bars returned for symbol=%s timeframe=%s limit=%s",
                alpaca_symbol,
                alpaca_timeframe,
                request_limit,
            )
            return []
        logger.info(
            "Alpaca crypto bars response: symbol=%s timeframe=%s raw_bars=%s",
            alpaca_symbol,
            alpaca_timeframe,
            len(raw_bars),
        )

        klines = self._format_raw_bars(raw_bars)
        if resample_bucket > 1:
            before = len(klines)
            klines = self._merge_every_n_sorted_bars(klines, resample_bucket)
            logger.info(
                "Alpaca crypto bars resampled: symbol=%s source=1Hour target=4H source_rows=%s rows=%s",
                alpaca_symbol,
                before,
                len(klines),
            )

        klines = self.filter_and_limit(
            klines,
            request_limit,
            before_time,
            after_time,
            truncate=(after_time is None),
        )
        self.log_result(alpaca_symbol, klines, self._qd_timeframe(timeframe))
        logger.info(
            "Alpaca crypto bars normalized: symbol=%s timeframe=%s rows=%s",
            alpaca_symbol,
            alpaca_timeframe,
            len(klines),
        )
        return klines

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Best-effort ticker from the latest 1-minute Alpaca crypto bar."""
        bars = self.get_kline(symbol, "1m", 1)
        if not bars:
            return {"last": 0, "symbol": symbol}
        latest = bars[-1]
        return {
            "last": latest.get("close", 0),
            "close": latest.get("close", 0),
            "open": latest.get("open", 0),
            "high": latest.get("high", 0),
            "low": latest.get("low", 0),
            "volume": latest.get("volume", 0),
            "symbol": normalize_symbol(symbol, "crypto", market_hint="Crypto"),
        }

    @classmethod
    def _alpaca_timeframe(cls, timeframe: str) -> Optional[str]:
        key = str(timeframe or "").strip()
        if key in cls.TIMEFRAME_MAP:
            return cls.TIMEFRAME_MAP[key]
        lower = key.lower()
        if lower in cls.TIMEFRAME_MAP:
            return cls.TIMEFRAME_MAP[lower]
        if key in cls.TIMEFRAME_MAP.values():
            return key
        return None

    @staticmethod
    def _qd_timeframe(timeframe: str) -> str:
        key = str(timeframe or "").strip()
        lower = key.lower()
        if lower == "1h":
            return "1H"
        if lower == "4h":
            return "4H"
        if lower == "1d":
            return "1D"
        return lower or key

    def _apply_time_bounds(
        self,
        params: Dict[str, Any],
        timeframe: str,
        limit: int,
        before_time: Optional[int],
        after_time: Optional[int],
    ) -> None:
        if after_time is not None:
            params["start"] = self._format_rfc3339(int(after_time))
        else:
            effective_before = int(before_time) if before_time else int(datetime.now(timezone.utc).timestamp())
            qd_timeframe = self._qd_timeframe(timeframe)
            span = TIMEFRAME_SECONDS.get(qd_timeframe, 60) * max(limit + 2, 3)
            params["start"] = self._format_rfc3339(max(0, effective_before - int(span)))
            params["end"] = self._format_rfc3339(effective_before)
            return

        if before_time:
            params["end"] = self._format_rfc3339(int(before_time))

    def _request_raw_bars(
        self,
        alpaca_symbol: str,
        alpaca_timeframe: str,
        request_limit: int,
        qd_timeframe: str,
        before_time: Optional[int],
        after_time: Optional[int],
    ) -> List[Dict[str, Any]]:
        api_request_limit = request_limit
        if after_time is None:
            api_request_limit = min(10000, max(request_limit + 10, request_limit * 2, 20))

        params: Dict[str, Any] = {
            "symbols": alpaca_symbol,
            "timeframe": alpaca_timeframe,
            "limit": api_request_limit,
        }
        self._apply_time_bounds(params, qd_timeframe, api_request_limit, before_time, after_time)

        try:
            logger.info(
                "Alpaca crypto bars request: symbol=%s timeframe=%s limit=%s params=%s",
                alpaca_symbol,
                alpaca_timeframe,
                request_limit,
                self._safe_params_for_log(params),
            )
            headers = self._headers()
            response = requests.get(
                self.API_URL,
                params=params,
                headers=headers or None,
                timeout=self.timeout,
            )
            if response.status_code in (401, 403) and headers:
                logger.warning(
                    "Alpaca crypto bars auth rejected: status=%s symbol=%s; retrying without credentials",
                    response.status_code,
                    alpaca_symbol,
                )
                response = requests.get(
                    self.API_URL,
                    params=params,
                    headers=None,
                    timeout=self.timeout,
                )
            if response.status_code >= 400:
                logger.error(
                    "Alpaca crypto bars request failed: status=%s symbol=%s timeframe=%s body=%s",
                    response.status_code,
                    alpaca_symbol,
                    alpaca_timeframe,
                    (response.text or "")[:500],
                )
                return []
            data = response.json()
        except requests.RequestException as exc:
            logger.error(
                "Alpaca crypto bars request error: symbol=%s timeframe=%s error=%s",
                alpaca_symbol,
                alpaca_timeframe,
                exc,
            )
            return []
        except ValueError as exc:
            logger.error(
                "Alpaca crypto bars invalid JSON: symbol=%s timeframe=%s error=%s",
                alpaca_symbol,
                alpaca_timeframe,
                exc,
            )
            return []
        except Exception as exc:
            logger.error(
                "Alpaca crypto bars unexpected failure: symbol=%s timeframe=%s error=%s",
                alpaca_symbol,
                alpaca_timeframe,
                exc,
            )
            return []
        return self._bars_for_symbol(data, alpaca_symbol)

    def _format_raw_bars(self, raw_bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        klines: List[Dict[str, Any]] = []
        for bar in raw_bars:
            if not isinstance(bar, dict):
                continue
            timestamp = self._parse_timestamp(bar.get("t"))
            if timestamp is None:
                logger.debug("Alpaca crypto bars: skipping bar with invalid timestamp: %s", bar)
                continue
            try:
                klines.append(
                    self.format_kline(
                        timestamp=timestamp,
                        open_price=bar.get("o"),
                        high=bar.get("h"),
                        low=bar.get("l"),
                        close=bar.get("c"),
                        volume=bar.get("v", 0),
                    )
                )
            except Exception as exc:
                logger.debug("Alpaca crypto bars: skipping malformed bar %s: %s", bar, exc)
        klines.sort(key=lambda row: row["time"])
        return klines

    @staticmethod
    def _merge_every_n_sorted_bars(bars: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
        if n <= 1 or len(bars) < n:
            return bars
        rows = sorted((bar for bar in bars if isinstance(bar, dict)), key=lambda row: row.get("time", 0))
        out: List[Dict[str, Any]] = []
        i = 0
        while i + n <= len(rows):
            chunk = rows[i : i + n]
            out.append(
                {
                    "time": int(chunk[0]["time"]),
                    "open": float(chunk[0]["open"]),
                    "high": max(float(row["high"]) for row in chunk),
                    "low": min(float(row["low"]) for row in chunk),
                    "close": float(chunk[-1]["close"]),
                    "volume": round(sum(float(row.get("volume") or 0.0) for row in chunk), 2),
                }
            )
            i += n
        return out

    @staticmethod
    def _is_near_now(timestamp: int) -> bool:
        now = int(datetime.now(timezone.utc).timestamp())
        return abs(now - int(timestamp)) <= 300

    @staticmethod
    def _safe_params_for_log(params: Dict[str, Any]) -> Dict[str, Any]:
        return dict(params or {})

    def _headers(self) -> Dict[str, str]:
        api_key = (
            self._config_value("api_key", "apiKey", "key_id", "keyId")
            or self._env_value("ALPACA_API_KEY", "APCA_API_KEY_ID", "ALPACA_KEY_ID")
        )
        secret_key = (
            self._config_value("secret_key", "secretKey", "secret", "api_secret", "apiSecret")
            or self._env_value("ALPACA_SECRET_KEY", "APCA_API_SECRET_KEY", "ALPACA_API_SECRET")
        )
        if not api_key or not secret_key:
            logger.warning(
                "Alpaca crypto bars: missing API credentials; trying unauthenticated data request"
            )
            return {}
        return {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        }

    def _config_value(self, *keys: str) -> str:
        for key in keys:
            value = self.exchange_config.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    @staticmethod
    def _env_value(*keys: str) -> str:
        for key in keys:
            value = os.getenv(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    @staticmethod
    def _env_timeout() -> float:
        raw = os.getenv("ALPACA_DATA_TIMEOUT") or os.getenv("DATA_SOURCE_TIMEOUT") or "15"
        try:
            value = float(raw)
            return value if value > 0 else 15.0
        except Exception:
            return 15.0

    @staticmethod
    def _format_rfc3339(timestamp: int) -> str:
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )

    @staticmethod
    def _parse_timestamp(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            raw = float(value)
            return int(raw / 1000) if raw > 10_000_000_000 else int(raw)

        text = str(value).strip()
        if not text:
            return None
        try:
            raw = float(text)
            return int(raw / 1000) if raw > 10_000_000_000 else int(raw)
        except Exception:
            pass

        iso_text = _FRACTIONAL_SECONDS_RE.sub(r".\1", text)
        if iso_text.endswith("Z"):
            iso_text = iso_text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(iso_text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return None

    @staticmethod
    def _bars_for_symbol(data: Any, symbol: str) -> List[Dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        bars_by_symbol = data.get("bars")
        if not isinstance(bars_by_symbol, dict):
            logger.error("Alpaca crypto bars: response missing bars object")
            return []
        bars = bars_by_symbol.get(symbol)
        if isinstance(bars, list):
            return bars
        logger.warning(
            "Alpaca crypto bars: response has no bars for %s; available=%s",
            symbol,
            sorted(str(k) for k in bars_by_symbol.keys())[:10],
        )
        return []
