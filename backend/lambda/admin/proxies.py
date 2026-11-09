"""Admin API: proxies."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote

from http_common import _json_response, _log_event, _read_http_error

FRANKFURTER_API_BASE = "https://api.frankfurter.dev"
YAHOO_FINANCE_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
FINANCE_QUOTES_MAX_SYMBOLS = 50

_YAHOO_EXCHANGE_SUFFIX_BY_PREFIX: dict[str, str] = {
    "US": "",
    "USA": "",
    "NASDAQ": "",
    "NYSE": "",
    "NYSEARCA": "",
    "ARCA": "",
    "AMEX": "",
    "BATS": "",
    "CBOE": "",
    "OTC": "",
    "LON": ".L",
    "LSE": ".L",
    "LSIN": ".IL",
    "HK": ".HK",
    "HKG": ".HK",
    "HKEX": ".HK",
    "TYO": ".T",
    "TSE": ".T",
    "JPX": ".T",
    "ASX": ".AX",
    "TSX": ".TO",
    "TSXV": ".V",
    "FRA": ".F",
    "ETR": ".DE",
    "XETRA": ".DE",
    "GER": ".DE",
    "PAR": ".PA",
    "EPA": ".PA",
    "AMS": ".AS",
    "EBR": ".BR",
    "BIT": ".MI",
    "MIL": ".MI",
    "BME": ".MC",
    "MAD": ".MC",
    "SWX": ".SW",
    "VIE": ".VI",
    "STO": ".ST",
    "OSL": ".OL",
    "CSE": ".CO",
    "HEL": ".HE",
    "SGX": ".SI",
    "KRX": ".KS",
    "KOSDAQ": ".KQ",
    "TWSE": ".TW",
    "SHA": ".SS",
    "SSE": ".SS",
    "SHE": ".SZ",
    "SZSE": ".SZ",
    "BSE": ".BO",
    "NSE": ".NS",
    "JSE": ".JO",
    "B3": ".SA",
    "BMV": ".MX",
    "BCBA": ".BA",
}


def _normalize_finance_quote_symbol(raw: str) -> str | None:
    """Convert a user-entered symbol (e.g. ``US:TQQQ``, ``BTC``, ``VWRA.L``)
    into the Yahoo Finance symbol form. Returns ``None`` for empty input.

    Heuristics:
    - ``EXCHANGE:SYMBOL`` is mapped via :data:`_YAHOO_EXCHANGE_SUFFIX_BY_PREFIX`.
      Unknown prefixes pass the bare symbol through unchanged.
    - Bare alphanumeric tokens that look like a crypto ticker (3-5 letters,
      no dot, no dash) get a ``-USD`` suffix so Yahoo treats them as crypto.
    - Anything else (already contains ``.``/``-``/``=``) is passed through.
    """
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    if ":" in s:
        prefix, _, sym = s.partition(":")
        prefix_up = prefix.strip().upper()
        sym = sym.strip()
        if not sym:
            return None
        suffix = _YAHOO_EXCHANGE_SUFFIX_BY_PREFIX.get(prefix_up)
        if suffix is None:
            # Unknown prefix: drop it and pass through the bare symbol.
            return sym.upper() if sym.isascii() and sym.isalnum() else sym
        if suffix == "":
            return sym.upper()
        return f"{sym.upper()}{suffix}"
    if "." in s or "-" in s or "=" in s:
        return s
    # Bare ticker: assume crypto if 2-6 letters all-alpha (Yahoo crypto pairs
    # use ``XXX-USD``); otherwise leave as-is so Yahoo can resolve the equity.
    upper = s.upper()
    if upper.isalpha() and 2 <= len(upper) <= 6:
        return f"{upper}-USD"
    return upper


def _parse_finance_quotes_query(
    qs: dict[str, Any] | None,
) -> tuple[list[tuple[str, str]], None] | str:
    """Return ``(pairs, None)`` where ``pairs`` is a list of
    ``(originalSymbol, yahooSymbol)`` (preserving order, deduplicated by
    yahoo symbol), or a validation error message.
    """
    if not qs:
        return "symbols is required"
    raw = str(qs.get("symbols") or "").strip()
    if not raw:
        return "symbols is required"
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return "symbols is required"
    if len(parts) > FINANCE_QUOTES_MAX_SYMBOLS:
        return f"At most {FINANCE_QUOTES_MAX_SYMBOLS} symbols per request"
    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for orig in parts:
        if len(orig) > 32:
            return f"Symbol too long: {orig[:32]}…"
        normalized = _normalize_finance_quote_symbol(orig)
        if normalized is None:
            return f"Invalid symbol: {orig}"
        if normalized in seen:
            continue
        seen.add(normalized)
        pairs.append((orig, normalized))
    return (pairs, None)


def _normalize_yahoo_price_currency(
    price: float, currency: str
) -> tuple[float, str]:
    """Yahoo reports some venues in sub-units (e.g. UK pence as ``GBp``,
    South African cents as ``ZAc``, Israeli agorot as ``ILA``). Convert
    those to the major-unit ISO 4217 code so the rest of the pipeline
    (Frankfurter, MoneyAmount) handles them consistently.
    """
    if not currency:
        return price, currency
    cu = currency.strip()
    if cu == "GBp" or cu == "GBX":
        return price / 100.0, "GBP"
    if cu == "ZAc":
        return price / 100.0, "ZAR"
    if cu == "ILA":
        return price / 100.0, "ILS"
    return price, cu.upper()


def _fetch_yahoo_quote(
    yahoo_symbol: str, request_id: str
) -> dict[str, Any]:
    """Returns ``{ price, currency }`` on success or ``{ error }`` on failure.

    Hits the public Yahoo Finance v8 chart endpoint (no auth required) and
    pulls ``meta.regularMarketPrice`` / ``meta.currency``. Sub-unit
    currencies (GBp, ZAc, ILA) are normalized to the major unit.
    """
    upstream = (
        f"{YAHOO_FINANCE_CHART_BASE}/{quote(yahoo_symbol, safe='')}"
        "?interval=1d&range=1d"
    )
    try:
        req = urllib.request.Request(
            upstream,
            headers={
                "User-Agent": "lxsoftware-admin-api/1.0",
                "Accept": "application/json",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = _read_http_error(exc).decode("utf-8", errors="replace")[:200]
        _log_event(
            "warning",
            tag="quote_upstream_http_error",
            symbol=yahoo_symbol,
            status=exc.code,
            body_snip=body,
            request_id=request_id,
        )
        return {"error": f"Quote HTTP {exc.code}"}
    except urllib.error.URLError as exc:
        _log_event(
            "warning",
            tag="quote_upstream_url_error",
            symbol=yahoo_symbol,
            err=str(exc)[:200],
            request_id=request_id,
        )
        return {"error": "Quote upstream unreachable"}
    except Exception as exc:  # pragma: no cover - defensive
        _log_event(
            "warning",
            tag="quote_upstream_unexpected_error",
            symbol=yahoo_symbol,
            err=str(exc)[:200],
            request_id=request_id,
        )
        return {"error": "Quote upstream error"}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "Quote upstream returned invalid JSON"}
    chart = payload.get("chart") if isinstance(payload, dict) else None
    if not isinstance(chart, dict):
        return {"error": "Quote upstream unexpected shape"}
    err = chart.get("error")
    if err:
        msg = (
            err.get("description") if isinstance(err, dict) else None
        ) or "Quote upstream error"
        return {"error": str(msg)[:200]}
    result = chart.get("result")
    if not isinstance(result, list) or not result:
        return {"error": "Quote not found"}
    meta = result[0].get("meta") if isinstance(result[0], dict) else None
    if not isinstance(meta, dict):
        return {"error": "Quote meta missing"}
    price_raw = meta.get("regularMarketPrice")
    currency_raw = meta.get("currency")
    try:
        price = float(price_raw) if price_raw is not None else None
    except (TypeError, ValueError):
        price = None
    if price is None or not (price == price):  # NaN check
        return {"error": "Quote price missing"}
    currency = (
        str(currency_raw).strip() if isinstance(currency_raw, str) else ""
    )
    if not currency:
        return {"error": "Quote currency missing"}
    norm_price, norm_currency = _normalize_yahoo_price_currency(price, currency)
    return {"price": norm_price, "currency": norm_currency}


def _proxy_finance_quotes(
    qs: dict[str, Any] | None, request_id: str
) -> dict[str, Any]:
    """Look up live spot prices for ETF tickers / crypto coins via Yahoo.

    The frontend calls this for Investment rows (Crypto / ETF) so the
    *Current Value* column can show ``unit × spot price`` converted to
    the row currency via Frankfurter.
    """
    parsed = _parse_finance_quotes_query(qs)
    if isinstance(parsed, str):
        return _json_response(400, {"message": parsed})
    pairs, _ = parsed
    if not pairs:
        return _json_response(200, [])

    # Yahoo's chart endpoint is one symbol per call. Fan out in parallel so
    # a 5-symbol request stays well below the API gateway timeout.
    import concurrent.futures

    def _one(pair: tuple[str, str]) -> dict[str, Any]:
        original, yahoo_symbol = pair
        result = _fetch_yahoo_quote(yahoo_symbol, request_id)
        return {"symbol": original, "yahooSymbol": yahoo_symbol, **result}

    max_workers = min(8, len(pairs))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(_one, pairs))
    return _json_response(200, results)


def _parse_fx_v2_rates_query(
    qs: dict[str, Any] | None,
) -> tuple[str, list[str]] | str:
    """Return ``(base, sorted_unique_quotes)`` or a validation error message.

    Accepts any 3-letter alphabetic ISO 4217 code (Frankfurter validates
    whether the code is actually supported upstream and returns 4xx otherwise).
    The Investments tab needs to convert Yahoo-reported quote currencies
    (which can be any of Frankfurter's supported fiat currencies — JPY, AUD,
    CAD, …) into the row currency, so we pass the validation through to the
    upstream rather than restricting to ``SUPPORTED_FINANCE_CURRENCIES``.
    """
    if not qs:
        return "base is required"
    base = str(qs.get("base") or "").strip().upper()
    quotes_raw = str(qs.get("quotes") or "").strip()
    if not base:
        return "base is required"
    parts = [p.strip().upper() for p in quotes_raw.split(",") if p.strip()]
    need = sorted({p for p in parts if p != base})
    for c in [base, *need]:
        if not (len(c) == 3 and c.isalpha()):
            return f"Invalid currency code: {c}"
    return (base, need)


def _proxy_fx_v2_rates(qs: dict[str, Any] | None, request_id: str) -> dict[str, Any]:
    """ECB-oriented FX rows from Frankfurter (server-side; keeps browser CSP tight)."""
    parsed = _parse_fx_v2_rates_query(qs)
    if isinstance(parsed, str):
        return _json_response(400, {"message": parsed})
    base, quotes_need = parsed
    if not quotes_need:
        return _json_response(200, [])
    quotes_param = ",".join(quote(q, safe="") for q in quotes_need)
    upstream = (
        f"{FRANKFURTER_API_BASE}/v2/rates?"
        f"base={quote(base, safe='')}&quotes={quotes_param}"
    )
    try:
        req = urllib.request.Request(
            upstream,
            headers={"User-Agent": "lxsoftware-admin-api/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = _read_http_error(exc).decode("utf-8", errors="replace")[:500]
        _log_event(
            "warning",
            tag="fx_rates_upstream_http_error",
            status=exc.code,
            body_snip=body,
            request_id=request_id,
        )
        return _json_response(
            502, {"message": f"FX upstream returned HTTP {exc.code}"}
        )
    except urllib.error.URLError as exc:
        _log_event(
            "warning",
            tag="fx_rates_upstream_url_error",
            err=str(exc)[:256],
            request_id=request_id,
        )
        return _json_response(502, {"message": "FX upstream unreachable"})
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return _json_response(502, {"message": "FX upstream returned invalid JSON"})
    if not isinstance(payload, list):
        return _json_response(502, {"message": "FX upstream unexpected shape"})
    return _json_response(200, payload)


