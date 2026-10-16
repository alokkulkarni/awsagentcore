#!/usr/bin/env bash
# =============================================================================
# deploy_pages_cloudfront.sh
# =============================================================================
# Puts Amazon CloudFront in front of the card dispute pages (customer page and
# adviser page), which deploy_card_dispute.sh serves from the Lambda through an
# HTTP API.
#
# Why: the customer page loads Amazon's Touchpoint library (about 3.6 MB). Without
# CloudFront the Lambda sends it on every page load. With it, CloudFront keeps a
# copy near the customer and the Lambda sends it once a day. You also get one
# stable https address for both pages.
#
# What CloudFront caches: only the versioned library (/vendor/*) and the pages'
# own scripts and styles (/assets/*). Everything else, every page and every call
# the pages make, goes straight to the Lambda, uncached, with its headers.
#
# YOU run this script, AFTER deploy_card_dispute.sh. It:
#   1. Finds the pages' HTTP API
#   2. Creates the CloudFront distribution (once; later runs leave it alone)
#   3. Tells the Lambda to build links with the CloudFront address
#   4. Waits until CloudFront has rolled out (about 5 to 15 minutes) and checks it
#
# Usage:
#   ./connect-card-dispute/scripts/deploy_pages_cloudfront.sh [--region REGION] [--no-wait] [--dry-run]
#
# Requirements: AWS CLI v2, python3, curl
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
die()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
step()  { echo -e "${CYAN}[....] $*${RESET}"; }
ok()    { echo -e "${GREEN}[ OK ] $*${RESET}"; }
header(){ echo -e "\n${BOLD}━━━ $* ━━━${RESET}"; }

REGION="${AWS_REGION:-eu-west-2}"
API_NAME="aria-card-dispute-pages"      # also the distribution's Comment, which is how it is found again
FUNCTION_NAME="aria-card-dispute"
WAIT=true
DRY_RUN=false

# AWS managed policies (the same IDs in every account).
CACHING_DISABLED="4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
CACHING_OPTIMIZED="658327ea-f89d-4fab-a63d-7e88639e58f6"
ALL_VIEWER_EXCEPT_HOST="b689b0a8-53d0-40ab-baf2-68738e2966ac"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)  REGION="$2"; shift 2 ;;
        --no-wait) WAIT=false; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help|-h) sed -n '/^# Usage:/,/^# Requirements:/p' "$0" | sed -E 's/^# ?//'; exit 0 ;;
        *) die "Unknown argument: $1. Run with --help for usage." ;;
    esac
done
for tool in aws python3 curl; do command -v "$tool" >/dev/null 2>&1 || die "${tool} not found on PATH."; done
first_value() { tr -s '[:space:]' '\n' | grep -v -e '^None$' -e '^$' | head -n 1 || true; }
BUILD_DIR="$(mktemp -d)"; trap 'rm -rf "$BUILD_DIR"' EXIT

header "Step 1 — The pages' HTTP API"
API_ID=$(aws apigatewayv2 get-apis --region "$REGION" --query "Items[?Name=='${API_NAME}'].ApiId" --output text | first_value)
[[ -n "$API_ID" ]] || die "No HTTP API named ${API_NAME}. Run deploy_card_dispute.sh first."
ORIGIN="${API_ID}.execute-api.${REGION}.amazonaws.com"
ok "Origin: ${ORIGIN}"

header "Step 2 — CloudFront distribution"
DIST_ID=$(aws cloudfront list-distributions --query "DistributionList.Items[?Comment=='${API_NAME}'].Id" --output text | first_value)
if [[ -n "$DIST_ID" ]]; then
    ok "Distribution already exists: ${DIST_ID} (left as it is)"
else
    ORIGIN="$ORIGIN" API_NAME="$API_NAME" CACHING_DISABLED="$CACHING_DISABLED" CACHING_OPTIMIZED="$CACHING_OPTIMIZED" \
    ALL_VIEWER_EXCEPT_HOST="$ALL_VIEWER_EXCEPT_HOST" python3 - > "${BUILD_DIR}/distribution.json" <<'PY'
