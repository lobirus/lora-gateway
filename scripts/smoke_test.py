#!/usr/bin/env python3
"""Smoke test: list the models visible to a virtual key and send one tiny chat completion to each.

Usage:
  export LORA_GATEWAY_API_KEY=<virtual key from the console>
  python3 scripts/smoke_test.py --base https://gateway.example.com [--models default,fast] [--insecure]

Each model call is a real (small) request and is billed by the upstream provider. Never prints the key.
"""
import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--base", default=os.environ.get("LORA_GATEWAY_URL", "http://127.0.0.1:4000"),
                help="gateway base URL, e.g. https://gateway.example.com (default: local LiteLLM port)")
ap.add_argument("--models", help="comma-separated model/alias names (default: everything /v1/models returns)")
ap.add_argument("--insecure", action="store_true", help="skip TLS verification (TLS_MODE=internal)")
a = ap.parse_args()
key = os.environ.get("LORA_GATEWAY_API_KEY")
if not key:
    sys.exit("set LORA_GATEWAY_API_KEY to a gateway virtual key")
ctx = ssl._create_unverified_context() if a.insecure else None
H = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "lora-smoke-test/1.0"}


def req(path, body=None):
    r = urllib.request.Request(a.base.rstrip("/") + path, data=json.dumps(body).encode() if body is not None else None,
                               headers=H)
    return json.load(urllib.request.urlopen(r, timeout=180, context=ctx))


models = a.models.split(",") if a.models else [m["id"] for m in req("/v1/models")["data"]]
failed = 0
for m in models:
    t0 = time.perf_counter()
    try:
        r = req("/v1/chat/completions", {"model": m, "max_tokens": 512,
                                         "messages": [{"role": "user", "content": "Reply with the single word: pong"}]})
        out = (r["choices"][0]["message"].get("content") or "").strip()[:40]
        print(f"OK   {m:40s} {round((time.perf_counter() - t0) * 1000):6d} ms  {out!r}")
    except urllib.error.HTTPError as e:
        failed += 1
        print(f"FAIL {m:40s} HTTP {e.code} {e.read()[:200]!r}")
    except Exception as e:  # noqa: BLE001
        failed += 1
        print(f"FAIL {m:40s} {e}")
sys.exit(1 if failed else 0)
