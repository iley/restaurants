#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

git push
SHA=$(git rev-parse HEAD)

echo "Waiting for CI run to start..."
while true; do
    RUN_ID=$(gh run list --commit "$SHA" --json databaseId --jq '.[0].databaseId' 2>/dev/null)
    if [ -n "$RUN_ID" ]; then
        break
    fi
    sleep 2
done

echo "Waiting for CI to complete..."
gh run watch "$RUN_ID" --exit-status

"$SCRIPT_DIR/deploy.sh" "$@"
