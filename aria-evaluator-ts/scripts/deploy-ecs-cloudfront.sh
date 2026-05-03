#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_FILE="${ROOT_DIR}/infra/cloudformation/ecs-cloudfront-lowcost.yaml"

ACTION="${1:-}"

STACK_NAME="${STACK_NAME:-aria-evaluator-ts}"
APP_NAME="${APP_NAME:-aria-evaluator-ts}"
AWS_REGION="${AWS_REGION:-eu-west-2}"
DESIRED_COUNT="${DESIRED_COUNT:-1}"
CPU="${CPU:-256}"
MEMORY="${MEMORY:-512}"
CONTAINER_PORT="${CONTAINER_PORT:-3001}"
S3_STATE_PREFIX="${S3_STATE_PREFIX:-aria-evaluator}"
S3_SYNC_INTERVAL_SECONDS="${S3_SYNC_INTERVAL_SECONDS:-30}"
IMAGE_TAG="${IMAGE_TAG:-$(date +%Y%m%d%H%M%S)-$(git -C "${ROOT_DIR}" rev-parse --short HEAD 2>/dev/null || echo local)}"
ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env}"
SCENARIOS_DIR="${SCENARIOS_DIR:-${ROOT_DIR}/../aria-evaluator/scenarios}"
PLACEHOLDER_IMAGE="${PLACEHOLDER_IMAGE:-public.ecr.aws/docker/library/nginx:stable}"

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/deploy-ecs-cloudfront.sh deploy
  ./scripts/deploy-ecs-cloudfront.sh update
  ./scripts/deploy-ecs-cloudfront.sh redeploy
  ./scripts/deploy-ecs-cloudfront.sh invalidate
  ./scripts/deploy-ecs-cloudfront.sh status
  ./scripts/deploy-ecs-cloudfront.sh destroy

Environment overrides:
  STACK_NAME, APP_NAME, AWS_REGION
  DESIRED_COUNT (0 or 1 for this low-cost template)
  CPU, MEMORY, CONTAINER_PORT
  S3_STATE_PREFIX, S3_SYNC_INTERVAL_SECONDS
  IMAGE_TAG
  ENV_FILE (default: ./aria-evaluator-ts/.env)
  SCENARIOS_DIR (default: ../aria-evaluator/scenarios)
USAGE
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "✗ Required command not found: $1" >&2
    exit 1
  }
}

require_docker_daemon() {
  if ! docker info >/dev/null 2>&1; then
    echo "✗ Docker daemon is not running or not reachable." >&2
    echo "  Start Docker Desktop (or your Docker engine), then retry." >&2
    exit 1
  fi
}

# Run a local production build (lint + tsc + vite) before committing to a
# Docker build.  Fails fast with readable errors rather than waiting several
# minutes for the Docker build to report the same thing.
run_local_production_build() {
  echo "ℹ Running production build check (lint + tsc + vite)…" >&2

  if ! command -v node >/dev/null 2>&1; then
    echo "✗ node not found — install Node.js 20+ to validate the build locally." >&2
    exit 1
  fi

  local node_ver
  node_ver="$(node --version 2>/dev/null | sed 's/v//' | cut -d. -f1)"
  if [[ -n "${node_ver}" && "${node_ver}" -lt 18 ]]; then
    echo "✗ Node.js 18+ required (found v${node_ver})." >&2
    exit 1
  fi

  # Install / sync deps if node_modules is missing or package-lock changed
  if [[ ! -d "${ROOT_DIR}/node_modules" ]]; then
    echo "ℹ node_modules not found — running npm ci…" >&2
    npm ci --prefix "${ROOT_DIR}" --no-audit --no-fund >&2 \
      || { echo "✗ npm ci failed." >&2; exit 1; }
  fi

  echo "  → tsc --noEmit (lint)" >&2
  npm run --prefix "${ROOT_DIR}" lint >&2 \
    || { echo "✗ TypeScript type-check failed. Fix errors before deploying." >&2; exit 1; }

  echo "  → tsc + vite (production build)" >&2
  npm run --prefix "${ROOT_DIR}" build >&2 \
    || { echo "✗ Production build failed. Fix errors before deploying." >&2; exit 1; }

  echo "✓ Local production build passed." >&2
}

stack_exists() {
  aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" >/dev/null 2>&1
}

stack_status() {
  aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --query 'Stacks[0].StackStatus' \
    --output text 2>/dev/null || echo "DOES_NOT_EXIST"
}

