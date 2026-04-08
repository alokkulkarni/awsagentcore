#!/usr/bin/env bash
# =============================================================================
# upload_knowledgebase_to_s3.sh
# Uploads the Meridian Bank knowledge base to an S3 bucket for use as an
# Amazon Bedrock Knowledge Base data source.
#
# Usage:
#   ./scripts/upload_knowledgebase_to_s3.sh [OPTIONS]
#
# Options:
#   --bucket-name  NAME     Explicit bucket name (skips auto-generation)
#   --region       REGION   AWS region (default: eu-west-2)
#   --prefix       PREFIX   S3 key prefix inside the bucket (default: meridian-bank-kb)
#   --profile      PROFILE  AWS CLI profile to use
#   --dry-run               Print what would be uploaded without uploading
# =============================================================================

set -euo pipefail

# ─── Defaults ────────────────────────────────────────────────────────────────
REGION="eu-west-2"
BUCKET_NAME=""
S3_PREFIX="meridian-bank-kb"
AWS_PROFILE_OPT=""
DRY_RUN=false
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
KB_SOURCE_DIR="${REPO_ROOT}/knowledgebase/meridian-bank"

# ─── Colours ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()      { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
die()     { error "$*"; exit 1; }
heading() { echo -e "\n${BOLD}${CYAN}$*${RESET}"; }

# ─── Argument parsing ────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bucket-name) BUCKET_NAME="$2"; shift 2 ;;
    --region)      REGION="$2";      shift 2 ;;
    --prefix)      S3_PREFIX="$2";   shift 2 ;;
    --profile)     AWS_PROFILE_OPT="--profile $2"; shift 2 ;;
    --dry-run)     DRY_RUN=true;     shift ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "Unknown argument: $1. Use --help for usage." ;;
  esac
done

# ─── Prerequisites ───────────────────────────────────────────────────────────
heading "Meridian Bank Knowledge Base — S3 Upload"
echo "======================================================================"

command -v aws  &>/dev/null || die "AWS CLI is not installed. Install from https://aws.amazon.com/cli/"
command -v jq   &>/dev/null || die "jq is not installed. Run: brew install jq  or  apt install jq"

# Validate source directory
[[ -d "${KB_SOURCE_DIR}" ]] || die "Knowledge base source directory not found: ${KB_SOURCE_DIR}"

# Count files
TOTAL_TXT=$(find "${KB_SOURCE_DIR}" -name "*.txt" | wc -l | tr -d ' ')
TOTAL_JSON=$(find "${KB_SOURCE_DIR}" -name "*.metadata.json" | wc -l | tr -d ' ')
info "Source directory : ${KB_SOURCE_DIR}"
info "Content files    : ${TOTAL_TXT} .txt files"
info "Metadata files   : ${TOTAL_JSON} .metadata.json files"
info "Region           : ${REGION}"
info "S3 prefix        : ${S3_PREFIX}"
[[ "${DRY_RUN}" == "true" ]] && warn "DRY RUN mode — no changes will be made"
echo ""

# ─── AWS account / identity check ───────────────────────────────────────────
AWS_ACCOUNT_ID=$(aws sts get-caller-identity ${AWS_PROFILE_OPT} \
  --query Account --output text 2>/dev/null) \
  || die "Could not retrieve AWS identity. Check your credentials or run: aws configure"

ok "AWS account: ${AWS_ACCOUNT_ID}"

# ─── Bucket name generation ──────────────────────────────────────────────────
if [[ -z "${BUCKET_NAME}" ]]; then
  # Generate a short, stable suffix from account ID to keep names consistent
  SUFFIX=$(echo "${AWS_ACCOUNT_ID}" | sha256sum 2>/dev/null || echo "${AWS_ACCOUNT_ID}" | shasum -a 256)
  SUFFIX="${SUFFIX:0:8}"
  BUCKET_NAME="meridian-bank-kb-${SUFFIX}"
fi

info "Target S3 bucket : s3://${BUCKET_NAME}"
echo ""

