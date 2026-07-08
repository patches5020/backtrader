#!/usr/bin/env python3
"""Account commands, ported from scripts/account.ts.

Usage: python account.py <command> [args]

Commands:
  balances [fiat|crypto|all]       Filtered non-zero balances (default: all)
  balance <SYMBOL>                 Single token balance lookup
  trading-limit                    Weekly trading limit info
  resolve-source <type>            Find funded wallets (purchase|sale|exchange)
  revoke-key                       Revoke API key (kill switch)
"""
import sys

from cdc_lib.api import api_get, api_post, assert_ok
from cdc_lib.output import ErrorCode, fail, run, success

USAGE = """Usage: python account.py <command> [args]

Commands:
  balances [fiat|crypto|all]       Filtered non-zero balances (default: all)
  balance <SYMBOL>                 Single token balance lookup
  trading-limit                    Weekly trading limit info
  resolve-source <type>            Find funded wallets (purchase|sale|exchange)
  revoke-key                       Revoke API key (kill switch)"""


def _filter_fiat(balances):
    return [b for b in balances if float((b.get("amount") or {}).get("amount", 0) or 0) > 0]


def _filter_crypto(wallets):
    def amount(w):
        return (w.get("available") or {}).get("amount") or (w.get("balance") or {}).get("amount") or "0"
    return [w for w in wallets if float(amount(w)) > 0]


def _parse_portfolio_products(res):
    if (res.data or {}).get("ok") is not True:
        return None
    products = res.data.get("products", [])
    return [p for p in products if float((p.get("price_native") or {}).get("amount", 0) or 0) > 0]


def _parse_currency_allocation(res):
    if (res.data or {}).get("ok") is not True:
        return None
    allocation = {}
    for key, val in res.data.items():
        if key == "ok":
            continue
        amount = (val or {}).get("amount")
        if amount and float(amount) > 0:
            allocation[key] = amount
    return allocation or None


def balances(scope):
    valid_scopes = ("fiat", "crypto", "all")
    if scope not in valid_scopes:
        fail(ErrorCode.INVALID_ARGS, f'Invalid scope "{scope}". Use: fiat | crypto | all')

    include_fiat = scope != "crypto"
    include_crypto = scope != "fiat"
    result = {}

    if include_fiat:
        res = api_get("/v1/fiat-account")
        assert_ok(res, "Fiat balance fetch")
        result["fiat"] = _filter_fiat(res.data["account"]["balances"])

    if include_crypto:
        crypto_res = api_get("/v1/crypto-account")
        portfolio_res = api_get("/v1/portfolio")
        assert_ok(crypto_res, "Crypto balance fetch")
        result["crypto"] = {
            "note": "available for trading",
            "wallets": _filter_crypto(crypto_res.data["account"]["wallets"]),
        }
        products = _parse_portfolio_products(portfolio_res)
        if products:
            result["portfolio_allocation"] = products

    success(result)


def balance(symbol):
    if not symbol:
        fail(ErrorCode.INVALID_ARGS, "Token symbol required. Example: python account.py balance BTC")

    upper = symbol.upper()
    crypto_res = api_get("/v1/crypto-account")
    allocation_res = api_get(f"/v1/portfolio/currency_allocation?currency={upper}")
    assert_ok(crypto_res, "Crypto balance fetch")

    wallet = next(
        (w for w in crypto_res.data["account"]["wallets"] if w["currency"].upper() == upper), None,
    )

    result = {
        "currency": upper,
        "available": (wallet or {}).get("available", {}).get("amount", "0"),
        "available_note": "available for trading",
        "balance": (wallet or {}).get("balance", {}).get("amount", "0"),
    }

    allocation = _parse_currency_allocation(allocation_res)
    if allocation:
        result["product_allocation"] = allocation

    success(result)


def trading_limit():
    res = api_get("/v1/api-keys/current")
    assert_ok(res, "Trading limit fetch")

    key = res.data["api_key"]
    limit = float(key["weekly_trading_limit_in_usd"])
    remaining = float(key["remaining_weekly_trading_limit_in_usd"])

    success({"used": limit - remaining, "limit": limit, "remaining": remaining, "currency": "USD"})


def _emit_resolve_result(funded, wallet_type):
    if len(funded) == 1:
        success({"status": "SELECTED", "currency": funded[0]["currency"], "walletType": wallet_type})
    elif len(funded) > 1:
        success({"status": "AMBIGUOUS", "options": [w["currency"] for w in funded], "walletType": wallet_type})
    else:
        success({"status": "EMPTY", "walletType": wallet_type})


def resolve_source(trade_type):
    valid_types = ("purchase", "sale", "exchange")
    if trade_type not in valid_types:
        fail(ErrorCode.INVALID_ARGS, f'Invalid trade type "{trade_type}". Use: purchase | sale | exchange')

    wallet_type = "fiat" if trade_type == "purchase" else "crypto"

    if wallet_type == "fiat":
        res = api_get("/v1/fiat-account")
        assert_ok(res, "Fiat balance fetch")
        _emit_resolve_result(_filter_fiat(res.data["account"]["balances"]), wallet_type)
    else:
        res = api_get("/v1/crypto-account")
        assert_ok(res, "Crypto balance fetch")
        _emit_resolve_result(_filter_crypto(res.data["account"]["wallets"]), wallet_type)


def revoke_key():
    res = api_post("/v1/api-keys/self-revoke", {})

    error_code = (res.data or {}).get("error") or (res.data or {}).get("code")

    if error_code == "api_key_not_found":
        fail(ErrorCode.API_KEY_NOT_FOUND, "API key not found — it may have already been revoked or does not exist.")

    if error_code == "key_not_active":
        fail(ErrorCode.API_KEY_NOT_FOUND, "API key is not active — it has been revoked or expired.")

    if res.status != 200 or (res.data or {}).get("ok") is False:
        api_msg = (res.data or {}).get("error_message") or (res.data or {}).get("message")
        detail = f"{error_code}: {api_msg}" if api_msg and error_code else (error_code or api_msg or f"HTTP {res.status}")
        fail(ErrorCode.API_ERROR, f"Kill switch request failed: {detail}")

    success({"revoked": True})


def main():
    args = sys.argv[1:]
    command = args[0] if args else None
    arg = args[1] if len(args) > 1 else None

    if command == "balances":
        return balances(arg or "all")
    if command == "balance":
        return balance(arg)
    if command == "trading-limit":
        return trading_limit()
    if command == "resolve-source":
        return resolve_source(arg)
    if command == "revoke-key":
        return revoke_key()
    fail(ErrorCode.INVALID_ARGS, f'Unknown command "{command}".\n\n{USAGE}' if command else USAGE)


if __name__ == "__main__":
    run(main)
