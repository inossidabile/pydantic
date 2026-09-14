#!/usr/bin/env bash
# Test runner for the holistic aggregations challenge.
#
# Usage:
#   ./test.sh [--output_path <junit.xml>] <base|new>
#
#   base  run the existing repository tests in the change's blast radius; these
#         must pass both before and after the solution is applied.
#   new   run the new challenge tests; these fail before the solution and pass
#         after it.
set -uo pipefail

cd "$(dirname -- "${BASH_SOURCE[0]}")"

OUTPUT_PATH=""
if [ "${1:-}" = "--output_path" ]; then
  OUTPUT_PATH="$2"
  shift 2
fi

MODE="${1:-new}"

case "$MODE" in
  base)
    make lint
    uv run python -m pytest -k 'not olympus' -v --junitxml="$OUTPUT_PATH"
    ;;
  new)
    make lint
    uv run python -m pytest -k 'olympus' -v --junitxml="$OUTPUT_PATH"
    ;;
  *)
    echo "unknown mode: $MODE (expected base or new)" >&2
    exit 2
    ;;
esac
