# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private
[security advisory form](../../security/advisories/new) for this repository instead.
Include the affected version/commit, a description, and steps to reproduce. You should get an
answer within a few days; fixes are released as soon as practical and credited if you wish.

## Scope and design notes

* The **LiteLLM master key** and all **provider API keys** stay on the server. The browser only holds a
  short-lived console session token (JWT); the Playground calls LiteLLM server-side with a virtual key.
* Provider keys and virtual keys are stored Fernet-encrypted (`ENCRYPTION_KEY`); console passwords are bcrypt-hashed.
* Only Caddy (80/443) is published. LiteLLM (`127.0.0.1:4000`) and the backend (`127.0.0.1:8000`) bind to
  localhost; Postgres and Redis are reachable only on the internal Docker network.
* The backend refuses to start with missing or placeholder secrets (`change-me`).
* There are no default credentials: the first admin password comes from `ADMIN_PASSWORD` or is generated
  randomly and printed once to the backend log.

## Hardening checklist for operators

* Keep `.env` at `chmod 600` and back it up together with database dumps (it holds the encryption keys).
* Change the generated admin password after the first login (*Settings*).
* Give every client its own virtual key with a budget and rate limit; revoke keys you no longer use.
* Keep images up to date (`docker compose pull && docker compose build --pull && docker compose up -d`).
* Consider restricting `/api/*` (the console) by IP or VPN if only a few people need it.
