#!/usr/bin/env bash
# =============================================================================
# deploy_connect_widget.sh
# =============================================================================
# Deploys the connect-chat-widget React application to AWS CloudFront + S3.
#
# Architecture:
#   Browser → CloudFront → S3 (private, no public access)
#             ↓
#   CloudFront Origin Access Control (OAC) — only CloudFront can read S3
#             ↓
#   Security headers added by CloudFront response headers policy
#   (intentionally no CSP — Amazon Connect widget requires CDN resource access)
#
# What this script does:
#   1. Builds the React/Vite app (npm run build)
#   2. Creates a private S3 bucket for static assets
#   3. Creates a CloudFront Origin Access Control (OAC)
#   4. Creates a CloudFront distribution with:
#        - S3 origin via OAC (no public S3 access)
#        - index.html: no-cache (always fresh)
#        - /assets/*: 1-year immutable cache (Vite hashes filenames)
#        - SPA fallback: 403/404 → /index.html (200)
#        - Security headers: HSTS, X-Frame-Options, X-Content-Type-Options
#   5. Applies the S3 bucket policy (CloudFront OAC read-only)
#   6. Syncs build output to S3 with correct Content-Type + cache headers
#   7. Creates a CloudFront cache invalidation
#   8. Prints the CloudFront URL + Connect Approved Origins reminder
#
# Re-running the script is IDEMPOTENT — existing resources are reused and only
# the S3 content + cache invalidation are updated on subsequent runs.
#
# Usage:
#   chmod +x scripts/deploy_connect_widget.sh
#   ./scripts/deploy_connect_widget.sh [OPTIONS]
#
# Options:
#   --env           ENV      Deployment environment tag (default: prod)
#   --region        REGION   AWS region for S3 + CloudFront (default: eu-west-2)
#   --account-id    ID       AWS account ID (auto-detected if not set)
#   --bucket-name   NAME     S3 bucket name override (default: meridian-connect-widget-{env})
#   --no-build               Skip npm build (use existing dist/ folder)
#   --dry-run                Print actions without executing AWS commands
#   --help                   Show this help text
#
# Requirements:
#   - AWS CLI v2 configured with credentials for S3, CloudFront, IAM
#   - Node.js and npm (for the build step)
#   - The connect-chat-widget/ directory must exist relative to the repo root
# =============================================================================

set -euo pipefail

# ── Colour helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

die()    { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }
warn()   { echo -e "${YELLOW}[ WARN]${NC} $*"; }
step()   { echo -e "${CYAN}[....]${NC} $*"; }
ok()     { echo -e "${GREEN}[  OK]${NC} $*"; }
header() { echo -e "\n${BOLD}━━━ $* ━━━${NC}"; }
info()   { echo -e "       $*"; }

# ── Script location ────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WIDGET_DIR="${REPO_ROOT}/connect-chat-widget"
DIST_DIR="${WIDGET_DIR}/dist"

# ── Defaults ───────────────────────────────────────────────────────────────────
ENV="prod"
AWS_REGION="${AWS_REGION:-eu-west-2}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-}"
BUCKET_NAME=""
SKIP_BUILD=false
DRY_RUN=false
PROJECT="meridian-connect-widget"

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --env)          ENV="$2";          shift 2 ;;
        --region)       AWS_REGION="$2";   shift 2 ;;
        --account-id)   ACCOUNT_ID="$2";   shift 2 ;;
        --bucket-name)  BUCKET_NAME="$2";  shift 2 ;;
        --no-build)     SKIP_BUILD=true;   shift   ;;
        --dry-run)      DRY_RUN=true;      shift   ;;
        --help|-h)
            sed -n '/^# Usage:/,/^# Requirements:/p' "$0" | sed 's/^# \?//'
            exit 0 ;;
        *) die "Unknown argument: $1. Run with --help for usage." ;;
    esac
done

# ── Derived names ──────────────────────────────────────────────────────────────
[[ -z "$BUCKET_NAME" ]] && BUCKET_NAME="${PROJECT}-${ENV}"
CF_COMMENT="Meridian Bank Connect Widget (${ENV})"
OAC_NAME="${PROJECT}-oac-${ENV}"
HEADERS_POLICY_NAME="${PROJECT}-headers-${ENV}"
CF_TAGS="Key=Project,Value=meridian Key=Environment,Value=${ENV} Key=ManagedBy,Value=deploy_connect_widget"

