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

: "${DEVICE_IP:?DEVICE_IP is missing from .env}"
: "${TAPO_USER:?TAPO_USER is missing from .env}"
: "${TAPO_PASS:?TAPO_PASS is missing from .env}"

uv run --project "$PYTHON_PROJECT" kasa \
    --host "$DEVICE_IP" \
    --username "$TAPO_USER" \
    --password "$TAPO_PASS" \
    off
