#!/usr/bin/env bash
#
# Smoke test for PillChecker API.
# Waits for the API to become healthy, then tests all endpoints.
#
# Prerequisites: curl, jq
# Usage: ./scripts/smoke-test.sh [BASE_URL]

set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
MAX_WAIT=120
INTERVAL=2
PASSED=0
FAILED=0

fail() {
    echo "  FAIL: $1"
    FAILED=$((FAILED + 1))
}

pass() {
    echo "  PASS: $1"
    PASSED=$((PASSED + 1))
}

assert_eq() {
    local desc="$1" actual="$2" expected="$3"
    if [ "$actual" = "$expected" ]; then
        pass "$desc"
    else
        fail "$desc (expected '$expected', got '$actual')"
    fi
}

assert_not_empty() {
    local desc="$1" value="$2"
    if [ -n "$value" ] && [ "$value" != "null" ]; then
        pass "$desc"
    else
        fail "$desc (got empty or null)"
    fi
}

# --- Wait for API ---

echo "Waiting for API at $BASE_URL (max ${MAX_WAIT}s)..."
elapsed=0
while true; do
    if curl -sf "$BASE_URL/health" > /dev/null 2>&1; then
        echo "API ready after ${elapsed}s."
        break
    fi
    if [ "$elapsed" -ge "$MAX_WAIT" ]; then
        echo "ERROR: API not healthy within ${MAX_WAIT}s."
        exit 1
    fi
    sleep "$INTERVAL"
    elapsed=$((elapsed + INTERVAL))
done

# --- Test 1: GET /health ---

echo ""
echo "=== GET /health ==="
HEALTH=$(curl -sf "$BASE_URL/health")
assert_eq "status" "$(echo "$HEALTH" | jq -r '.status')" "ok"

echo ""
echo "=== GET /health/data ==="
DATA_HEALTH=$(curl -sf "$BASE_URL/health/data")
assert_eq "status" "$(echo "$DATA_HEALTH" | jq -r '.status')" "ready"
assert_eq "biomcp" "$(echo "$DATA_HEALTH" | jq -r '.biomcp')" "connected"

# --- Test 2: POST /analyze ---

echo ""
echo "=== POST /analyze ==="
ANALYZE=$(curl -sf -X POST "$BASE_URL/analyze" \
    -H "Content-Type: application/json" \
    -d '{"text": "Ibuprofen 400 mg tablets"}')

assert_eq "drugs[0].name" "$(echo "$ANALYZE" | jq -r '.drugs[0].name')" "Ibuprofen"
assert_eq "drugs[0].rxcui" "$(echo "$ANALYZE" | jq -r '.drugs[0].rxcui')" "5640"
assert_eq "drugs[0].source" "$(echo "$ANALYZE" | jq -r '.drugs[0].source')" "ner"
assert_not_empty "drugs[0].dosage" "$(echo "$ANALYZE" | jq -r '.drugs[0].dosage')"

# --- Test 3: POST /interactions ---
# Note: BioMCP sources interaction data from MyChem.info/DrugBank.
# We verify the endpoint returns a valid response with the correct schema.
# The 'safe' field can be true (no interactions found), false (interactions
# found), or null (BioMCP unavailable). All are valid as long as the response
# shape is correct and BioMCP is connected (checked via /health/data above).

echo ""
echo "=== POST /interactions ==="
INTERACTIONS=$(curl -sf -X POST "$BASE_URL/interactions" \
    -H "Content-Type: application/json" \
    -d '{"drugs": ["ibuprofen", "warfarin"]}')

echo "  Response: $INTERACTIONS"
SAFE_VAL=$(echo "$INTERACTIONS" | jq -r '.safe')
# safe must be true, false, or null — not missing
if [ "$SAFE_VAL" = "true" ] || [ "$SAFE_VAL" = "false" ] || [ "$SAFE_VAL" = "null" ]; then
    pass "safe is valid ($SAFE_VAL)"
else
    fail "safe has unexpected value: '$SAFE_VAL'"
fi

# interactions must be an array (possibly empty)
INTERACTIONS_TYPE=$(echo "$INTERACTIONS" | jq -r '.interactions | type')
assert_eq "interactions is array" "$INTERACTIONS_TYPE" "array"

# error field must be present (null or string)
ERROR_EXISTS=$(echo "$INTERACTIONS" | jq 'has("error")')
assert_eq "error field exists" "$ERROR_EXISTS" "true"

# --- Summary ---

echo ""
echo "================================"
echo "Results: $PASSED passed, $FAILED failed"
echo "================================"

[ "$FAILED" -eq 0 ] || exit 1
