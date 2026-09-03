#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"
PYTHON_PROJECT="$SCRIPT_DIR/../python"

if [[ ! -f "$ENV_FILE" ]]; then
    printf '[-] Missing environment file: %s\n' "$ENV_FILE" >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${TAPO_USER:?TAPO_USER is missing from .env}"
: "${TAPO_PASS:?TAPO_PASS is missing from .env}"
DISCOVERY_TARGET="${DISCOVERY_TARGET:-192.168.1.255}"

uv run --project "$PYTHON_PROJECT" kasa \
    --target "$DISCOVERY_TARGET" \
    --username "$TAPO_USER" \
    --password "$TAPO_PASS" \
    discover detail