# ─── Dry-run file listing ────────────────────────────────────────────────────
if [[ "${DRY_RUN}" == "true" ]]; then
  heading "Files that would be uploaded:"
  find "${KB_SOURCE_DIR}" -type f | sort | while read -r f; do
    rel="${f#${KB_SOURCE_DIR}/}"
    echo "  s3://${BUCKET_NAME}/${S3_PREFIX}/${rel}"
  done
  echo ""
  warn "Dry run complete. No bucket created, no files uploaded."
  exit 0
fi

# ─── Create bucket if it does not exist ─────────────────────────────────────
heading "Step 1 — S3 Bucket"

BUCKET_EXISTS=$(aws s3api head-bucket ${AWS_PROFILE_OPT} \
  --bucket "${BUCKET_NAME}" 2>&1 || true)

if echo "${BUCKET_EXISTS}" | grep -q "Not Found\|NoSuchBucket\|404"; then
  info "Bucket does not exist — creating: ${BUCKET_NAME}"
  if [[ "${REGION}" == "us-east-1" ]]; then
    aws s3api create-bucket ${AWS_PROFILE_OPT} \
      --bucket "${BUCKET_NAME}" \
      --region "${REGION}" \
      --output text > /dev/null
  else
    aws s3api create-bucket ${AWS_PROFILE_OPT} \
      --bucket "${BUCKET_NAME}" \
      --region "${REGION}" \
      --create-bucket-configuration LocationConstraint="${REGION}" \
      --output text > /dev/null
  fi
  ok "Bucket created: ${BUCKET_NAME}"

  # Block all public access
  info "Blocking public access on bucket..."
  aws s3api put-public-access-block ${AWS_PROFILE_OPT} \
    --bucket "${BUCKET_NAME}" \
    --public-access-block-configuration \
      "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" \
    --output text > /dev/null
  ok "Public access blocked"

  # Enable versioning (recommended for Bedrock KB data sources)
  info "Enabling versioning..."
  aws s3api put-bucket-versioning ${AWS_PROFILE_OPT} \
    --bucket "${BUCKET_NAME}" \
    --versioning-configuration Status=Enabled
  ok "Versioning enabled"

  # Enable server-side encryption (AES-256)
  info "Enabling server-side encryption (AES-256)..."
  aws s3api put-bucket-encryption ${AWS_PROFILE_OPT} \
    --bucket "${BUCKET_NAME}" \
    --server-side-encryption-configuration '{
      "Rules": [{
        "ApplyServerSideEncryptionByDefault": {
          "SSEAlgorithm": "AES256"
        },
        "BucketKeyEnabled": true
      }]
    }' > /dev/null
  ok "Server-side encryption enabled"

  # Tag the bucket
  aws s3api put-bucket-tagging ${AWS_PROFILE_OPT} \
    --bucket "${BUCKET_NAME}" \
    --tagging "TagSet=[
      {Key=Project,Value=aria-agentcore},
      {Key=Purpose,Value=bedrock-knowledgebase},
      {Key=Bank,Value=meridian-bank},
      {Key=ManagedBy,Value=upload-kb-script}
    ]" > /dev/null
  ok "Bucket tags applied"

elif echo "${BUCKET_EXISTS}" | grep -q "403\|Forbidden"; then
  die "Bucket '${BUCKET_NAME}' exists but you do not have access to it. Choose a different name with --bucket-name."
else
  ok "Bucket already exists — reusing: ${BUCKET_NAME}"
fi

# ─── Upload files ────────────────────────────────────────────────────────────
heading "Step 2 — Upload Knowledge Base Files"

UPLOADED=0
FAILED=0
SKIPPED=0

# Use aws s3 sync for efficiency — uploads only changed files
info "Syncing knowledge base to s3://${BUCKET_NAME}/${S3_PREFIX}/ ..."
echo ""