# ── Validation ─────────────────────────────────────────────────────────────────
[[ -d "$WIDGET_DIR" ]] || die "Widget directory not found: ${WIDGET_DIR}"
command -v aws  >/dev/null 2>&1 || die "AWS CLI not found."
$SKIP_BUILD || command -v npm >/dev/null 2>&1 || die "npm not found. Install Node.js."

# ── Dry-run wrapper ────────────────────────────────────────────────────────────
run() {
    if $DRY_RUN; then
        echo -e "       ${YELLOW}[dry-run]${NC} $*"
    else
        "$@"
    fi
}

# ── Auto-detect account ID ─────────────────────────────────────────────────────
if [[ -z "$ACCOUNT_ID" ]]; then
    step "Auto-detecting AWS account ID..."
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) \
        || die "Cannot detect account ID — check AWS credentials."
    ok "Account: ${ACCOUNT_ID}  Region: ${AWS_REGION}"
fi

# State file persists CloudFront distribution ID between runs
STATE_FILE="${WIDGET_DIR}/.deploy-state-${ENV}.env"
CF_DISTRIBUTION_ID=""
OAC_ID=""

if [[ -f "$STATE_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$STATE_FILE"
    [[ -n "$CF_DISTRIBUTION_ID" ]] && info "Loaded state: distribution=${CF_DISTRIBUTION_ID}"
fi

save_state() {
    cat > "$STATE_FILE" <<EOF
# Auto-generated by deploy_connect_widget.sh — do not edit manually
CF_DISTRIBUTION_ID="${CF_DISTRIBUTION_ID}"
OAC_ID="${OAC_ID}"
BUCKET_NAME="${BUCKET_NAME}"
AWS_REGION="${AWS_REGION}"
ACCOUNT_ID="${ACCOUNT_ID}"
EOF
}

# =============================================================================
# Step 1 — Build
# =============================================================================
header "Step 1 — Build React app"

if $SKIP_BUILD; then
    warn "--no-build flag set — skipping build."
    [[ -d "$DIST_DIR" ]] || die "No dist/ folder found. Run without --no-build first."
    ok "Using existing dist/: $(find "$DIST_DIR" -type f | wc -l | tr -d ' ') files"
else
    step "Installing dependencies..."
    (cd "$WIDGET_DIR" && run npm install --silent)

    step "Building production bundle..."
    (cd "$WIDGET_DIR" && run npm run build)

    $DRY_RUN || [[ -d "$DIST_DIR" ]] || die "Build failed — dist/ not created."
    ok "Build complete: $(find "$DIST_DIR" -type f 2>/dev/null | wc -l | tr -d ' ') files in dist/"
fi

# =============================================================================
# Step 2 — S3 Bucket (private, CloudFront-only access)
# =============================================================================
header "Step 2 — S3 bucket (private)"

bucket_exists() {
    aws s3api head-bucket --bucket "$1" --region "$AWS_REGION" 2>/dev/null && echo "yes" || echo ""
}

if [[ -n "$(bucket_exists "$BUCKET_NAME")" ]]; then
    warn "Bucket already exists — reusing: s3://${BUCKET_NAME}"
else
    step "Creating S3 bucket: ${BUCKET_NAME} in ${AWS_REGION}..."
    if [[ "$AWS_REGION" == "us-east-1" ]]; then
        run aws s3api create-bucket \
            --bucket "$BUCKET_NAME" \
            --region "$AWS_REGION"
    else
        run aws s3api create-bucket \
            --bucket "$BUCKET_NAME" \
            --region "$AWS_REGION" \
            --create-bucket-configuration "LocationConstraint=${AWS_REGION}"
    fi
    ok "Bucket created: s3://${BUCKET_NAME}"
fi

step "Enforcing Block Public Access on s3://${BUCKET_NAME}..."
run aws s3api put-public-access-block \
    --bucket "$BUCKET_NAME" \
    --public-access-block-configuration \
      "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

step "Enabling S3 server-side encryption (AES-256)..."
run aws s3api put-bucket-encryption \
    --bucket "$BUCKET_NAME" \
    --server-side-encryption-configuration '{
        "Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]
    }'

step "Disabling S3 versioning (static host — not needed)..."
run aws s3api put-bucket-versioning \
    --bucket "$BUCKET_NAME" \
    --versioning-configuration "Status=Suspended"

# Disable CORS on the bucket — CloudFront handles all browser requests.
# The S3 bucket is never accessed directly by the browser.
step "Removing any existing CORS configuration from S3 (CloudFront is the origin)..."
run aws s3api delete-bucket-cors --bucket "$BUCKET_NAME" 2>/dev/null || true

ok "S3 bucket configured: s3://${BUCKET_NAME}"

# =============================================================================
# Step 3 — CloudFront Origin Access Control (OAC)
# =============================================================================
header "Step 3 — CloudFront Origin Access Control"

# OAC is the modern replacement for OAI — it signs requests to S3 with
# SigV4 so the bucket never needs to be public.
# CloudFront OAC is a global resource (no region needed).

existing_oac_id=""
if [[ -n "$OAC_ID" ]]; then
    # Verify stored OAC still exists
    existing_oac_id=$(aws cloudfront get-origin-access-control \
        --id "$OAC_ID" \
        --query "OriginAccessControl.Id" \
        --output text 2>/dev/null || echo "")
fi

if [[ -n "$existing_oac_id" ]]; then
    warn "OAC already exists — reusing: ${OAC_ID}"
else
    step "Creating CloudFront Origin Access Control: ${OAC_NAME}..."
    OAC_RESULT=$(aws cloudfront create-origin-access-control \
        --origin-access-control-config "{
            \"Name\": \"${OAC_NAME}\",
            \"Description\": \"OAC for ${CF_COMMENT}\",
            \"SigningProtocol\": \"sigv4\",
            \"SigningBehavior\": \"always\",
            \"OriginAccessControlOriginType\": \"s3\"
        }" \
        --query "OriginAccessControl.Id" --output text 2>/dev/null) || \
    die "Failed to create OAC. Check CloudFront permissions."

    OAC_ID="$OAC_RESULT"
    ok "OAC created: ${OAC_ID}"
    save_state
fi

# =============================================================================
# Step 4 — S3 Bucket Policy (allow CloudFront OAC only)
# =============================================================================
header "Step 4 — S3 bucket policy (CloudFront OAC only)"

BUCKET_ARN="arn:aws:s3:::${BUCKET_NAME}"

step "Applying S3 bucket policy..."
run aws s3api put-bucket-policy \
    --bucket "$BUCKET_NAME" \
    --policy "{
        \"Version\": \"2012-10-17\",
        \"Statement\": [
            {
                \"Sid\": \"AllowCloudFrontOACRead\",
                \"Effect\": \"Allow\",
                \"Principal\": {
                    \"Service\": \"cloudfront.amazonaws.com\"
                },
                \"Action\": \"s3:GetObject\",
                \"Resource\": \"${BUCKET_ARN}/*\",
                \"Condition\": {
                    \"StringEquals\": {
                        \"AWS:SourceArn\": \"arn:aws:cloudfront::${ACCOUNT_ID}:distribution/*\"
                    }
                }
            }
        ]
    }"

