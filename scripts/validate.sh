#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PYTHON="${REPO_ROOT}/.venv/bin/python"
if [ ! -x "${PYTHON}" ]; then
  PYTHON="python3"
fi

PYTEST_CMD=(
  "${PYTHON}" -m pytest
  tests/test_engine.py
  tests/test_output_contract.py
  -v
)

echo "==> Repo root"
echo "${REPO_ROOT}"

echo
echo "==> Python"
echo "${PYTHON}"

echo
echo "==> Default local validation lane"
printf ' %q' "${PYTEST_CMD[@]}"
echo

echo
echo "==> Note"
echo "API/auth/runtime/integration-heavy checks are intentionally excluded from this default lane."
echo "Examples: tests/test_api_contract.py, tests/test_auth_entitlements.py, tests/test_eat_now_session.py, scripts/stream_smoke_test.py, tests/run_tests.sh"

echo
echo "==> Running pytest"
cd "${REPO_ROOT}"
"${PYTEST_CMD[@]}"
