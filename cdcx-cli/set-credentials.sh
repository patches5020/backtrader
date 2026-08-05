#!/usr/bin/env bash
# Writes CRYPTOCOM_API_KEY / CRYPTOCOM_API_SECRET into this package's .env
# file (read by cdcx/config.py via python-dotenv).
# Usage: set-credentials.sh <CRYPTOCOM_API_KEY> <CRYPTOCOM_API_SECRET>
#
# Dedicated, single-purpose script (rather than allowlisting raw
# cat/tee/redirection in Bash) so the standing permission rule that invokes
# it can be scoped to exactly this one operation on exactly this one file.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <CRYPTOCOM_API_KEY> <CRYPTOCOM_API_SECRET>" >&2
    exit 1
fi

umask 177
{
    printf 'CRYPTOCOM_API_KEY=%s\n' "$1"
    printf 'CRYPTOCOM_API_SECRET=%s\n' "$2"
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "Wrote CRYPTOCOM_API_KEY/CRYPTOCOM_API_SECRET to $ENV_FILE"
