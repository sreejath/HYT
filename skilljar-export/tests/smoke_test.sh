#!/usr/bin/env bash
# End-to-end smoke test against a local fixture that mimics Skilljar's URL
# shapes: learning path -> courses -> lessons, including a SCORM lesson whose
# text lives in an iframe and only renders once scrolled.
set -euo pipefail

cd "$(dirname "$0")"
PORT="${PORT:-8899}"
WORK="$(mktemp -d)"
trap 'kill "${SERVER_PID:-}" 2>/dev/null || true; rm -rf "$WORK"' EXIT

python3 make_fixture.py "$WORK/fixture_site" >/dev/null
python3 -m http.server "$PORT" --directory "$WORK/fixture_site" >/dev/null 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 20); do
  curl -sf --noproxy '*' "http://127.0.0.1:$PORT/" >/dev/null && break
  sleep 0.5
done

echo '{"cookies":[],"origins":[]}' > "$WORK/auth.json"

BROWSER_ARGS=()
[ -n "${CHROMIUM_PATH:-}" ] && BROWSER_ARGS=(--browser-path "$CHROMIUM_PATH")

NO_PROXY='*' no_proxy='*' python3 ../skilljar_export.py \
  --auth-state "$WORK/auth.json" --out "$WORK/out" \
  --settle 800 --delay 100 "${BROWSER_ARGS[@]}" \
  "http://127.0.0.1:$PORT/path/claude-certified-associate-foundations/prompting-task-execution/486636/scorm/2dk4fzu1k4lj"

DOC="$WORK/out/claude-certified-associate-foundations.md"
fail=0
check() {
  if grep -qF "$2" "$DOC"; then echo "  ok   $1"; else echo "  FAIL $1"; fail=1; fi
}
refute() {
  if grep -qF "$2" "$DOC"; then echo "  FAIL $1"; fail=1; else echo "  ok   $1"; fi
}

echo "checks:"
check "both courses discovered"        "## Context and Tools"
check "lesson order preserved"         "### Prompt anatomy"
check "plain lesson body extracted"    "A workable prompt states"
check "SCORM iframe body extracted"    "Decomposition beats one giant instruction."
check "lazy iframe content scrolled in" "Always close the loop"
check "links absolutised"              "](http://127.0.0.1:$PORT/glossary)"
check "code fence '#' not demoted"     "# not a heading, a comment"
refute "nav chrome stripped"           "catalog chrome that must be stripped"
refute "footer chrome stripped"        "footer chrome that must be stripped"

test -f "$WORK/out/raw/002/00-data-js.js" \
  && echo "  ok   SCORM payload captured to raw/" \
  || { echo "  FAIL SCORM payload captured to raw/"; fail=1; }

[ "$fail" -eq 0 ] && echo "smoke test passed" || { echo "smoke test FAILED"; exit 1; }
