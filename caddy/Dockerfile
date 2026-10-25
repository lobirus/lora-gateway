# Build the Vue frontend, then serve it with Caddy
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM caddy:2-alpine
COPY caddy/Caddyfile /etc/caddy/Caddyfile
COPY caddy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
COPY --from=web /web/dist /srv
ENTRYPOINT ["/entrypoint.sh"]