ok "Bucket policy applied — only CloudFront can read s3://${BUCKET_NAME}"

# =============================================================================
# Step 5 — CloudFront Response Headers Policy (security headers)
# =============================================================================
# Note: We deliberately do NOT add a Content-Security-Policy header here.
# The Amazon Connect chat widget loads resources from CDNs (Ant Design CSS,
# etc.) and posts messages to iframe origins that a strict CSP would block.
# Security is enforced via:
#   - HTTPS-only (HSTS)
#   - X-Frame-Options: SAMEORIGIN
#   - X-Content-Type-Options: nosniff
#   - Referrer-Policy: strict-origin-when-cross-origin
# =============================================================================
header "Step 5 — CloudFront response headers policy"

existing_headers_policy_id=""
existing_headers_policy_id=$(aws cloudfront list-response-headers-policies \
    --type custom \
    --query "ResponseHeadersPolicyList.Items[?ResponseHeadersPolicy.ResponseHeadersPolicyConfig.Name=='${HEADERS_POLICY_NAME}'].ResponseHeadersPolicy.Id" \
    --output text 2>/dev/null | tr -d '[:space:]') || true

# AWS CLI outputs literal "None" for empty JMESPath list results — treat as absent
[[ "$existing_headers_policy_id" == "None" ]] && existing_headers_policy_id=""

