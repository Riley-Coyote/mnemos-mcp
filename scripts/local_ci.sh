#!/bin/bash
# The release gate, run on this machine instead of GitHub Actions.
#
# GitHub Actions no longer starts jobs on this account, so this script is the
# check a pull request must pass before it merges. It runs every step of
# .github/workflows/release-hardening.yml against a clean copy of one commit
# and writes a summary to post on the pull request.
#
#   scripts/local_ci.sh              # the commit checked out here (HEAD)
#   scripts/local_ci.sh origin/main  # any commit
#   scripts/local_ci.sh --out DIR    # logs somewhere other than $TMPDIR
#   scripts/local_ci.sh --keep       # keep the copy and the environments
#
# Exit status is 0 only when every step passes. The workflows stay in the repo
# as the record of these checks: change a step in one, change it in the other.
#
# Written for the bash that ships with macOS (3.2), so no bash 4 features.

set -u -o pipefail

# A clean environment, as a CI runner has: nothing from the developer's shell
# (MNEMOS_*, a Claude Code session's variables, API keys) reaches a step.
# Kept: what finding the tools, the network and the caches needs.
if [ -z "${LOCAL_CI_CLEAN_ENV:-}" ]; then
    keep_env=()
    for name in $(compgen -e); do
        case $name in
            HOME|PATH|USER|LOGNAME|SHELL|TMPDIR|LANG|LC_*|TERM|UV_*|HF_*|XDG_*|PIP_*|SSL_CERT_*|REQUESTS_CA_BUNDLE|*_proxy|*_PROXY)
                keep_env+=("$name=${!name}") ;;
        esac
    done
    exec env -i "${keep_env[@]}" LOCAL_CI_CLEAN_ENV=1 /bin/bash "$0" "$@"
fi

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-2}"; }

OUT=""
KEEP=0
REF=HEAD
while [ $# -gt 0 ]; do
    case $1 in
        --out) [ $# -ge 2 ] || usage; OUT=$2; shift 2 ;;
        --keep) KEEP=1; shift ;;
        -h|--help) usage 0 ;;
        -*) usage ;;
        *) REF=$1; shift ;;
    esac
done

REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel) || exit 2
SHA=$(git -C "$REPO" rev-parse --verify "$REF^{commit}") || { echo "not a commit: $REF" >&2; exit 2; }
SHORT=${SHA:0:12}
SUBJECT=$(git -C "$REPO" log -1 --format=%s "$SHA")
[ -n "$OUT" ] || OUT="${TMPDIR:-/tmp}"
OUT="${OUT%/}/mnemos-local-ci-$SHORT"
rm -rf "$OUT" && mkdir -p "$OUT/logs" || exit 2
SRC="$OUT/src"
DIST="$OUT/dist"
VERSIONS="3.10 3.11 3.12 3.13"

echo "Mnemos local CI: $SHORT $SUBJECT"
echo "logs: $OUT/logs"
if [ "$REF" = HEAD ] && [ -n "$(git -C "$REPO" status --porcelain --untracked-files=no)" ]; then
    echo "note: uncommitted changes here are not tested; only $SHORT is."
fi
echo

# The commit itself, not the working tree: a shared clone of the repository,
# checked out at the commit, with its own .git as a CI checkout has.
git clone -q --shared --no-checkout "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)" "$SRC" \
    && git -C "$SRC" checkout -q --detach "$SHA" \
    || { echo "could not check out $SHA" >&2; exit 2; }
cd "$SRC" || exit 2

ROWS="$OUT/rows.md"
: > "$ROWS"
FAILED=0

