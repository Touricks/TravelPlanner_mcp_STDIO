#!/bin/bash
set -euo pipefail

usage() {
    echo "Usage: $0 <trip-id> [--stage N] [--dry-run]"
    echo "  trip-id:   e.g. 2026-04-san-francisco"
    echo "  --stage N: run only stage N (2-7)"
    echo "  --dry-run: print commands without executing"
    exit 1
}

[[ $# -lt 1 ]] && usage

TRIP_ID="$1"; shift
STAGE=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --stage) STAGE="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) usage ;;
    esac
done

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TRIP_DIR="$PROJECT_ROOT/assets/data/$TRIP_ID"
CONTRACTS="$PROJECT_ROOT/assets/configs/contracts"
PROFILE="$PROJECT_ROOT/prototype/userProfile/profile.yaml"
GUARDRAILS="$PROJECT_ROOT/assets/configs/guardrails.yaml"

mkdir -p "$TRIP_DIR"

run_cmd() {
    if $DRY_RUN; then
        echo "[dry-run] $*"
    else
        "$@"
    fi
}

should_run() {
    [[ -z "$STAGE" ]] || [[ "$STAGE" == "$1" ]]
}

# --- Stage 2: POI Search ---
if should_run 2; then
    echo "=== Stage 2: POI Search ==="
    PROMPT=$(python3 -c "
import sys; sys.path.insert(0, '$PROJECT_ROOT')
from pipeline.stages.stage_prompts import load_prompt
print(load_prompt('stage-2-poi-search', {
    'destination': '$TRIP_ID',
    'profile': open('$PROFILE').read()
}))
")
    run_cmd claude -p "$PROMPT" \
        --output-format json \
        --json-schema "$(cat "$CONTRACTS/poi-candidates.json")" \
        --allowedTools "WebSearch" \
        --max-turns 10 \
        | jq '.structured_output' > "$TRIP_DIR/poi-candidates.json"
    echo "  -> $TRIP_DIR/poi-candidates.json"
fi

# --- Stage 3: Itinerary Scheduling ---
if should_run 3; then
    echo "=== Stage 3: Scheduling ==="
    PROMPT=$(python3 -c "
import sys; sys.path.insert(0, '$PROJECT_ROOT')
from pipeline.stages.stage_prompts import load_prompt
print(load_prompt('stage-3-scheduling', {
    'guardrails': open('$GUARDRAILS').read()
}))
")
    cat "$TRIP_DIR/poi-candidates.json" | \
        run_cmd claude -p "$PROMPT" \
            --output-format json \
            --json-schema "$(cat "$CONTRACTS/itinerary.json")" \
            --max-turns 5 \
            | jq '.structured_output' > "$TRIP_DIR/itinerary.json"

    echo "  Running rule engine..."
    python3 "$PROJECT_ROOT/rules/evaluate.py" \
        "$TRIP_DIR/itinerary.json" \
        "$GUARDRAILS" \
        > "$TRIP_DIR/rule-check.json"

    if [[ $(jq '.pass' "$TRIP_DIR/rule-check.json") != "true" ]]; then
        echo "  BLOCKED: hard constraint violations detected"
        jq '.hard_violations' "$TRIP_DIR/rule-check.json"
        exit 1
    fi
    echo "  -> $TRIP_DIR/itinerary.json (rules passed)"
fi

# --- Stage 4a: Restaurant Recommendations ---
if should_run 4; then
    echo "=== Stage 4a: Restaurants ==="
    PROMPT=$(python3 -c "
import sys; sys.path.insert(0, '$PROJECT_ROOT')
from pipeline.stages.stage_prompts import load_prompt
print(load_prompt('stage-4a-restaurants'))
")
    cat "$TRIP_DIR/itinerary.json" | \
        run_cmd claude -p "$PROMPT" \
            --output-format json \
            --json-schema "$(cat "$CONTRACTS/restaurants.json")" \
            --allowedTools "WebSearch" \
            --max-turns 10 \
            | jq '.structured_output' > "$TRIP_DIR/restaurants.json"
    echo "  -> $TRIP_DIR/restaurants.json"

    echo "=== Stage 4b: Hotels ==="
    PROMPT=$(python3 -c "
import sys; sys.path.insert(0, '$PROJECT_ROOT')
from pipeline.stages.stage_prompts import load_prompt
print(load_prompt('stage-4b-hotels'))
")
    cat "$TRIP_DIR/itinerary.json" | \
        run_cmd claude -p "$PROMPT" \
            --output-format json \
            --json-schema "$(cat "$CONTRACTS/hotels.json")" \
            --allowedTools "WebSearch" \
            --max-turns 10 \
            | jq '.structured_output' > "$TRIP_DIR/hotels.json"
    echo "  -> $TRIP_DIR/hotels.json"
fi

# --- Stage 5: Review & Validation ---
if should_run 5; then
    echo "=== Stage 5: Review ==="
    python3 "$PROJECT_ROOT/rules/evaluate.py" \
        "$TRIP_DIR/itinerary.json" \
        "$GUARDRAILS" \
        --soft \
        > "$TRIP_DIR/rule-report.json"

    python3 "$PROJECT_ROOT/review/codex_review.py" \
        "$TRIP_DIR/itinerary.json" \
        "$TRIP_DIR/restaurants.json" \
        "$TRIP_DIR/hotels.json" \
        > "$TRIP_DIR/codex-report.json"

    python3 "$PROJECT_ROOT/review/merge_report.py" \
        "$TRIP_DIR/rule-report.json" \
        "$TRIP_DIR/codex-report.json" \
        > "$TRIP_DIR/review-report.json"

    REJECTED=$(jq '.summary.rejected' "$TRIP_DIR/review-report.json")
    if [[ "$REJECTED" -gt 0 ]]; then
        echo "  BLOCKED: $REJECTED items rejected"
        jq '.items[] | select(.verdict == "reject")' "$TRIP_DIR/review-report.json"
        exit 1
    fi
    echo "  -> $TRIP_DIR/review-report.json (passed)"
fi

# --- Stage 6: Notion Visualization ---
if should_run 6; then
    echo "=== Stage 6: Notion Publishing ==="
    MANIFEST=$(python3 "$PROJECT_ROOT/output/notion_publisher.py" \
        "$TRIP_DIR/itinerary.json" \
        "$TRIP_DIR/restaurants.json" \
        "$TRIP_DIR/hotels.json" \
        "$TRIP_DIR/review-report.json")

    PROMPT=$(python3 -c "
import sys; sys.path.insert(0, '$PROJECT_ROOT')
from pipeline.stages.stage_prompts import load_prompt
print(load_prompt('stage-6-notion'))
")
    echo "$MANIFEST" | \
        run_cmd claude -p "$PROMPT" \
            --allowedTools "mcp__notion__*" \
            --max-turns 20
    echo "  -> Notion pages created"
fi

# --- Stage 7: Screenshot Verification ---
if should_run 7; then
    echo "=== Stage 7: Screenshot Verification ==="
    PROMPT=$(python3 -c "
import sys; sys.path.insert(0, '$PROJECT_ROOT')
from pipeline.stages.stage_prompts import load_prompt
print(load_prompt('stage-7-verify'))
")
    run_cmd claude -p "$PROMPT" \
        --allowedTools "mcp__plugin_playwright_playwright__*,mcp__computer-use__*" \
        --max-turns 10
    echo "  -> Verification complete"
fi

echo "=== Pipeline complete for $TRIP_ID ==="
