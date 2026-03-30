#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_FILE="${ROOT_DIR}/.deploy-state"
SERVICE_NAME="passat-ecu"
DEFAULT_REF="origin/main"
TIME_SYNC_URL="${OTA_TIME_SYNC_URL:-https://github.com}"

cd "${ROOT_DIR}"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/update.sh [tag]
  ./scripts/update.sh [tag] --set-time "YYYY-MM-DD HH:MM:SS"
  ./scripts/update.sh [tag] --set-time-from-ssh
  ./scripts/update.sh --set-time "YYYY-MM-DD HH:MM:SS"

Options:
  --set-time <UTC>   Set system time before deploy (UTC, e.g. "2026-03-26 14:35:00")
  --set-time-from-ssh
                     Use CALLER_UTC from SSH command environment
  -h, --help         Show this help
EOF
}

set_system_time() {
  local ts_utc="$1"
  echo "Setting system clock (UTC): ${ts_utc}"
  sudo date -u -s "${ts_utc}" >/dev/null
  echo "System time now: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
}

TARGET_INPUT=""
SET_TIME_UTC=""
SET_TIME_FROM_SSH="0"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --set-time)
      shift
      if [[ $# -eq 0 ]]; then
        echo "ERROR: --set-time requires a value."
        usage
        exit 1
      fi
      SET_TIME_UTC="$1"
      ;;
    --set-time-from-ssh)
      SET_TIME_FROM_SSH="1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -z "${TARGET_INPUT}" ]]; then
        TARGET_INPUT="$1"
      else
        echo "ERROR: Unexpected extra argument '$1'."
        usage
        exit 1
      fi
      ;;
  esac
  shift
done

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: Working tree is not clean. Commit/stash local changes first."
  exit 1
fi

DEPLOY_REF="${DEFAULT_REF}"
DEPLOY_LABEL="${DEFAULT_REF}"

if [[ "${SET_TIME_FROM_SSH}" == "1" ]]; then
  if [[ -z "${CALLER_UTC:-}" ]]; then
    echo "ERROR: --set-time-from-ssh requires CALLER_UTC in environment."
    echo "Example:"
    echo "  ssh joe@192.168.4.1 \"cd /home/joe/passat_ecu && CALLER_UTC='$(date -u +%Y-%m-%d\ %H:%M:%S)' ./scripts/update.sh --set-time-from-ssh\""
    exit 1
  fi
  set_system_time "${CALLER_UTC}"
elif [[ -n "${SET_TIME_UTC}" ]]; then
  set_system_time "${SET_TIME_UTC}"
else
  # On power loss systems without RTC, try a best-effort clock sync via HTTP Date.
  if [[ "$(date -u +%Y)" -lt 2025 ]]; then
    if command -v curl >/dev/null 2>&1; then
      HTTP_DATE="$(curl -fsSI --max-time 6 "${TIME_SYNC_URL}" | awk -F': ' 'tolower($1)=="date"{sub("\r","",$2); print $2; exit}' || true)"
      if [[ -n "${HTTP_DATE}" ]]; then
        set_system_time "${HTTP_DATE}"
      else
        echo "WARN: Could not auto-sync time from ${TIME_SYNC_URL}."
        echo "      Tip: run with --set-time \"YYYY-MM-DD HH:MM:SS\" (UTC)."
      fi
    else
      echo "WARN: curl not found; skipping automatic clock sync."
      echo "      Tip: run with --set-time \"YYYY-MM-DD HH:MM:SS\" (UTC)."
    fi
  fi
fi

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
