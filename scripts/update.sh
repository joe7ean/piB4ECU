#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_FILE="${ROOT_DIR}/.deploy-state"
SERVICE_NAME="passat-ecu"
DEFAULT_REF="origin/main"

cd "${ROOT_DIR}"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: Working tree is not clean. Commit/stash local changes first."
  exit 1
fi

TARGET_INPUT="${1:-}"
DEPLOY_REF="${DEFAULT_REF}"
DEPLOY_LABEL="${DEFAULT_REF}"

echo "Fetching latest refs and tags..."
git fetch --tags origin

if [[ -n "${TARGET_INPUT}" ]]; then
  if ! git ls-remote --tags --exit-code origin "refs/tags/${TARGET_INPUT}" >/dev/null 2>&1; then
    echo "ERROR: Tag '${TARGET_INPUT}' not found on origin."
    exit 1
  fi
  DEPLOY_REF="refs/tags/${TARGET_INPUT}"
  DEPLOY_LABEL="${TARGET_INPUT}"
fi

CURRENT_COMMIT="$(git rev-parse HEAD)"
CURRENT_REF="$(git describe --tags --exact-match 2>/dev/null || echo "${CURRENT_COMMIT}")"
TARGET_COMMIT="$(git rev-parse "${DEPLOY_REF}^{commit}")"

if [[ "${CURRENT_COMMIT}" == "${TARGET_COMMIT}" ]]; then
  echo "Already on target commit (${TARGET_COMMIT}). Continuing with dependency sync and restart."
else
  echo "Checking out ${DEPLOY_LABEL} (${TARGET_COMMIT})..."
  git checkout --detach "${TARGET_COMMIT}"
fi

if [[ ! -x ".venv/bin/pip" ]]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

echo "Syncing Python dependencies..."
".venv/bin/pip" install -r requirements.txt

echo "Restarting service ${SERVICE_NAME}..."
sudo systemctl restart "${SERVICE_NAME}"

if ! sudo systemctl is-active --quiet "${SERVICE_NAME}"; then
  echo "ERROR: ${SERVICE_NAME} failed to start."
  sudo systemctl status "${SERVICE_NAME}" --no-pager || true
  exit 1
fi

{
  echo "LAST_DEPLOY_TS_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "CURRENT_REF=${DEPLOY_LABEL}"
  echo "CURRENT_COMMIT=${TARGET_COMMIT}"
  echo "PREVIOUS_REF=${CURRENT_REF}"
  echo "PREVIOUS_COMMIT=${CURRENT_COMMIT}"
} > "${STATE_FILE}"

echo "Deploy successful."
echo "Current: ${DEPLOY_LABEL} (${TARGET_COMMIT})"
echo "Previous: ${CURRENT_REF} (${CURRENT_COMMIT})"
