#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

git push

echo "Waiting for CI to complete..."
gh run watch --exit-status

"$SCRIPT_DIR/deploy.sh" "$@"
