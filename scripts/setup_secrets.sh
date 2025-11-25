#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT=${1:-dev}
SECRETS_DIR=".env"
mkdir -p "$SECRETS_DIR"
TARGET_FILE="$SECRETS_DIR/.env.$ENVIRONMENT"

if [[ -f "$TARGET_FILE" ]]; then
  echo "Secrets for $ENVIRONMENT already exist at $TARGET_FILE"
  exit 0
fi

echo "Fetching secrets for $ENVIRONMENT..."
# Placeholder: integrate with Vault/Cloudflare secrets CLI
cat <<EOT > "$TARGET_FILE"
# Binance / Cloudflare secrets for $ENVIRONMENT
BINANCE_API_KEY=
BINANCE_API_SECRET=
CLOUDFLARE_API_TOKEN=
D1_DATABASE_ID=
EOT

chmod 600 "$TARGET_FILE"
echo "Created secret template at $TARGET_FILE. Populate values manually or pipe from secret manager."