import json, os, time
e = os.environ
read_only = {"Quantity": 2, "Items": ["GET", "HEAD"], "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}}
def cached(pattern):
    # The library and the pages' own files: the same for everyone, so they can be cached.
    return {"PathPattern": pattern, "TargetOriginId": "pages", "ViewerProtocolPolicy": "redirect-to-https",
            "AllowedMethods": read_only, "CachePolicyId": e["CACHING_OPTIMIZED"], "Compress": True}
print(json.dumps({
    "CallerReference": f"{e['API_NAME']}-{int(time.time())}",
    "Comment": e["API_NAME"],
    "Enabled": True,
    "PriceClass": "PriceClass_100",
    "HttpVersion": "http2and3",
    "Origins": {"Quantity": 1, "Items": [{
        "Id": "pages", "DomainName": e["ORIGIN"],
        "CustomOriginConfig": {"HTTPPort": 80, "HTTPSPort": 443, "OriginProtocolPolicy": "https-only",
                               "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]}}}]},
    # Pages and their calls: never cached, and every header but Host passed on (the CX designer's
    # x-api-key included), so the Lambda sees each request exactly as the browser sent it.
    "DefaultCacheBehavior": {
        "TargetOriginId": "pages", "ViewerProtocolPolicy": "redirect-to-https", "Compress": True,
        "AllowedMethods": {"Quantity": 7, "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
                           "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}},
        "CachePolicyId": e["CACHING_DISABLED"], "OriginRequestPolicyId": e["ALL_VIEWER_EXCEPT_HOST"]},
    "CacheBehaviors": {"Quantity": 2, "Items": [cached("/vendor/*"), cached("/assets/*")]},
}))
PY
    if $DRY_RUN; then
        warn "DRY-RUN — would create this distribution:"; python3 -m json.tool "${BUILD_DIR}/distribution.json" | head -40
        exit 0
    fi
    step "Creating the distribution..."
    DIST_ID=$(aws cloudfront create-distribution --distribution-config "file://${BUILD_DIR}/distribution.json" \
        --query "Distribution.Id" --output text)
    ok "Distribution created: ${DIST_ID}"
fi
DOMAIN=$(aws cloudfront get-distribution --id "$DIST_ID" --query "Distribution.DomainName" --output text)
PAGE_URL="https://${DOMAIN}"

header "Step 3 — Links use the CloudFront address"
# Only PUBLIC_BASE_URL changes; every other setting the Lambda has is kept.
aws lambda get-function-configuration --function-name "$FUNCTION_NAME" --region "$REGION" \
    --query "Environment" --output json > "${BUILD_DIR}/env-now.json"
PAGE_URL="$PAGE_URL" python3 - "${BUILD_DIR}/env-now.json" > "${BUILD_DIR}/env.json" <<'PY'
import json, os, sys
environment = json.load(open(sys.argv[1])) or {}
variables = environment.get("Variables") or {}
variables["PUBLIC_BASE_URL"] = os.environ["PAGE_URL"]
print(json.dumps({"Variables": variables}))
PY
if $DRY_RUN; then
    warn "DRY-RUN — would set PUBLIC_BASE_URL=${PAGE_URL} on ${FUNCTION_NAME}"
else
    aws lambda update-function-configuration --function-name "$FUNCTION_NAME" --region "$REGION" \
        --environment "file://${BUILD_DIR}/env.json" --query "FunctionName" --output text > /dev/null
    aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
    ok "Adviser links now start with ${PAGE_URL}"
fi

header "Step 4 — Rolling out"
if $WAIT && ! $DRY_RUN; then
    step "Waiting for CloudFront to roll out (usually 5 to 15 minutes)..."
    aws cloudfront wait distribution-deployed --id "$DIST_ID"
    code=$(curl -s -o "${BUILD_DIR}/page.html" -w '%{http_code}' "${PAGE_URL}/" || true)
    [[ "$code" == "200" ]] && grep -q "Read this code to us" "${BUILD_DIR}/page.html" \
        || die "The customer page did not load through CloudFront (HTTP ${code}) at ${PAGE_URL}/"
    ok "Customer page loads through CloudFront."
    if curl -s -o /dev/null -w '%{http_code}' "${PAGE_URL}/vendor/touchpoint-1.0.1/index.js" | grep -q 200; then
        ok "Touchpoint library is served and cached."
    else
        warn "The Touchpoint library is not in the Lambda package. Re-run deploy_card_dispute.sh with npm installed."
    fi
else
    warn "Not waiting. Check the distribution's status in the CloudFront console before using the address."
fi

cat <<SUMMARY

  Customer page : ${PAGE_URL}/
  Adviser page  : opened from the screen pop (${PAGE_URL}/adviser#<link token>)
  Distribution  : ${DIST_ID}

  deploy_card_dispute.sh finds this distribution on later runs and keeps using its address.

SUMMARY
