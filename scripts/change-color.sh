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

if [[ $# -ne 3 || ! "$1" =~ ^[0-9]+$ || ! "$2" =~ ^[0-9]+$ || ! "$3" =~ ^[0-9]+$ || "$1" -gt 360 || "$2" -gt 100 || "$3" -lt 1 || "$3" -gt 100 ]]; then
    printf 'Usage: %s HUE SATURATION BRIGHTNESS\n' "$0" >&2
    printf 'HUE: 0-360; SATURATION: 0-100; BRIGHTNESS: 1-100.\n' >&2
    exit 2
fi

uv run --project "$PYTHON_PROJECT" kasa \
    --host "$DEVICE_IP" \
    --username "$TAPO_USER" \
    --password "$TAPO_PASS" \
    light hsv "$1" "$2" "$3"
