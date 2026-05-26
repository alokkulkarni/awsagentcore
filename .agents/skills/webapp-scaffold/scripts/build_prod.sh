#!/usr/bin/env bash
# Usage: ./build_prod.sh [--with-e2e] [--skip-audit] [--skip-tests]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WITH_E2E=false
SKIP_AUDIT=false
SKIP_TESTS=false

while [ $# -gt 0 ]; do
  case "$1" in
    --with-e2e) WITH_E2E=true ;;
    --skip-audit) SKIP_AUDIT=true ;;
    --skip-tests) SKIP_TESTS=true ;;
    *)
      echo "❌ Unknown option: $1"
      echo "Usage: ./build_prod.sh [--with-e2e] [--skip-audit] [--skip-tests]"
      exit 1
      ;;
  esac
  shift
done

fail() {
  echo "❌ $1"
  exit 1
}

warn() {
  echo "⚠️  $1"
}

run_if_script_exists() {
  local script_name="$1"
  shift
  if node -e "const p=require('./package.json'); process.exit(p.scripts && p.scripts['$script_name'] ? 0 : 1)"; then
    npm run "$script_name" "$@"
  else
    return 0
  fi
}

NODE_MAJOR=$(node --version | sed -E 's/^v([0-9]+).*/\1/')
NPM_VERSION=$(npm --version)

echo "Node $(node --version)"
echo "npm ${NPM_VERSION}"

if [ "${NODE_MAJOR}" -lt 20 ]; then
  fail "Node 20 or newer is required."
fi

if [ "${SKIP_AUDIT}" = false ]; then
  if ! python3 "${SCRIPT_DIR}/audit_security.py" . --report-only; then
    fail "Critical or high vulnerabilities remain after the security audit."
  fi
else
  warn "Skipping security audit."
fi

if ! python3 "${SCRIPT_DIR}/check_versions.py" .; then
  warn "Dependency version check reported warnings."
fi

npm ci

run_if_script_exists lint || fail "Lint failed."

if [ "${SKIP_TESTS}" = false ]; then
  if node -e "const p=require('./package.json'); process.exit(p.scripts && p.scripts.test ? 0 : 1)"; then
    if node -e "const p=require('./package.json'); process.exit((p.scripts && p.scripts.test || '').includes('vitest') ? 0 : 1)"; then
      npm run test -- --run || fail "Tests failed."
    else
      npm run test || fail "Tests failed."
    fi
  fi
else
  warn "Skipping unit tests."
fi

npm run build || fail "Production build failed."

if [ ! -d dist ]; then
  fail "dist/ was not created by the build."
fi

BUILD_SIZE=$(du -sh dist | awk '{print $1}')
FILE_COUNT=$(find dist -type f | wc -l | tr -d ' ')

echo "Build size: ${BUILD_SIZE}"
echo "Files in dist/: ${FILE_COUNT}"

if [ "${WITH_E2E}" = true ] && [ "${SKIP_TESTS}" = false ]; then
  run_if_script_exists test:e2e || fail "E2E tests failed."
fi

echo "✅ Production build completed successfully."