stack_output() {
  local key="$1"
  aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --query "Stacks[0].Outputs[?OutputKey=='${key}'].OutputValue | [0]" \
    --output text
}

# Wait for any in-progress stack operation to settle before issuing a new one.
# If the stack is stuck in *_IN_PROGRESS (not create/update rollback), cancel it and wait.
wait_for_stable_stack() {
  local status
  status="$(stack_status)"
  case "${status}" in
    UPDATE_COMPLETE|CREATE_COMPLETE|UPDATE_ROLLBACK_COMPLETE|DOES_NOT_EXIST)
      return 0
      ;;
    UPDATE_IN_PROGRESS|UPDATE_COMPLETE_CLEANUP_IN_PROGRESS)
      echo "ℹ Stack is currently in ${status}. Waiting up to 5 min for it to settle…"
      if aws cloudformation wait stack-update-complete \
          --stack-name "${STACK_NAME}" \
          --region "${AWS_REGION}" 2>/dev/null; then
        echo "ℹ Stack update completed."
      else
        echo "⚠ Stack update did not complete cleanly (status: $(stack_status)). Proceeding anyway."
      fi
      ;;
    UPDATE_ROLLBACK_IN_PROGRESS|UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS)
      echo "ℹ Stack is rolling back (${status}). Waiting for rollback to finish…"
      aws cloudformation wait stack-rollback-complete \
        --stack-name "${STACK_NAME}" \
        --region "${AWS_REGION}" 2>/dev/null || true
      ;;
    CREATE_IN_PROGRESS)
      echo "ℹ Stack creation in progress. Waiting…"
      aws cloudformation wait stack-create-complete \
        --stack-name "${STACK_NAME}" \
        --region "${AWS_REGION}" 2>/dev/null || true
      ;;
    *FAILED*|ROLLBACK_COMPLETE)
      echo "⚠ Stack is in terminal/failed state (${status}). A new changeset will handle it."
      ;;
    *)
      echo "⚠ Unexpected stack state: ${status}. Proceeding."
      ;;
  esac
}

deploy_stack() {
  local image_uri="$1"
  local desired="$2"
  aws cloudformation deploy \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --template-file "${TEMPLATE_FILE}" \
    --capabilities CAPABILITY_NAMED_IAM \
    --no-fail-on-empty-changeset \
    --parameter-overrides \
      AppName="${APP_NAME}" \
      AppImageUri="${image_uri}" \
      DesiredCount="${desired}" \
      Cpu="${CPU}" \
      Memory="${MEMORY}" \
      ContainerPort="${CONTAINER_PORT}" \
      S3StatePrefix="${S3_STATE_PREFIX}" \
      S3SyncIntervalSeconds="${S3_SYNC_INTERVAL_SECONDS}"
}

login_ecr() {
  local ecr_repo_uri="$1"
  local registry="${ecr_repo_uri%%/*}"
  aws ecr get-login-password --region "${AWS_REGION}" \
    | docker login --username AWS --password-stdin "${registry}"
}

build_and_push_image() {
  local ecr_repo_uri="$1"
  local full_image="${ecr_repo_uri}:${IMAGE_TAG}"

  echo "ℹ Building image ${full_image} (platform: linux/amd64)" >&2
  # Force linux/amd64 — ECS Fargate requires x86_64.
  # --provenance=false avoids pushing a multi-arch manifest list that ECR/ECS can't resolve.
  docker build \
    --platform linux/amd64 \
    --provenance=false \
    -t "${full_image}" \
    "${ROOT_DIR}" >&2
  docker push "${full_image}" >&2
  echo "${full_image}"
}

sync_runtime_state_inputs() {
  local bucket="$1"
  local env_target="s3://${bucket}/${S3_STATE_PREFIX}/.env"
  local scenarios_target="s3://${bucket}/${S3_STATE_PREFIX}/scenarios/"

  if [[ ! -f "${ENV_FILE}" ]]; then
    echo "✗ ENV_FILE not found: ${ENV_FILE}" >&2
    exit 1
  fi

  echo "ℹ Uploading runtime env to ${env_target}"
  aws s3 cp "${ENV_FILE}" "${env_target}" --region "${AWS_REGION}"

  if [[ -d "${SCENARIOS_DIR}" ]]; then
    echo "ℹ Syncing scenarios from ${SCENARIOS_DIR} to ${scenarios_target}"
    aws s3 sync "${SCENARIOS_DIR}/" "${scenarios_target}" --delete --region "${AWS_REGION}"
  else
    echo "⚠ SCENARIOS_DIR not found (${SCENARIOS_DIR}). Skipping scenarios sync."
  fi
}

