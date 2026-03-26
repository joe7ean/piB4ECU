#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_FILE="${ROOT_DIR}/.deploy-state"
SERVICE_NAME="passat-ecu"

cd "${ROOT_DIR}"

if [[ ! -f "${STATE_FILE}" ]]; then
  echo "ERROR: ${STATE_FILE} not found. No rollback target recorded yet."
  exit 1
fi

# shellcheck source=/dev/null
source "${STATE_FILE}"

if [[ -z "${PREVIOUS_COMMIT:-}" ]]; then
  echo "ERROR: PREVIOUS_COMMIT missing in ${STATE_FILE}."
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: Working tree is not clean. Commit/stash local changes first."
  exit 1
fi

echo "Fetching latest refs and tags..."
git fetch --tags origin

if ! git cat-file -e "${PREVIOUS_COMMIT}^{commit}" 2>/dev/null; then
  echo "ERROR: Previous commit '${PREVIOUS_COMMIT}' not available locally."
  exit 1
fi

CURRENT_COMMIT_NOW="$(git rev-parse HEAD)"
CURRENT_REF_NOW="$(git describe --tags --exact-match 2>/dev/null || echo "${CURRENT_COMMIT_NOW}")"
ROLLBACK_REF="${PREVIOUS_REF:-${PREVIOUS_COMMIT}}"

echo "Rolling back to ${ROLLBACK_REF} (${PREVIOUS_COMMIT})..."
git checkout --detach "${PREVIOUS_COMMIT}"

if [[ ! -x ".venv/bin/pip" ]]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

echo "Syncing Python dependencies..."
".venv/bin/pip" install -r requirements.txt

echo "Restarting service ${SERVICE_NAME}..."
sudo systemctl restart "${SERVICE_NAME}"

if ! sudo systemctl is-active --quiet "${SERVICE_NAME}"; then
  echo "ERROR: ${SERVICE_NAME} failed to start after rollback."
  sudo systemctl status "${SERVICE_NAME}" --no-pager || true
  exit 1
fi

{
  echo "LAST_DEPLOY_TS_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "CURRENT_REF=${ROLLBACK_REF}"
  echo "CURRENT_COMMIT=${PREVIOUS_COMMIT}"
  echo "PREVIOUS_REF=${CURRENT_REF_NOW}"
  echo "PREVIOUS_COMMIT=${CURRENT_COMMIT_NOW}"
} > "${STATE_FILE}"

echo "Rollback successful."
echo "Current: ${ROLLBACK_REF} (${PREVIOUS_COMMIT})"
echo "Previous: ${CURRENT_REF_NOW} (${CURRENT_COMMIT_NOW})"
