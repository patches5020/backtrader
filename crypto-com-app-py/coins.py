#!/usr/bin/env python3
"""Coin search, ported from scripts/coins.ts.

Usage: python coins.py <command> [args]

Commands:
  search '<json>'    Search coins by keyword, sort, pagination
"""
import json
import sys
from urllib.parse import urlencode

from cdc_lib.api import api_get, assert_ok
from cdc_lib.output import ErrorCode, fail, run, success

USAGE = """Usage: python coins.py <command> [args]

Commands:
  search '<json>'    Search coins by keyword, sort, pagination"""


def search(params_json):
    if not params_json:
        fail(
            ErrorCode.INVALID_ARGS,
            'JSON params required. Example: python coins.py search '
            '\'{"keyword":"BTC","sort_by":"rank","sort_direction":"asc","native_currency":"USD","page_size":10}\'',
        )

    try:
        params = json.loads(params_json)
    except ValueError:
        fail(ErrorCode.INVALID_ARGS, f"Invalid JSON: {params_json}")

    query = {k: v for k, v in params.items() if v is not None}
    path = f"/v1/crypto/coins?{urlencode(query)}"
    res = api_get(path)
    assert_ok(res, "Coin search")

    success({"coins": res.data["coins"], "pagination": res.data["pagination"]})


def main():
    args = sys.argv[1:]
    command = args[0] if args else None
    arg = args[1] if len(args) > 1 else None

    if command == "search":
        return search(arg)
    fail(ErrorCode.INVALID_ARGS, f'Unknown command "{command}".\n\n{USAGE}' if command else USAGE)


if __name__ == "__main__":
    run(main)