run_deploy_flow() {
  if [[ ! -f "${TEMPLATE_FILE}" ]]; then
    echo "✗ Template not found: ${TEMPLATE_FILE}" >&2
    exit 1
  fi

  # Validate the production build locally first for fast feedback before
  # committing to a full Docker build + ECR push.
  run_local_production_build

  # Wait for any prior in-progress operation before touching the stack
  if stack_exists; then
    wait_for_stable_stack
  else
    echo "ℹ Bootstrapping stack (${STACK_NAME}) with desiredCount=0"
    deploy_stack "${PLACEHOLDER_IMAGE}" 0
  fi

  local ecr_repo_uri
  ecr_repo_uri="$(stack_output EcrRepositoryUri)"
  local bucket
  bucket="$(stack_output StateBucketName)"

  require_docker_daemon
  login_ecr "${ecr_repo_uri}"
  local image_uri
  image_uri="$(build_and_push_image "${ecr_repo_uri}")"
  if [[ -z "${image_uri}" || "${image_uri}" =~ [[:space:]] ]]; then
    echo "✗ Invalid image URI produced: '${image_uri}'" >&2
    exit 1
  fi

  sync_runtime_state_inputs "${bucket}"

  echo "ℹ Deploying stack with app image ${image_uri}"
  deploy_stack "${image_uri}" "${DESIRED_COUNT}"

  local distribution_id
  distribution_id="$(stack_output CloudFrontDistributionId)"
  echo "ℹ Invalidating CloudFront cache (${distribution_id})"
  aws cloudfront create-invalidation \
    --distribution-id "${distribution_id}" \
    --paths '/*' >/dev/null

  local url
  url="$(stack_output CloudFrontUrl)"
  echo
  echo "✓ Deployment complete"
  echo "  CloudFront URL: ${url}"
  echo "  State bucket  : ${bucket}"
}

run_invalidate() {
  if ! stack_exists; then
    echo "✗ Stack not found: ${STACK_NAME}" >&2
    exit 1
  fi
  local distribution_id
  distribution_id="$(stack_output CloudFrontDistributionId)"
  aws cloudfront create-invalidation \
    --distribution-id "${distribution_id}" \
    --paths '/*'
  echo "✓ Invalidated CloudFront distribution ${distribution_id}"
}

run_status() {
  if ! stack_exists; then
    echo "✗ Stack not found: ${STACK_NAME}" >&2
    exit 1
  fi
  local cf_url cluster service
  cf_url="$(stack_output CloudFrontUrl)"
  cluster="$(stack_output EcsClusterName)"
  service="$(stack_output EcsServiceName)"

  echo "CloudFront URL: ${cf_url}"
  aws ecs describe-services \
    --cluster "${cluster}" \
    --services "${service}" \
    --region "${AWS_REGION}" \
    --query 'services[0].{status:status,runningCount:runningCount,desiredCount:desiredCount,taskDefinition:taskDefinition}' \
    --output table
}

run_destroy() {
  if ! stack_exists; then
    echo "ℹ Stack does not exist: ${STACK_NAME}"
    return 0
  fi

  local bucket
  bucket="$(stack_output StateBucketName || true)"
  if [[ -n "${bucket}" && "${bucket}" != "None" ]]; then
    echo "ℹ Emptying S3 bucket s3://${bucket}"
    aws s3 rm "s3://${bucket}" --recursive --region "${AWS_REGION}" || true
  fi

  echo "ℹ Deleting stack ${STACK_NAME}"
  aws cloudformation delete-stack --stack-name "${STACK_NAME}" --region "${AWS_REGION}"
  aws cloudformation wait stack-delete-complete --stack-name "${STACK_NAME}" --region "${AWS_REGION}"
  echo "✓ Stack deleted"
}

require_cmd aws
require_cmd docker

case "${ACTION}" in
  deploy|update|redeploy)
    run_deploy_flow
    ;;
  invalidate)
    run_invalidate
    ;;
  status)
    run_status
    ;;
  destroy|teardown)
    run_destroy
    ;;
  *)
    usage
    exit 1
    ;;
esac
