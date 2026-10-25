#!/bin/sh
set -e
mkdir -p /etc/caddy/tls.d
if [ "$TLS_MODE" = "internal" ]; then
  echo "tls internal" > /etc/caddy/tls.d/tls.caddy
else
  echo "# automatic HTTPS (Let's Encrypt / ZeroSSL)" > /etc/caddy/tls.d/tls.caddy
fi
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