if [[ -n "$existing_headers_policy_id" ]]; then
    HEADERS_POLICY_ID="$existing_headers_policy_id"
    warn "Response headers policy already exists — reusing: ${HEADERS_POLICY_ID}"
else
    step "Creating CloudFront response headers policy: ${HEADERS_POLICY_NAME}..."
    HEADERS_POLICY_CONFIG_FILE=$(mktemp)
    cat > "$HEADERS_POLICY_CONFIG_FILE" <<JSON
{
    "Name": "${HEADERS_POLICY_NAME}",
    "Comment": "Security headers for Meridian Connect Widget (${ENV})",
    "SecurityHeadersConfig": {
        "StrictTransportSecurity": {
            "Override": true,
            "IncludeSubdomains": true,
            "Preload": false,
            "AccessControlMaxAgeSec": 31536000
        },
        "ContentTypeOptions": {
            "Override": true
        },
        "FrameOptions": {
            "FrameOption": "SAMEORIGIN",
            "Override": true
        },
        "ReferrerPolicy": {
            "ReferrerPolicy": "strict-origin-when-cross-origin",
            "Override": true
        },
        "XSSProtection": {
            "Override": true,
            "Protection": true,
            "ModeBlock": true
        }
    }
}
JSON
    HEADERS_POLICY_ID=$(aws cloudfront create-response-headers-policy \
        --response-headers-policy-config "file://${HEADERS_POLICY_CONFIG_FILE}" \
        --query "ResponseHeadersPolicy.Id" --output text 2>&1) \
        || die "Failed to create response headers policy: ${HEADERS_POLICY_ID}"
    rm -f "$HEADERS_POLICY_CONFIG_FILE"
    # Guard against "None" on unexpected empty response
    [[ "$HEADERS_POLICY_ID" == "None" || -z "$HEADERS_POLICY_ID" ]] && \
        die "Response headers policy creation returned no ID."

    ok "Response headers policy created: ${HEADERS_POLICY_ID}"
fi

# =============================================================================
# Step 6 — CloudFront Distribution
# =============================================================================
header "Step 6 — CloudFront distribution"

S3_ORIGIN_DOMAIN="${BUCKET_NAME}.s3.${AWS_REGION}.amazonaws.com"
ORIGIN_ID="S3-${BUCKET_NAME}"

if [[ -n "$CF_DISTRIBUTION_ID" ]]; then
    # Verify stored distribution still exists
    existing_dist=$(aws cloudfront get-distribution \
        --id "$CF_DISTRIBUTION_ID" \
        --query "Distribution.Id" \
        --output text 2>/dev/null || echo "")
    if [[ -n "$existing_dist" ]]; then
        warn "CloudFront distribution already exists — reusing: ${CF_DISTRIBUTION_ID}"
    else
        warn "Stored distribution ID ${CF_DISTRIBUTION_ID} not found — creating new one."
        CF_DISTRIBUTION_ID=""
    fi
fi