# step NAME DETAIL_PATTERN COMMAND...
# Runs one check with its output in logs/NAME.log, prints a line as it ends,
# and keeps a row for the summary. The detail is the last two log lines that
# match DETAIL_PATTERN, or the last line of the log when the pattern is empty.
step() {
    local name=$1 pattern=$2; shift 2
    local log started=$SECONDS rc detail="" result
    log="$OUT/logs/$(printf '%s' "$name" | tr -cs 'A-Za-z0-9.' '-' | sed 's/-$//').log"
    "$@" > "$log" 2>&1
    rc=$?
    if [ -n "$pattern" ]; then
        detail=$(grep -E "$pattern" "$log" | tail -n 2 | tr '\n' ' ')
    fi
    if [ -z "$detail" ]; then
        detail=$(grep -v '^[[:space:]]*$' "$log" | tail -n 1)
    fi
    detail=$(printf '%s' "$detail" \
        | sed -E -e $'s/\x1b\\[[0-9;]*m//g' \
                 -e 's/Required test coverage of [0-9.]+% reached\. Total coverage: ([0-9.]+%)/coverage \1;/' \
                 -e 's/[[:space:]]+/ /g' -e 's/^ //; s/ $//' -e 's/\|/\\|/g' \
        | cut -c 1-110)
    if [ $rc -eq 0 ]; then result=pass; else result="**FAIL** (exit $rc)"; FAILED=$((FAILED + 1)); fi
    printf '%-28s %-6s %4ss  %s\n' "$name" "$([ $rc -eq 0 ] && echo pass || echo FAIL)" $((SECONDS - started)) "$detail"
    printf '| %s | %s | %ss | %s |\n' "$name" "$result" $((SECONDS - started)) "$detail" >> "$ROWS"
}

# Each Python version gets an environment of its own, as each CI job did.
in_env() { local env=$1; shift; UV_PROJECT_ENVIRONMENT="$OUT/env/$env" "$@"; }

up_to_date() {
    git -C "$REPO" fetch -q origin main || { echo "could not fetch origin/main"; return 1; }
    local main
    main=$(git -C "$REPO" rev-parse origin/main)
    if git -C "$REPO" merge-base --is-ancestor "$main" "$SHA"; then
        echo "contains origin/main ${main:0:12}"
    else
        echo "behind origin/main ${main:0:12}: merge main into the branch and run again"
        return 1
    fi
}

compile_entrypoints() {
    in_env "py$1" uv run --python "$1" --extra mcp python -m py_compile \
        mnemos/simple_runtime.py mnemos/simple_mcp.py mnemos/mcp_server.py mnemos/cli.py \
        && echo "the 4 entrypoints compile"
}

build() { uv build --out-dir "$DIST" && (cd "$DIST" && ls); }

