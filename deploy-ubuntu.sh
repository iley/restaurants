#!/bin/bash
# Sibling to deploy.sh used during the Amazon Linux -> Ubuntu migration.
# Targets the new Ubuntu host via playbook-ubuntu.yml. Delete this script
# (and rename playbook-ubuntu.yml -> playbook.yml) once the old host is gone.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ANSIBLE_DIR="$SCRIPT_DIR/ansible"
SECRETS_FILE="$ANSIBLE_DIR/secrets.yml"

if [ ! -f "$SECRETS_FILE" ]; then
    echo "Missing $SECRETS_FILE — run ./deploy.sh once first to generate it." >&2
    exit 1
fi

uvx --from ansible-core --with ansible ansible-playbook \
    -i "$ANSIBLE_DIR/inventory.ini" \
    "$ANSIBLE_DIR/playbook-ubuntu.yml" \
    --extra-vars "@$SECRETS_FILE" \
    "$@"
