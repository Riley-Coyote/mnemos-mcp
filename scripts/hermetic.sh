#!/usr/bin/env bash
# Run a command on Mnemos without going near anyone's live memory.
#
#   scripts/hermetic.sh pytest -q tests/test_live_store_guard.py
#   scripts/hermetic.sh mnemos stats
#   scripts/hermetic.sh python -c 'import mnemos; print(mnemos.__file__)'
#
# The command runs with:
#   - a temporary HOME (and USERPROFILE), removed afterwards unless
#     MNEMOS_HERMETIC_KEEP=1
#   - an explicit MNEMOS_DB_PATH inside that HOME, unless one is given that is
#     also outside the real ~/.mnemos
#   - this checkout installed in a venv of its own (.hermetic-venv here, made
#     with uv on first use), never a global pip install
#   - PYTHONDONTWRITEBYTECODE=1, after clearing this checkout's __pycache__
#   - MNEMOS_HERMETIC=1, so the engine refuses any store under the real
#     ~/.mnemos unless the command passes --i-mean-it (mnemos/live_guard.py)
#
# Nothing here reads, opens or writes the real ~/.mnemos.
set -euo pipefail

if [ "$#" -eq 0 ]; then
    sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
    exit 64
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# The account's own home, as the system has it, whatever HOME says now.
REAL_HOME="$(eval echo "~$(id -un)")"
VENV="${MNEMOS_HERMETIC_VENV:-$ROOT/.hermetic-venv}"

case "$VENV" in
    "$REAL_HOME/.mnemos"|"$REAL_HOME/.mnemos/"*)
        echo "hermetic: the venv may not live in $REAL_HOME/.mnemos" >&2; exit 2 ;;
esac

if ! command -v uv >/dev/null 2>&1; then
    echo "hermetic: uv is needed to build the isolated venv (https://docs.astral.sh/uv/)" >&2
    exit 2
fi

find "$ROOT/mnemos" "$ROOT/tests" "$ROOT/scripts" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
export PYTHONDONTWRITEBYTECODE=1

if [ ! -x "$VENV/bin/python" ]; then
    uv venv --quiet --python "${MNEMOS_HERMETIC_PYTHON:-3.12}" "$VENV"
fi
# Editable, so the venv runs this checkout as it stands; with what the suite needs.
VIRTUAL_ENV="$VENV" uv pip install --quiet --python "$VENV/bin/python" -e "$ROOT[dev,mcp]"

TMP_HOME="$(mktemp -d "${TMPDIR:-/tmp}/mnemos-hermetic.XXXXXX")"
TMP_HOME="$(cd "$TMP_HOME" && pwd -P)"
cleanup() {
    if [ "${MNEMOS_HERMETIC_KEEP:-0}" = "1" ]; then
        echo "hermetic: kept $TMP_HOME" >&2
    else
        rm -rf "$TMP_HOME"
    fi
}
trap cleanup EXIT

DB_PATH="${MNEMOS_DB_PATH:-}"
case "$DB_PATH" in
    "") DB_PATH="$TMP_HOME/.mnemos/${MNEMOS_AGENT_ID:-hermetic}.db" ;;
    "$REAL_HOME/.mnemos"|"$REAL_HOME/.mnemos/"*|"~/.mnemos"*)
        echo "hermetic: MNEMOS_DB_PATH=$DB_PATH is the live store; use a path in the temporary HOME" >&2
        exit 2 ;;
esac

export HOME="$TMP_HOME"
export USERPROFILE="$TMP_HOME"
export MNEMOS_DB_PATH="$DB_PATH"
export MNEMOS_HERMETIC=1
export MNEMOS_PROTECTED_HOME="$REAL_HOME"
export MNEMOS_DISABLE_DOTENV=1
unset MNEMOS_I_MEAN_IT VIRTUAL_ENV CONDA_PREFIX PYTHONHOME PYTHONPATH
export PATH="$VENV/bin:$PATH"

cd "$ROOT"
"$@"