twine_check() { (cd "$DIST" && COLUMNS=200 uvx twine check ./*); }

# Keep this set identical to the ones in release-hardening.yml and release.yml.
wheel_contents() {
    uv run --no-project --python 3.13 python - "$DIST" <<'PY'
import sys
import zipfile
from pathlib import Path

wheel = next(Path(sys.argv[1]).glob("mnemos*.whl"))
required = {
    "mnemos/simple_runtime.py",
    "mnemos/simple_mcp.py",
    "mnemos/setup/scheduler.py",
    "mnemos/setup/templates/SOUL.md",
    "mnemos/setup/templates/IDENTITY.md",
    "mnemos/companion/page/log/index.html",
    "mnemos/companion/page/fonts/inter-latin-wght-normal.woff2",
}
with zipfile.ZipFile(wheel) as archive:
    names = set(archive.namelist())
missing = sorted(required - names)
if missing:
    raise SystemExit(f"Missing from wheel: {missing}")
stray = sorted(n for n in names if n.split("/")[0] == "templates")
if stray:
    raise SystemExit(f"Loose top-level files in wheel: {stray}")
print(f"Wheel OK: {wheel.name}")
PY
}

# The built wheel in a clean venv, dependencies resolved live from PyPI with no
# lockfile, as a user's `pip install` would. It runs outside the source tree so
# that `import mnemos` finds the installed wheel, not the checkout.
fresh_install() {
    local venv="$OUT/fresh/py$1" python
    python=$(uv python find "$1") || return 1
    "$python" -m venv "$venv" \
        && "$venv/bin/pip" install --quiet --upgrade pip \
        && "$venv/bin/pip" install --quiet "$DIST"/mnemos*.whl \
        || return 1
    (cd "$OUT" && "$venv/bin/python" - <<'PY'
import asyncio
import importlib.metadata as md

from mnemos.simple_mcp import SIMPLE_TOOL_NAMES, simple_mcp

print("resolved mcp:", md.version("mcp"))
tools = {t.name for t in asyncio.run(simple_mcp.list_tools())}
if tools != set(SIMPLE_TOOL_NAMES):
    raise SystemExit(
        f"tool surface mismatch: {sorted(tools)} != {sorted(SIMPLE_TOOL_NAMES)}"
    )
print(f"Fresh install OK: {len(tools)} simple tools registered")
PY
    )
}

pip_audit() {
    uv export --frozen --no-dev --no-hashes --output-file "$OUT/runtime-requirements.txt" \
        && uvx pip-audit --no-deps --disable-pip -r "$OUT/runtime-requirements.txt"
}

bandit() {
    uvx bandit -q -lll \
        mnemos/simple_runtime.py mnemos/simple_mcp.py mnemos/simple_scope.py \
        mnemos/backup.py mnemos/file_security.py mnemos/store/sqlite_store.py \
        mnemos/setup/scheduler.py mnemos/cli.py mnemos/llm.py \
        mnemos/integrations/hermes/*.py \
        && echo "no high-severity findings"
}

blackbox() {
    local venv="$OUT/blackbox"
    uv venv -q "$venv" --python 3.12 \
        && uv pip install -q --python "$venv/bin/python" "$DIST"/mnemos*.whl \
        && "$venv/bin/python" scripts/release_blackbox.py --mnemos "$venv/bin/mnemos"
}

# Quick checks first, so a broken build shows in seconds, not after the tests.
step "up to date with main" '' up_to_date
step "lockfile matches pyproject" '' uv lock --check
step "ruff (3.13)" '' in_env py3.13 uv run --python 3.13 --extra dev ruff check mnemos
for v in $VERSIONS; do
    step "compile entrypoints ($v)" '' compile_entrypoints "$v"
done
step "build" '\.whl$|\.tar\.gz$' build
step "wheel contents" '' wheel_contents
step "twine check" 'PASSED|FAILED|ERROR' twine_check
for v in $VERSIONS; do
    step "fresh install ($v)" 'resolved mcp|Fresh install|Error|error' fresh_install "$v"
done
step "pip-audit" 'vulnerabilit' pip_audit
step "bandit -lll" '' bandit
step "black box (macOS)" '"result"' blackbox
for v in 3.10 3.11 3.12; do
    step "tests ($v)" '^[0-9]+ (passed|failed|error)' in_env "py$v" uv run --python "$v" --extra dev --extra mcp pytest -q
done
step "tests + coverage (3.13)" 'Total coverage|^[0-9]+ (passed|failed|error)' \
    in_env py3.13 uv run --python 3.13 --extra dev --extra mcp pytest -q --cov --cov-report=term
step "tests, meaning search (3.13)" '^[0-9]+ (passed|failed|error)' \
    in_env meaning uv run --python 3.13 --extra dev --extra mcp --extra embeddings pytest -q

SUMMARY="$OUT/summary.md"
{
    if [ $FAILED -eq 0 ]; then
        echo "**Local CI passed** on \`$SHORT\` ($SUBJECT)"
    else
        echo "**Local CI failed: $FAILED step(s)** on \`$SHORT\` ($SUBJECT)"
    fi
    echo
    echo "\`scripts/local_ci.sh\`, every step of \`release-hardening.yml\`, run on macOS $(sw_vers -productVersion 2>/dev/null || uname -r) ($(uname -m)), $(date '+%Y-%m-%d %H:%M %Z'), $(uv --version)."
    echo
    echo "| step | result | time | detail |"
    echo "|---|---|---|---|"
    cat "$ROWS"
    echo
    echo "**Not run here:** the black box on Linux and on Windows (they need those machines), and CodeQL (it runs only on GitHub)."
} > "$SUMMARY"

if [ $KEEP -eq 0 ]; then
    rm -rf "$SRC" "$OUT/env" "$OUT/fresh" "$OUT/blackbox"
fi

echo
if [ $FAILED -eq 0 ]; then echo "ALL PASSED"; else echo "$FAILED STEP(S) FAILED"; fi
echo "Not run here: black box on Linux and Windows, CodeQL."
echo "summary for the pull request: $SUMMARY"
echo "  gh pr comment <number> --body-file $SUMMARY"
[ $FAILED -eq 0 ]
