#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"

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
: "${DEVICE_IP:?DEVICE_IP is missing from .env}"

# 1. Calculate the KLAP v2 auth hash:
#    SHA256(SHA1(user) || SHA1(password)), where || means raw bytes.
U_HASH=$(printf '%s' "$TAPO_USER" | sha1sum | awk '{print $1}')
P_HASH=$(printf '%s' "$TAPO_PASS" | sha1sum | awk '{print $1}')
AUTH_HASH=$(printf '%s%s' "$U_HASH" "$P_HASH" | xxd -r -p | sha256sum | awk '{print $1}')

# 2. Generate a random 32-character hex seed (16 bytes)
LOCAL_SEED1=$(openssl rand -hex 16)

echo "Auth Hash:  $AUTH_HASH"
echo "Local Seed: $LOCAL_SEED1"