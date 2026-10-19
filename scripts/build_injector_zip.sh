#!/usr/bin/env bash
# =============================================================================
# build_injector_zip.sh
# =============================================================================
# Builds the code package for the session injector (aria-session-injector-qconnect):
# session_injector_qconnect.py plus the sample bank's data (moneyhub/__init__.py
# and moneyhub/data.py), which gives ARIA's greeting its accounts and cards.
#
# It only builds a zip. It changes nothing in AWS. To deploy it (code only, so the
# function's settings such as CLI_MATCH_LOA stay as they are):
#
#   aws lambda update-function-code --function-name aria-session-injector-qconnect \
#       --zip-file fileb://<the zip this prints> --region eu-west-2
#
# Usage:  ./scripts/build_injector_zip.sh [output.zip]
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-${TMPDIR:-/tmp}/aria-session-injector-qconnect.zip}"
BUILD="$(mktemp -d)"; trap 'rm -rf "$BUILD"' EXIT

cp "$ROOT/scripts/lambdas/session_injector_qconnect.py" "$BUILD/"
mkdir -p "$BUILD/moneyhub"
cp "$ROOT/connect-money-hub/moneyhub/__init__.py" "$ROOT/connect-money-hub/moneyhub/data.py" "$BUILD/moneyhub/"
rm -f "$OUT"
(cd "$BUILD" && zip -qr "$OUT" session_injector_qconnect.py moneyhub)

echo "Built $OUT:"
(cd "$BUILD" && find . -type f | sort | sed 's|^\./|  |')
echo "Deploy (code only):"
echo "  aws lambda update-function-code --function-name aria-session-injector-qconnect --zip-file fileb://$OUT --region eu-west-2"
