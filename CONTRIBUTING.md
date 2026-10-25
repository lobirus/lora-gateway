# Contributing

Thanks for helping! Issues and pull requests are welcome.

* **Bugs / features**: open an issue first for anything larger than a small fix, so we can agree on the approach.
* **Security issues**: see [SECURITY.md](SECURITY.md); please don't file them publicly.
* **Development setup**: see *Development* in the [README](README.md). Run `cd frontend && npm ci && npm run build`
  (type-check + build) and `python -m compileall backend/app` before opening a PR; CI runs the same checks.
* **Style**: keep changes focused, follow the existing code style (FastAPI + SQLAlchemy 2 on the backend,
  Vue 3 `<script setup>` + TypeScript on the frontend, CSS variables from `frontend/src/styles.css`).
* **Never commit secrets**: no `.env`, real API keys, hostnames or database dumps. Use placeholders such as
  `gateway.example.com` and `$LORA_GATEWAY_API_KEY`.

By contributing you agree that your contributions are licensed under the MIT License.
