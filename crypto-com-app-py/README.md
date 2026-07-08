# crypto-com-app-py

Python port of the official Crypto.com `crypto-agent-trading` skill's
"Main App" scripts (originally TypeScript, run via `npx tsx`), so it can be
run directly from VSCode's integrated terminal or debugger.

Source parity: `lib/api.py` + `lib/output.py` mirror `scripts/lib/api.ts` +
`scripts/lib/output.ts`; `account.py`, `trade.py`, `fiat.py`, `coins.py`
mirror the four TypeScript command scripts one-for-one (same commands, same
JSON stdout envelope, same HMAC-SHA256 request signing, same `https://wapi.crypto.com`
API host).

## Setup (VSCode)

1. Open this folder in VSCode.
2. Create a virtualenv and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # .venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```
3. Set your credentials as environment variables — **never** hardcode them
   or put real values in a committed file:
   ```bash
   export CDC_API_KEY="your-api-key"
   export CDC_API_SECRET="your-api-secret"
   ```
   Or copy `.env.example` to `.env` (already `.gitignore`d) and use VSCode's
   `python.envFile` setting / the `python-dotenv` package if you prefer.
4. Generate an API key at https://help.crypto.com/en/articles/13843786-api-key-management.

## Commands

```bash
# Account
python account.py balances [fiat|crypto|all]
python account.py balance <SYMBOL>
python account.py trading-limit
python account.py resolve-source <purchase|sale|exchange>
python account.py revoke-key            # kill switch: revokes the API key

# Trading (quote -> confirm, always review the quote before confirming)
python trade.py quote purchase '{"from_currency":"USD","to_currency":"BTC","from_amount":"100"}'
python trade.py confirm purchase <quotation-id>
python trade.py history

# Fiat / cash management
python fiat.py discover
python fiat.py payment-networks USD
python fiat.py deposit-methods USD sepa
python fiat.py email-deposit-info USD iban
python fiat.py withdrawal-details USD iban
python fiat.py create-withdrawal-order '{"currency":"USD","amount":"100","viban_type":"iban"}'
python fiat.py create-withdrawal <order-id>   # may prompt for a TOTP code
python fiat.py bank-accounts [currency]

# Coin search
python coins.py search '{"keyword":"BTC","sort_by":"rank","sort_direction":"asc","page_size":10}'
```

Every command prints a single JSON object to stdout: `{"ok": true, "data": ...}`
on success, or `{"ok": false, "error": "<CODE>", "error_message": "..."}` on
failure (exit code 1). This makes it easy to pipe into `jq` or parse from
another script/agent.

## Safety notes

- Every trade requires two steps: `quote` (no funds moved) then `confirm`
  with that quotation's ID. Always inspect the quote before confirming.
- `account.py revoke-key` is a kill switch — it revokes the current API key
  immediately.
- Credentials are read from `CDC_API_KEY`/`CDC_API_SECRET` env vars only;
  nothing in this package writes them to disk.

## Tests

```bash
pip install pytest
pytest tests/ -q
```

Tests mock the HTTP layer (no real network calls / credentials required).