if [[ -z "$CF_DISTRIBUTION_ID" ]]; then
    step "Creating CloudFront distribution..."
    info "  Origin: ${S3_ORIGIN_DOMAIN} (via OAC ${OAC_ID})"
    info "  Cache: /index.html → no-cache | /assets/* → 1 year immutable"
    info "  SPA:   403/404 → /index.html (HTTP 200)"

    # Write the distribution config to a temp file — avoids bash quoting issues
    # with deeply-nested JSON and makes the structure easy to read.
    #
    # Cache policy IDs (AWS managed, globally available):
    #   CachingDisabled:  4135ea2d-6df8-44a3-9df3-4b5a84be39ad  → no-cache (HTML)
    #   CachingOptimized: 658327ea-f89d-4fab-a63d-7e88639e58f6  → 1-year cache (assets)
    #
    # IMPORTANT: CachePolicyId and ForwardedValues/MinTTL/DefaultTTL/MaxTTL are
    # mutually exclusive in the CloudFront API. Use one or the other, not both.
    CF_CONFIG_FILE=$(mktemp)
    cat > "$CF_CONFIG_FILE" <<JSON
{
    "Comment": "${CF_COMMENT}",
    "Enabled": true,
    "HttpVersion": "http2and3",
    "PriceClass": "PriceClass_100",
    "DefaultRootObject": "index.html",
    "CallerReference": "${PROJECT}-${ENV}-$(date +%s)",
    "Origins": {
        "Quantity": 1,
        "Items": [{
            "Id": "${ORIGIN_ID}",
            "DomainName": "${S3_ORIGIN_DOMAIN}",
            "S3OriginConfig": {
                "OriginAccessIdentity": ""
            },
            "OriginAccessControlId": "${OAC_ID}"
        }]
    },
    "DefaultCacheBehavior": {
        "TargetOriginId": "${ORIGIN_ID}",
        "ViewerProtocolPolicy": "redirect-to-https",
        "Compress": true,
        "ResponseHeadersPolicyId": "${HEADERS_POLICY_ID}",
        "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
        "AllowedMethods": {
            "Quantity": 2,
            "Items": ["GET", "HEAD"],
            "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}
        }
    },
    "CacheBehaviors": {
        "Quantity": 1,
        "Items": [{
            "PathPattern": "/assets/*",
            "TargetOriginId": "${ORIGIN_ID}",
            "ViewerProtocolPolicy": "redirect-to-https",
            "Compress": true,
            "ResponseHeadersPolicyId": "${HEADERS_POLICY_ID}",
            "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",
            "AllowedMethods": {
                "Quantity": 2,
                "Items": ["GET", "HEAD"],
                "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}
            }
        }]
    },
    "CustomErrorResponses": {
        "Quantity": 2,
        "Items": [
            {
                "ErrorCode": 403,
                "ResponsePagePath": "/index.html",
                "ResponseCode": "200",
                "ErrorCachingMinTTL": 10
            },
            {
                "ErrorCode": 404,
                "ResponsePagePath": "/index.html",
                "ResponseCode": "200",
                "ErrorCachingMinTTL": 10
            }
        ]
    },
    "ViewerCertificate": {
        "CloudFrontDefaultCertificate": true,
        "MinimumProtocolVersion": "TLSv1.2_2021"
    },
    "Restrictions": {
        "GeoRestriction": {"RestrictionType": "none", "Quantity": 0}
    }
}
JSON

    CF_CREATE_OUTPUT=$(aws cloudfront create-distribution \
        --distribution-config "file://${CF_CONFIG_FILE}" \
        --query "Distribution.Id" --output text 2>&1)
    CF_EXIT=$?
    rm -f "$CF_CONFIG_FILE"

    if [[ $CF_EXIT -ne 0 || "$CF_CREATE_OUTPUT" == "None" || -z "$CF_CREATE_OUTPUT" ]]; then
        die "CloudFront distribution creation failed:\n${CF_CREATE_OUTPUT}\n\nCheck: IAM permissions for cloudfront:CreateDistribution"
    fi

    CF_DISTRIBUTION_ID="$CF_CREATE_OUTPUT"

    save_state
    ok "CloudFront distribution created: ${CF_DISTRIBUTION_ID}"
    info "  Distribution is deploying — this takes 5–15 minutes."
    info "  You can proceed with the S3 upload while it deploys."
fi

# Retrieve the distribution domain name
CF_DOMAIN=$(aws cloudfront get-distribution \
    --id "$CF_DISTRIBUTION_ID" \
    --query "Distribution.DomainName" \
    --output text 2>/dev/null) || CF_DOMAIN="<see AWS console>"

# =============================================================================
# Step 7 — Tighten S3 bucket policy with the specific distribution ARN
# =============================================================================
header "Step 7 — Tighten S3 bucket policy to this distribution"

CF_DISTRIBUTION_ARN="arn:aws:cloudfront::${ACCOUNT_ID}:distribution/${CF_DISTRIBUTION_ID}"

step "Updating bucket policy with specific distribution ARN..."
run aws s3api put-bucket-policy \
    --bucket "$BUCKET_NAME" \
    --policy "{
        \"Version\": \"2012-10-17\",
        \"Statement\": [
            {
                \"Sid\": \"AllowCloudFrontOACRead\",
                \"Effect\": \"Allow\",
                \"Principal\": {
                    \"Service\": \"cloudfront.amazonaws.com\"
                },
                \"Action\": \"s3:GetObject\",
                \"Resource\": \"${BUCKET_ARN}/*\",
                \"Condition\": {
                    \"StringEquals\": {
                        \"AWS:SourceArn\": \"${CF_DISTRIBUTION_ARN}\"
                    }
                }
            }
        ]
    }"

ok "Bucket policy locked to distribution: ${CF_DISTRIBUTION_ID}"

