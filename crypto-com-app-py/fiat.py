#!/usr/bin/env python3
"""Fiat (cash) commands, ported from scripts/fiat.ts.

Usage: python fiat.py <command> [args]

Commands:
  discover                                       Cash overview (balances + payment networks)
  payment-networks <currency>                    Available deposit/withdrawal networks
  deposit-methods <currency> <deposit_method>    Bank details for a deposit method
  email-deposit-info <currency> <viban_type>     Email deposit instructions to user
  withdrawal-details <currency> <viban_type>     Withdrawal quotas, fees, minimums
  create-withdrawal-order '<json>'               Create withdrawal order
  create-withdrawal <order_id>                   Execute withdrawal (may prompt for TOTP)
  bank-accounts [currency]                       List linked bank accounts
"""
import json
import sys
from urllib.parse import quote as urlquote

from cdc_lib.api import api_get, api_post, assert_ok
from cdc_lib.output import ErrorCode, fail, run, success

USAGE = """Usage: python fiat.py <command> [args]

Commands:
  discover                                       Cash overview (balances + payment networks)
  payment-networks <currency>                    Available deposit/withdrawal networks
  deposit-methods <currency> <deposit_method>    Bank details for a deposit method
  email-deposit-info <currency> <viban_type>     Email deposit instructions to user
  withdrawal-details <currency> <viban_type>     Withdrawal quotas, fees, minimums
  create-withdrawal-order '<json>'               Create withdrawal order
  create-withdrawal <order_id>                   Execute withdrawal (may prompt for TOTP)
  bank-accounts [currency]                       List linked bank accounts"""


def _prompt_totp():
    print("TOTP code required. Enter your 6-digit authenticator code: ", end="", file=sys.stderr, flush=True)
    return input().strip()


def discover():
    account_res = api_get("/v1/fiat-account")
    assert_ok(account_res, "Fiat account fetch")

    balances = (account_res.data.get("account") or {}).get("balances") or []
    if not balances:
        success({"currencies": []})
        return

    currencies = []
    for bal in balances:
        ccy = bal["currency"]
        balance = (bal.get("amount") or {}).get("amount", "0")

        net_res = api_get(f"/v1/fiat/payment-networks?currency={urlquote(ccy)}")
        if net_res.status != 200 or net_res.data.get("ok") is not True:
            currencies.append({"currency": ccy, "balance": balance, "deposit": [], "withdrawal": []})
            continue

        networks = net_res.data.get("available_payment_networks") or []
        net = next((n for n in networks if n["currency"] == ccy), None)
        if not net:
            currencies.append({"currency": ccy, "balance": balance, "deposit": [], "withdrawal": []})
            continue

        currencies.append({
            "currency": ccy,
            "balance": balance,
            "deposit": net.get("deposit_push_payment_networks") or [],
            "withdrawal": net.get("withdrawal_payment_networks") or [],
        })

    success({"currencies": currencies})


def payment_networks(currency):
    if not currency:
        fail(ErrorCode.INVALID_ARGS, "Currency required. Example: python fiat.py payment-networks USD")

    res = api_get(f"/v1/fiat/payment-networks?currency={urlquote(currency)}")
    assert_ok(res, f"Payment networks fetch for {currency}")

    success(res.data["available_payment_networks"])


def deposit_methods(currency, deposit_method):
    if not currency:
        fail(ErrorCode.INVALID_ARGS, "Currency required. Example: python fiat.py deposit-methods USD sepa")
    if not deposit_method:
        fail(ErrorCode.INVALID_ARGS, "Deposit method required. Example: python fiat.py deposit-methods USD sepa")

    res = api_get(
        f"/v1/fiat/deposit-methods?currency={urlquote(currency)}&deposit_method={urlquote(deposit_method)}",
    )
    assert_ok(res, f"Deposit methods fetch for {currency} {deposit_method}")

    success(res.data["deposit_methods"])


def email_deposit_info(currency, viban_type):
    if not currency:
        fail(ErrorCode.INVALID_ARGS, "Currency required. Example: python fiat.py email-deposit-info USD iban")
    if not viban_type:
        fail(ErrorCode.INVALID_ARGS, "VIBAN type required. Example: python fiat.py email-deposit-info USD iban")

    res = api_post("/v1/fiat/deposit-info/email", {"currency": currency, "viban_type": viban_type})
    assert_ok(res, f"Email deposit info for {currency} {viban_type}")

    success(res.data["bank_info_email"])


def withdrawal_details(currency, viban_type):
    if not currency:
        fail(ErrorCode.INVALID_ARGS, "Currency required. Example: python fiat.py withdrawal-details USD iban")
    if not viban_type:
        fail(ErrorCode.INVALID_ARGS, "VIBAN type required. Example: python fiat.py withdrawal-details USD iban")

    res = api_get(
        f"/v1/fiat/withdrawal-details?currency={urlquote(currency)}&viban_type={urlquote(viban_type)}",
    )
    assert_ok(res, f"Withdrawal details fetch for {currency} {viban_type}")

    success(res.data["details"])


def create_withdrawal_order(params_json):
    if not params_json:
        fail(
            ErrorCode.INVALID_ARGS,
            'JSON params required. Example: python fiat.py create-withdrawal-order '
            '\'{"currency":"USD","amount":"100","viban_type":"iban"}\'',
        )

    try:
        params = json.loads(params_json)
    except ValueError:
        fail(ErrorCode.INVALID_ARGS, f"Invalid JSON: {params_json}")

    if not params.get("currency") or not params.get("amount") or not params.get("viban_type"):
        fail(ErrorCode.INVALID_ARGS, "Required fields: currency, amount, viban_type")

    res = api_post("/v1/fiat/withdrawal-orders", params)
    assert_ok(res, "Withdrawal order creation")

    success(res.data["viban_withdrawal_order"])


def create_withdrawal(order_id):
    if not order_id:
        fail(ErrorCode.INVALID_ARGS, "Order ID required. Example: python fiat.py create-withdrawal <order-id>")

    res = api_post("/v1/fiat/withdrawals", {"order_id": order_id})

    if (res.data or {}).get("error") == "totp_required":
        otp = _prompt_totp()
        res = api_post("/v1/fiat/withdrawals", {"order_id": order_id, "otp": otp})

    assert_ok(res, "Withdrawal creation")

    success(res.data["viban_withdrawal"])


def bank_accounts(currency=None):
    path = f"/v1/fiat/bank-accounts?currency={urlquote(currency)}" if currency else "/v1/fiat/bank-accounts"
    res = api_get(path)
    assert_ok(res, f"Bank accounts fetch for {currency}" if currency else "Bank accounts fetch")

    success(res.data["bank_accounts"])


def main():
    args = sys.argv[1:]
    command = args[0] if args else None
    arg1 = args[1] if len(args) > 1 else None
    arg2 = args[2] if len(args) > 2 else None

    if command == "discover":
        return discover()
    if command == "payment-networks":
        return payment_networks(arg1)
    if command == "deposit-methods":
        return deposit_methods(arg1, arg2)
    if command == "email-deposit-info":
        return email_deposit_info(arg1, arg2)
    if command == "withdrawal-details":
        return withdrawal_details(arg1, arg2)
    if command == "create-withdrawal-order":
        return create_withdrawal_order(arg1)
    if command == "create-withdrawal":
        return create_withdrawal(arg1)
    if command == "bank-accounts":
        return bank_accounts(arg1)
    fail(ErrorCode.INVALID_ARGS, f'Unknown command "{command}".\n\n{USAGE}' if command else USAGE)


if __name__ == "__main__":
    run(main)