# Sync with content-type hints
aws s3 sync ${AWS_PROFILE_OPT} \
  "${KB_SOURCE_DIR}" \
  "s3://${BUCKET_NAME}/${S3_PREFIX}/" \
  --region "${REGION}" \
  --exclude "*.DS_Store" \
  --exclude ".gitkeep" \
  --include "*.txt" \
  --include "*.metadata.json" \
  --storage-class STANDARD_IA \
  --sse AES256 \
  --no-progress \
  2>&1 | while IFS= read -r line; do
    if echo "${line}" | grep -q "^upload:"; then
      echo -e "  ${GREEN}↑${RESET} ${line#upload: }"
      UPLOADED=$((UPLOADED + 1))
    else
      echo "  ${line}"
    fi
  done

# Count what was actually synced
UPLOADED_COUNT=$(aws s3 ls ${AWS_PROFILE_OPT} \
  "s3://${BUCKET_NAME}/${S3_PREFIX}/" \
  --recursive 2>/dev/null | wc -l | tr -d ' ')

echo ""
ok "Sync complete — ${UPLOADED_COUNT} objects now in s3://${BUCKET_NAME}/${S3_PREFIX}/"

# ─── Verify upload ───────────────────────────────────────────────────────────
heading "Step 3 — Verification"

info "Listing uploaded objects:"
aws s3 ls ${AWS_PROFILE_OPT} \
  "s3://${BUCKET_NAME}/${S3_PREFIX}/" \
  --recursive \
  --human-readable 2>/dev/null \
  | awk '{printf "  %-10s %s %s\n", $3, $4, $5}' \
  | sort

# ─── Summary ─────────────────────────────────────────────────────────────────
heading "======================================================================"
echo -e "${BOLD}${GREEN}Upload complete!${RESET}"
echo ""
echo -e "  ${BOLD}S3 Bucket:${RESET}   s3://${BUCKET_NAME}"
echo -e "  ${BOLD}S3 Prefix:${RESET}   ${S3_PREFIX}/"
echo -e "  ${BOLD}Region:${RESET}      ${REGION}"
echo -e "  ${BOLD}Objects:${RESET}     ${UPLOADED_COUNT} files"
echo -e "  ${BOLD}S3 URI:${RESET}      s3://${BUCKET_NAME}/${S3_PREFIX}/"
echo -e "  ${BOLD}ARN:${RESET}         arn:aws:s3:::${BUCKET_NAME}"
echo ""
echo -e "${BOLD}Next steps — Create Bedrock Knowledge Base:${RESET}"
echo "  1. Open AWS Console → Amazon Bedrock → Knowledge bases → Create"
echo "  2. Data source type: Amazon S3"
echo "  3. S3 URI: s3://${BUCKET_NAME}/${S3_PREFIX}/"
echo "  4. Metadata field: metadataAttributes (Bedrock KB will read .metadata.json files automatically)"
echo "  5. Embedding model: Amazon Titan Embeddings v2 (or your preferred model)"
echo "  6. Vector store: Amazon OpenSearch Serverless (managed) — recommended"
echo "  7. After creation, click 'Sync' to index the documents"
echo ""
echo -e "${BOLD}Or via AWS CLI:${RESET}"
echo "  aws bedrock-agent create-knowledge-base \\"
echo "    --name 'meridian-bank-knowledge-base' \\"
echo "    --role-arn 'arn:aws:iam::${AWS_ACCOUNT_ID}:role/AmazonBedrockExecutionRoleForKnowledgeBase' \\"
echo "    --knowledge-base-configuration '{\"type\":\"VECTOR\",\"vectorKnowledgeBaseConfiguration\":{\"embeddingModelArn\":\"arn:aws:bedrock:${REGION}::foundation-model/amazon.titan-embed-text-v2:0\"}}' \\"
echo "    --storage-configuration '{\"type\":\"OPENSEARCH_SERVERLESS\",\"opensearchServerlessConfiguration\":{\"collectionArn\":\"<YOUR_COLLECTION_ARN>\",\"vectorIndexName\":\"meridian-bank-index\",\"fieldMapping\":{\"vectorField\":\"embedding\",\"textField\":\"AMAZON_BEDROCK_TEXT_CHUNK\",\"metadataField\":\"AMAZON_BEDROCK_METADATA\"}}}' \\"
echo "    --region ${REGION}"
echo ""
echo -e "${GREEN}Done.${RESET}"
