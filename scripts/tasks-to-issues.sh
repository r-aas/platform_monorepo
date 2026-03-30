#!/usr/bin/env bash
# Convert spec tasks.md to GitLab Issues
# Usage: ./scripts/tasks-to-issues.sh <spec-number> [--dry-run]
set -euo pipefail

SPEC_NUM="${1:?Usage: tasks-to-issues.sh <spec-number> [--dry-run]}"
DRY_RUN="${2:-}"
GITLAB_URL="${GITLAB_URL:-http://gitlab.platform.127.0.0.1.nip.io}"
GITLAB_TOKEN="${GITLAB_TOKEN:-${GITLAB_PAT:-}}"
PROJECT_PATH="${GITLAB_PROJECT:-root/platform_monorepo}"

# Get project ID
PROJECT_ID=$(curl -sf "$GITLAB_URL/api/v4/projects/$(echo "$PROJECT_PATH" | sed 's|/|%2F|g')?private_token=$GITLAB_TOKEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

SPEC_DIR=$(find specs -maxdepth 1 -type d -name "${SPEC_NUM}-*" | head -1)
if [ -z "$SPEC_DIR" ] || [ ! -d "$SPEC_DIR" ]; then
    echo "ERROR: No spec directory matching specs/${SPEC_NUM}-*"
    exit 1
fi

TASKS_FILE="$SPEC_DIR/tasks.md"
if [ ! -f "$TASKS_FILE" ]; then
    echo "ERROR: No tasks.md in $SPEC_DIR"
    exit 1
fi

SPEC_NAME=$(basename $SPEC_DIR)
echo "=== Converting $SPEC_NAME tasks to GitLab Issues ==="
echo "    Project: $PROJECT_PATH (ID: $PROJECT_ID)"

# Ensure label exists
if [ -z "$DRY_RUN" ]; then
    curl -sf "$GITLAB_URL/api/v4/projects/$PROJECT_ID/labels" \
        -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        -d "name=spec:${SPEC_NUM}&color=#428BCA" 2>/dev/null || true
fi

# Parse tasks
CURRENT_PHASE=""
CREATED=0
SKIPPED=0

while IFS= read -r line; do
    # Detect phase headers
    if echo "$line" | grep -qE '^## Phase'; then
        CURRENT_PHASE=$(echo "$line" | sed 's/^## //')
    fi

    # Detect task headers (### TXXX)
    if echo "$line" | grep -qE '^### T[0-9]+'; then
        TASK_ID=$(echo "$line" | grep -oE 'T[0-9]+')
        TASK_TITLE=$(echo "$line" | sed 's/^### //' | sed "s/${TASK_ID}[: ]*//" | sed 's/ *\[P\] *//' | sed 's/^ *//')

        # Collect task body until next ### or ##
        TASK_BODY=""
        DONE_COUNT=0
        TOTAL_COUNT=0
        while IFS= read -r subline; do
            if echo "$subline" | grep -qE '^###? '; then
                # Push back — we'll catch this on next iteration
                break
            fi
            TASK_BODY="${TASK_BODY}${subline}\n"
            if echo "$subline" | grep -qE '^\- \[x\]'; then
                DONE_COUNT=$((DONE_COUNT + 1))
                TOTAL_COUNT=$((TOTAL_COUNT + 1))
            elif echo "$subline" | grep -qE '^\- \[ \]'; then
                TOTAL_COUNT=$((TOTAL_COUNT + 1))
            fi
        done

        # Determine status
        if [ "$TOTAL_COUNT" -gt 0 ] && [ "$DONE_COUNT" -eq "$TOTAL_COUNT" ]; then
            STATUS="closed"
        else
            STATUS="open"
        fi

        ISSUE_TITLE="[${SPEC_NUM}] ${TASK_ID}: ${TASK_TITLE}"
        LABELS="spec:${SPEC_NUM}"
        [ -n "$CURRENT_PHASE" ] && LABELS="${LABELS},phase:$(echo "$CURRENT_PHASE" | grep -oE 'Phase [0-9]+' | tr ' ' '-' | tr '[:upper:]' '[:lower:]')"

        if [ -n "$DRY_RUN" ]; then
            echo "  [DRY-RUN] Would create: $ISSUE_TITLE (${STATUS}, labels: ${LABELS})"
            CREATED=$((CREATED + 1))
        else
            # Check if issue already exists
            EXISTING=$(curl -sf "$GITLAB_URL/api/v4/projects/$PROJECT_ID/issues?search=${TASK_ID}&private_token=$GITLAB_TOKEN" 2>/dev/null | python3 -c "import sys,json; issues=json.load(sys.stdin); print(len([i for i in issues if '${TASK_ID}:' in i['title']]))" 2>/dev/null || echo "0")

            if [ "$EXISTING" != "0" ]; then
                echo "  [SKIP] $ISSUE_TITLE (already exists)"
                SKIPPED=$((SKIPPED + 1))
            else
                RESPONSE=$(curl -sf "$GITLAB_URL/api/v4/projects/$PROJECT_ID/issues" \
                    -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
                    -d "title=$(echo "$ISSUE_TITLE" | python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.stdin.read().strip()))')" \
                    -d "labels=$LABELS" \
                    --data-urlencode "description=$(echo -e "$TASK_BODY")" 2>&1)

                IID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('iid','ERROR'))" 2>/dev/null || echo "ERROR")

                if [ "$IID" = "ERROR" ]; then
                    echo "  [FAIL] $ISSUE_TITLE"
                else
                    echo "  [OK] #$IID: $ISSUE_TITLE"
                    # Close if all done
                    if [ "$STATUS" = "closed" ]; then
                        curl -sf "$GITLAB_URL/api/v4/projects/$PROJECT_ID/issues/$IID" \
                            -X PUT -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
                            -d "state_event=close" >/dev/null 2>&1
                        echo "       → closed (all subtasks done)"
                    fi
                    CREATED=$((CREATED + 1))
                fi
            fi
        fi
    fi
done < "$TASKS_FILE"

echo ""
echo "=== Done: $CREATED created, $SKIPPED skipped ==="
