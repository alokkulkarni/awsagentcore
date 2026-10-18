#!/usr/bin/env bash
# =============================================================================
# build_chime.sh
# =============================================================================
# Builds the two scripts a call from the Money Hub page needs (pinned versions,
# from web/vendor-src/package-lock.json):
#   web/vendor/chime.js  the parts of the Amazon Chime SDK for JavaScript that
#                        join the call
#   web/vendor/daily.js  Daily's client, for the room the face (Tavus) appears in
# The page serves both itself, so its strict content security policy needs no
# script hosts.
#
# Changes nothing in AWS. deploy_money_hub.sh runs it on every deploy.
#
# Usage:   ./connect-money-hub/scripts/build_chime.sh
# Needs:   Node.js 18+ and npm
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="${SCRIPT_DIR}/../web/vendor-src"
OUT="${SCRIPT_DIR}/../web/vendor/chime.js"
OUT_DAILY="${SCRIPT_DIR}/../web/vendor/daily.js"

command -v npm >/dev/null || { echo "[FAIL] npm not found. Install Node.js 18 or later (https://nodejs.org)." >&2; exit 1; }

echo "[....] Installing the pinned Chime SDK, Daily client and esbuild..."
(cd "$SRC" && npm ci --no-audit --no-fund --ignore-scripts >/dev/null)

# esbuild's own installer is a script npm may block; its platform binary arrives as a plain package.
ESBUILD="$(find "$SRC/node_modules/@esbuild" -path '*/bin/esbuild' -type f 2>/dev/null | head -n 1)"
[[ -x "$ESBUILD" ]] || { echo "[FAIL] No esbuild binary for this computer under $SRC/node_modules/@esbuild." >&2; exit 1; }

mkdir -p "$(dirname "$OUT")"
(cd "$SRC" && "$ESBUILD" entry.js --bundle --format=esm --minify --platform=browser --target=es2020 \
    --legal-comments=none --log-level=warning --define:global=globalThis \
    --alias:@aws-sdk/client-chime-sdk-messaging=./messaging-stub.cjs --outfile="$OUT")

if grep -q 'from"node:\|require("node:' "$OUT"; then
    echo "[FAIL] The bundle still refers to Node modules; it would not load in a browser." >&2; exit 1
fi
# The SDK uses Node's `global` (browsers have none); --define swaps it for globalThis. None may be left.
if grep -q '[^A-Za-z0-9_.$]global[^A-Za-z0-9_$]' "$OUT"; then
    echo "[FAIL] The bundle still uses Node's 'global'; a call would fail with 'global is not defined'." >&2; exit 1
fi
echo "[ OK ] Built web/vendor/chime.js ($(wc -c < "$OUT" | tr -d ' ') bytes)."

(cd "$SRC" && "$ESBUILD" daily-entry.js --bundle --format=esm --minify --platform=browser --target=es2020 \
    --legal-comments=none --log-level=warning --define:global=globalThis --outfile="$OUT_DAILY")
if grep -q 'from"node:\|require("node:' "$OUT_DAILY"; then
    echo "[FAIL] The Daily bundle refers to Node modules; it would not load in a browser." >&2; exit 1
fi
echo "[ OK ] Built web/vendor/daily.js ($(wc -c < "$OUT_DAILY" | tr -d ' ') bytes)."