# =============================================================================
# Step 8 — Upload to S3
# =============================================================================
header "Step 8 — Upload build to S3"

if $DRY_RUN; then
    warn "[dry-run] Would sync ${DIST_DIR}/ → s3://${BUCKET_NAME}/"
else
    step "Uploading assets (long-cache: 1 year, immutable)..."
    # Vite hashes filenames in /assets — safe to cache forever
    aws s3 sync "${DIST_DIR}/assets/" "s3://${BUCKET_NAME}/assets/" \
        --region "$AWS_REGION" \
        --cache-control "public, max-age=31536000, immutable" \
        --delete \
        --exact-timestamps 2>/dev/null | grep -E "^upload:" | head -20 || true
    ok "Assets uploaded with 1-year immutable cache"

    step "Uploading index.html (no-cache)..."
    aws s3 cp "${DIST_DIR}/index.html" "s3://${BUCKET_NAME}/index.html" \
        --region "$AWS_REGION" \
        --content-type "text/html; charset=utf-8" \
        --cache-control "no-cache, no-store, must-revalidate"
    ok "index.html uploaded (no-cache)"

    step "Uploading remaining files (1 day cache)..."
    # Sync everything else that wasn't covered above (favicon, manifests, etc.)
    aws s3 sync "${DIST_DIR}/" "s3://${BUCKET_NAME}/" \
        --region "$AWS_REGION" \
        --cache-control "public, max-age=86400" \
        --exclude "assets/*" \
        --exclude "index.html" \
        --delete \
        --exact-timestamps 2>/dev/null | grep -E "^upload:" | head -20 || true
    ok "All files synced to s3://${BUCKET_NAME}/"
fi

# =============================================================================
# Step 9 — CloudFront invalidation
# =============================================================================
header "Step 9 — CloudFront cache invalidation"

step "Creating invalidation for /* ..."
INVALIDATION_ID=$(aws cloudfront create-invalidation \
    --distribution-id "$CF_DISTRIBUTION_ID" \
    --paths "/*" \
    --query "Invalidation.Id" --output text 2>/dev/null) || \
INVALIDATION_ID="(failed — invalidate manually)"

ok "Invalidation created: ${INVALIDATION_ID}"
info "  Cache cleared — changes will be live within ~30 seconds."

# =============================================================================
# Summary
# =============================================================================
header "Deployment complete"

cat <<EOF

  S3 Bucket       : s3://${BUCKET_NAME}   (${AWS_REGION})
  OAC             : ${OAC_ID}
  Distribution ID : ${CF_DISTRIBUTION_ID}
  Widget URL      : https://${CF_DOMAIN}

  Security:
    ✓ S3 bucket is private — no public access
    ✓ Only CloudFront (OAC ${OAC_ID}) can read S3
    ✓ All HTTP traffic redirected to HTTPS
    ✓ HSTS: max-age=31536000 (1 year)
    ✓ X-Frame-Options: SAMEORIGIN
    ✓ X-Content-Type-Options: nosniff
    ✓ Referrer-Policy: strict-origin-when-cross-origin
    ✓ TLS 1.2 minimum (TLSv1.2_2021)
    ✗ CSP intentionally omitted — Connect widget needs CDN access

  Cache strategy:
    /index.html       → no-cache (always fresh)
    /assets/*         → 1 year immutable (Vite content-hashed filenames)
    Everything else   → 1 day

$(printf "${YELLOW}")⚠  REQUIRED: Add CloudFront domain to Amazon Connect Approved Origins$(printf "${NC}")
  Without this step the chat widget will return 403 Forbidden.

  Steps:
    1. Open: https://console.aws.amazon.com/connect/
    2. Select your Connect instance
    3. Go to: Approved origins  (Instance settings → Approved origins)
    4. Click: Add origin
    5. Enter: https://${CF_DOMAIN}
    6. Click: Save

$(printf "${YELLOW}")⚠  If the distribution is still deploying (status: In Progress):$(printf "${NC}")
  Wait 5–15 minutes then test: https://${CF_DOMAIN}
  Check status:
    aws cloudfront get-distribution \\
      --id ${CF_DISTRIBUTION_ID} \\
      --query 'Distribution.Status' --output text

  To redeploy after code changes:
    ./scripts/deploy_connect_widget.sh --env ${ENV} --region ${AWS_REGION}

  State file: ${STATE_FILE}
EOF
