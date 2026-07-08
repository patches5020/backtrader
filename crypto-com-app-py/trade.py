#!/usr/bin/env python3
"""Trade commands, ported from scripts/trade.ts.

Usage: python trade.py <command> [args]

Commands:
  quote <type> '<json>'            Get quotation (purchase|sale|exchange)
  confirm <type> <quotation-id>    Confirm order
  history                          Last 5 transactions
"""
import json
import sys

from cdc_lib.api import api_get, api_post, assert_ok
from cdc_lib.output import ErrorCode, fail, run, success

USAGE = """Usage: python trade.py <command> [args]

Commands:
  quote <type> '<json>'            Get quotation (purchase|sale|exchange)
  confirm <type> <quotation-id>    Confirm order
  history                          Last 5 transactions"""

QUOTE_PATHS = {
    "purchase": "/v1/crypto-purchase/quotations",
    "sale": "/v1/crypto-sales/quotations",
    "exchange": "/v1/crypto-exchange/quotations",
}

ORDER_PATHS = {
    "purchase": "/v1/crypto-purchase/orders",
    "sale": "/v1/crypto-sales/orders",
    "exchange": "/v1/crypto-exchange/orders",
}


def _build_quotation_body(trade_type, params):
    if trade_type == "purchase":
        body = {"from_currency": params["from_currency"], "to_currency": params["to_currency"]}
        if params.get("from_amount"):
            body["from_amount"] = params["from_amount"]
        else:
            body["to_amount"] = params.get("to_amount")
        return body
    if trade_type == "sale":
        return {
            "from_currency": params["from_currency"],
            "from_amount": params["from_amount"],
            "to_currency": params["to_currency"],
            "fixed_side": params.get("fixed_side", "from"),
        }
    if trade_type == "exchange":
        return {
            "from": params["from_currency"],
            "to": params["to_currency"],
            "from_amount": params["from_amount"],
            "side": params.get("side", "buy"),
        }
    fail(ErrorCode.INVALID_ARGS, f"Unknown trade type: {trade_type}")


def quote(trade_type, params_json):
    if trade_type not in QUOTE_PATHS:
        fail(ErrorCode.INVALID_ARGS, f'Invalid trade type "{trade_type}". Use: purchase | sale | exchange')
    if not params_json:
        fail(
            ErrorCode.INVALID_ARGS,
            'JSON params required. Example: python trade.py quote purchase '
            '\'{"from_currency":"USD","to_currency":"BTC","from_amount":"100"}\'',
        )

    try:
        params = json.loads(params_json)
    except ValueError:
        fail(ErrorCode.INVALID_ARGS, f"Invalid JSON: {params_json}")

    body = _build_quotation_body(trade_type, params)
    res = api_post(QUOTE_PATHS[trade_type], body)

    if res.status != 200 or (res.data or {}).get("ok") is not True:
        api_error = (res.data or {}).get("error")
        api_msg = (res.data or {}).get("error_message")
        msg = f"{api_error}: {api_msg}" if api_msg and api_error else (api_error or api_msg or "Quotation request rejected.")
        fail(ErrorCode.QUOTATION_FAILED, msg)

    success(res.data["quotation"])


def confirm(trade_type, quotation_id):
    if trade_type not in ORDER_PATHS:
        fail(ErrorCode.INVALID_ARGS, f'Invalid trade type "{trade_type}". Use: purchase | sale | exchange')
    if not quotation_id:
        fail(ErrorCode.INVALID_ARGS, "Quotation ID required. Example: python trade.py confirm purchase <quotation-id>")

    body = {"quotation_id": quotation_id, "side": "buy"} if trade_type == "exchange" else {"quotation_id": quotation_id}

    res = api_post(ORDER_PATHS[trade_type], body)

    if res.status != 200 or (res.data or {}).get("ok") is not True:
        api_error = (res.data or {}).get("error")
        api_msg = (res.data or {}).get("error_message")
        msg = f"{api_error}: {api_msg}" if api_msg and api_error else (api_error or api_msg or "Order confirmation failed.")
        fail(ErrorCode.EXECUTION_FAILED, msg)

    success(res.data["transaction"])


def history():
    res = api_get("/v1/transactions")
    assert_ok(res, "Transaction history fetch")

    txns = (res.data.get("transactions") or [])[:5]
    success(txns)


def main():
    args = sys.argv[1:]
    command = args[0] if args else None
    arg1 = args[1] if len(args) > 1 else None
    arg2 = args[2] if len(args) > 2 else None

    if command == "quote":
        return quote(arg1, arg2)
    if command == "confirm":
        return confirm(arg1, arg2)
    if command == "history":
        return history()
    fail(ErrorCode.INVALID_ARGS, f'Unknown command "{command}".\n\n{USAGE}' if command else USAGE)


if __name__ == "__main__":
    run(main)
