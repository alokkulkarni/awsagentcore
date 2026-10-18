#!/usr/bin/env bash
# =============================================================================
# build_vendor.sh
# =============================================================================
# Builds the third-party scripts the banking app serves itself (pinned versions,
# from web/vendor-src/package-lock.json), so its strict content security policy
# needs no script hosts other than Daily's:
#   web/vendor/chime.js         the Amazon Chime SDK parts that join a call
#   web/vendor/daily.js         Daily's client, for the room the face (Tavus) appears in
#   web/vendor/touchpoint/*.js  the Amazon Connect Touchpoint SDK 1.0.1, for Live Sync on the
#                               mortgage and dispute forms (the version those pages use)
#
# Changes nothing in AWS. deploy_banking_app.sh runs it on every deploy.
#
# Usage:   ./connect-banking-app/scripts/build_vendor.sh
# Needs:   Node.js 18+ and npm
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="${SCRIPT_DIR}/../web/vendor-src"
OUT="${SCRIPT_DIR}/../web/vendor"

command -v npm >/dev/null || { echo "[FAIL] npm not found. Install Node.js 18 or later (https://nodejs.org)." >&2; exit 1; }

echo "[....] Installing the pinned Chime SDK, Daily client, Touchpoint SDK and esbuild..."
(cd "$SRC" && npm ci --no-audit --no-fund --ignore-scripts >/dev/null)

# esbuild's own installer is a script npm may block; its platform binary arrives as a plain package.
ESBUILD="$(find "$SRC/node_modules/@esbuild" -path '*/bin/esbuild' -type f 2>/dev/null | head -n 1)"
[[ -x "$ESBUILD" ]] || { echo "[FAIL] No esbuild binary for this computer under $SRC/node_modules/@esbuild." >&2; exit 1; }

mkdir -p "$OUT/touchpoint"
(cd "$SRC" && "$ESBUILD" entry.js --bundle --format=esm --minify --platform=browser --target=es2020 \
    --legal-comments=none --log-level=warning --define:global=globalThis \
    --alias:@aws-sdk/client-chime-sdk-messaging=./messaging-stub.cjs --outfile="$OUT/chime.js")
(cd "$SRC" && "$ESBUILD" daily-entry.js --bundle --format=esm --minify --platform=browser --target=es2020 \
    --legal-comments=none --log-level=warning --define:global=globalThis --outfile="$OUT/daily.js")
for bundle in chime.js daily.js; do
    if grep -q 'from"node:\|require("node:' "$OUT/$bundle"; then
        echo "[FAIL] web/vendor/$bundle refers to Node modules; it would not load in a browser." >&2; exit 1
    fi
done

# Touchpoint ships ready-made ES modules that import each other by file name: copy them as they are
# (not the UMD build, which the page doesn't use), the way the mortgage page serves them.
rm -f "$OUT"/touchpoint/*.js
find "$SRC/node_modules/@amazon-connect-touchpoint/web/lib" -maxdepth 1 -name '*.js' ! -name '*.umd.js' \
    -exec cp {} "$OUT/touchpoint/" \;
[[ -f "$OUT/touchpoint/index.js" ]] || { echo "[FAIL] The Touchpoint SDK has no lib/index.js." >&2; exit 1; }

echo "[ OK ] Built web/vendor/chime.js ($(wc -c < "$OUT/chime.js" | tr -d ' ') bytes), web/vendor/daily.js" \
     "($(wc -c < "$OUT/daily.js" | tr -d ' ') bytes) and web/vendor/touchpoint/ ($(ls "$OUT/touchpoint" | wc -l | tr -d ' ') files)."
