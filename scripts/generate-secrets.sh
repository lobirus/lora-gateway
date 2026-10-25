#!/usr/bin/env bash
# Fill every "change-me" value in .env with a fresh random secret. Existing real values are left untouched.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
chmod 600 .env
gen() {
  case "$1" in
    LITELLM_MASTER_KEY) echo "sk-$(openssl rand -hex 32)" ;;
    ENCRYPTION_KEY) python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())" ;;
    POSTGRES_PASSWORD) openssl rand -hex 24 ;;
    *) openssl rand -hex 32 ;;
  esac
}
for var in POSTGRES_PASSWORD LITELLM_MASTER_KEY LITELLM_SALT_KEY JWT_SECRET ENCRYPTION_KEY; do
  if grep -qE "^${var}=change-me$" .env; then
    val="$(gen "$var")"
    # values are hex / urlsafe-base64, safe for sed with the | delimiter
    sed -i "s|^${var}=change-me$|${var}=${val}|" .env
    echo "generated $var"
  fi
done
if grep -qE '^PUBLIC_HOST=(gateway\.example\.com)?$' .env; then
  echo "NOTE: set PUBLIC_HOST in .env to your server's DNS name before 'docker compose up -d'." >&2
fi
