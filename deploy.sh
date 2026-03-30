#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ANSIBLE_DIR="$SCRIPT_DIR/ansible"
SECRET_KEY_FILE="$ANSIBLE_DIR/secret_key"

if [ ! -f "$SECRET_KEY_FILE" ]; then
    python3 -c "import secrets; print(secrets.token_urlsafe(50))" > "$SECRET_KEY_FILE"
    chmod 600 "$SECRET_KEY_FILE"
    echo "Generated new secret key at $SECRET_KEY_FILE"
fi

SECRET_KEY=$(cat "$SECRET_KEY_FILE")

uvx --from ansible ansible-playbook \
    -i "$ANSIBLE_DIR/inventory.ini" \
    "$ANSIBLE_DIR/playbook.yml" \
    --extra-vars "django_secret_key=$SECRET_KEY" \
    "$@"
