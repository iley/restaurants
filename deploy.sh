#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ANSIBLE_DIR="$SCRIPT_DIR/ansible"
SECRETS_FILE="$ANSIBLE_DIR/secrets.yml"

if [ ! -f "$SECRETS_FILE" ]; then
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
    cat > "$SECRETS_FILE" <<EOF
django_secret_key: "$SECRET_KEY"
google_places_api_key: ""
EOF
    chmod 600 "$SECRETS_FILE"
    echo "Created $SECRETS_FILE — edit it to add your Google Places API key."
fi

uvx --from ansible-core ansible-galaxy collection install \
    -r "$ANSIBLE_DIR/requirements.yml"

uvx --from ansible-core ansible-playbook \
    -i "$ANSIBLE_DIR/inventory.ini" \
    "$ANSIBLE_DIR/playbook.yml" \
    --extra-vars "@$SECRETS_FILE" \
    "$@"
