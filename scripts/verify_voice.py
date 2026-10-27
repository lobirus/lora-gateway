#!/usr/bin/env python3
"""End-to-end voice + catalog checks over the PUBLIC HTTPS endpoint with a virtual key.

Usage: python3 scripts/verify_voice.py   (needs httpx + websockets; reads .env for host/admin, never prints secrets)
Checks: /v1/models lists audio models; speech (tts, tts-openai) returns valid audio (ffprobe); transcription and
translation (stt, listener, stt-openai) incl. a ~19 MB upload; realtime WebSocket handshakes and one spoken turn for
"talk" (open-weight pipeline) and "talk-openai"; error paths; one chat call per new Together model; audio rows in Logs.
"""
import asyncio
import base64
import json
import os
import subprocess
import time
import wave

import httpx
import websockets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
PUB = "https://" + env["PUBLIC_HOST"]
ADMIN = "http://127.0.0.1:8000"
OUT = "/tmp/lora-voice-verify"
os.makedirs(OUT, exist_ok=True)
rows = []


def rec(name, ok, ms, detail=""):
    rows.append((name, "PASS" if ok else "FAIL", f"{ms:.0f} ms" if ms is not None else "", detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:<46} {'' if ms is None else f'{ms:7.0f} ms'}  {detail}", flush=True)


def admin():
    r = httpx.post(ADMIN + "/api/auth/login", json={"username": env["ADMIN_USERNAME"], "password": env["ADMIN_PASSWORD"]})
    h = {"Authorization": "Bearer " + r.json()["access_token"]}
    keys = httpx.get(ADMIN + "/api/keys", headers=h).json()
    k = next(k for k in keys if k["name"] == os.environ.get("VERIFY_KEY_NAME", "default"))
    return h, httpx.get(ADMIN + f"/api/keys/{k['id']}/reveal", headers=h).json()["key"]


def ffprobe(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=format_name,duration:stream=codec_name,sample_rate",
                        "-of", "json", path], capture_output=True, text=True)
    j = json.loads(p.stdout or "{}")
    f, s = j.get("format", {}), (j.get("streams") or [{}])[0]
    return f"{f.get('format_name')} {s.get('codec_name')} {s.get('sample_rate')} Hz {float(f.get('duration', 0)):.2f} s"


def usd(v):
    return "USD %.6f" % float(v) if v not in (None, "") else "n/a"


def main():
    from datetime import datetime, timezone
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    h, key = admin()
    H = {"Authorization": f"Bearer {key}"}
    c = httpx.Client(base_url=PUB + "/v1", headers=H, timeout=300)

    t0 = time.perf_counter(); r = c.get("/models"); ms = (time.perf_counter() - t0) * 1000
    ids = [m["id"] for m in r.json().get("data", [])]
    want = ["stt", "tts", "talk", "listener", "stt-openai", "tts-openai", "talk-openai", "whisper-large-v3", "kokoro-82m", "lora-talk"]
    rec("GET /v1/models lists audio models", r.status_code == 200 and all(w in ids for w in want), ms,
        f"{len(ids)} ids; missing: {[w for w in want if w not in ids] or 'none'}")

    clips = {}
    for model, voice, text in [("tts", "af_heart", "Hello there. This is the Lora gateway speaking with an open-weight voice."),
                               ("tts-openai", "coral", "Hello from the gateway, now with an OpenAI voice.")]:
        t0 = time.perf_counter()
        with c.stream("POST", "/audio/speech", json={"model": model, "input": text, "voice": voice, "response_format": "mp3"}) as s:
            ttfb = (time.perf_counter() - t0) * 1000
            data = s.read()
        ms = (time.perf_counter() - t0) * 1000
        path = f"{OUT}/speech_{model}.mp3"
        open(path, "wb").write(data)
        info = ffprobe(path) if s.status_code == 200 else data[:200].decode(errors="replace")
        rec(f"POST /v1/audio/speech {model} ({voice})", s.status_code == 200 and "mp3" in info, ms,
            f"TTFB {ttfb:.0f} ms, {len(data)} B, {info}, cost {usd(s.headers.get('x-litellm-response-cost'))}")
        clips[model] = path

    for model in ("stt", "listener", "stt-openai"):
        t0 = time.perf_counter()
        r = c.post("/audio/transcriptions", data={"model": model, "language": "en"}, files={"file": ("speech.mp3", open(clips["tts"], "rb"), "audio/mpeg")})
        ms = (time.perf_counter() - t0) * 1000
        txt = r.json().get("text", "") if r.status_code == 200 else r.text[:200]
        rec(f"POST /v1/audio/transcriptions {model}", r.status_code == 200 and "gateway" in txt.lower(), ms,
            f"'{txt.strip()[:70]}' cost {usd(r.headers.get('x-litellm-response-cost'))}")
    t0 = time.perf_counter()
    r = c.post("/audio/translations", data={"model": "stt"}, files={"file": ("speech.mp3", open(clips["tts"], "rb"), "audio/mpeg")})
    rec("POST /v1/audio/translations stt", r.status_code == 200, (time.perf_counter() - t0) * 1000, (r.json().get("text", "") if r.status_code == 200 else r.text)[:70])

    big = f"{OUT}/big.wav"
    if not os.path.exists(big):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "120", "-i", clips["tts"], "-t", "600", "-ar", "16000", "-ac", "1", big], check=True)
    size = os.path.getsize(big)
    t0 = time.perf_counter()
    r = c.post("/audio/transcriptions", data={"model": "stt", "response_format": "json"}, files={"file": ("big.wav", open(big, "rb"), "audio/wav")})
    ms = (time.perf_counter() - t0) * 1000
    rec(f"large upload ({size / 1e6:.1f} MB WAV) -> stt", r.status_code == 200, ms,
        f"{len(r.json().get('text', '')) if r.status_code == 200 else r.text[:120]} chars; cost {usd(r.headers.get('x-litellm-response-cost'))}")

    asyncio.run(realtime_checks(key))

    for m in ("qwen3.8-2.4t", "kimi-k3", "gpt-oss-120b", "deepseek-v4-pro", "glm-5.3", "minimax-m3.1-flash"):
        t0 = time.perf_counter()
        r = c.post("/chat/completions", json={"model": m, "messages": [{"role": "user", "content": "Reply with exactly: pong"}], "max_tokens": 1024})
        ms = (time.perf_counter() - t0) * 1000
        out = (r.json()["choices"][0]["message"].get("content") or "").strip() if r.status_code == 200 else r.text[:120]
        rec(f"chat {m}", r.status_code == 200 and "pong" in out.lower(), ms, f"'{out[:30]}' cost {usd(r.headers.get('x-litellm-response-cost'))}")

    time.sleep(10)  # spend logs are batched
    logs = [l for l in httpx.get(ADMIN + "/api/logs", headers=h, params={"type": "audio", "hours": 1, "limit": 100}).json()["items"]
            if l["start_time"] >= started[:19]]
    kinds = {}
    for l in logs:
        kinds.setdefault(l["type"], []).append(l)
    rec("Logs: audio requests with cost", all(k in kinds for k in ("transcription", "speech", "realtime")) and all(l["cost"] > 0 for l in logs if l["status"] == "success"), None,
        "; ".join(f"{k}: {len(v)} rows, {usd(sum(x['cost'] for x in v))}" for k, v in kinds.items()))
    au = httpx.get(ADMIN + "/api/analytics/audio", headers=h, params={"hours": 1}).json()
    rec("Analytics /api/analytics/audio", au["types"]["transcription"]["requests"] > 0, None,
        f"{au['minutes_transcribed']} min transcribed, {au['characters_spoken']} chars, {au['realtime_minutes']} realtime min, {usd(au['cost'])}")
    print("\n| Check | Result | Latency | Detail |\n|---|---|---|---|")
    for r_ in rows:
        print("| " + " | ".join(str(x).replace("|", "/") for x in r_) + " |")


async def realtime_checks(key):
    url = PUB.replace("https", "wss") + "/v1/realtime?model="
    for label, model, hdr in [("no key", "talk", {}), ("unknown model", "nope", {"Authorization": f"Bearer {key}"}),
                              ("non-realtime model", "tts", {"Authorization": f"Bearer {key}"}),
                              ("bad key", "talk-openai", {"Authorization": "Bearer sk-invalid"})]:
        t0 = time.perf_counter()
        try:
            async with websockets.connect(url + model, additional_headers=hdr) as ws:
                ev = json.loads(await asyncio.wait_for(ws.recv(), 20))
            ok = ev.get("type") == "error"
            detail = (ev.get("error") or {}).get("message", "")[:90]
        except Exception as e:  # noqa: BLE001
            ok, detail = False, repr(e)[:90]
        rec(f"WS /v1/realtime error path: {label}", ok, (time.perf_counter() - t0) * 1000, detail)
    t0 = time.perf_counter()
    async with websockets.connect(url + "talk", subprotocols=["realtime", "openai-insecure-api-key." + key]) as ws:
        ev = json.loads(await asyncio.wait_for(ws.recv(), 20))
        proto = ws.subprotocol
    rec("WS /v1/realtime talk (browser subprotocol auth)", ev.get("type") == "session.created", (time.perf_counter() - t0) * 1000, f"subprotocol={proto}")
    q = f"{OUT}/question.pcm"
    if not os.path.exists(q):
        r = httpx.post(PUB + "/v1/audio/speech", headers={"Authorization": f"Bearer {key}"}, timeout=60,
                       json={"model": "tts", "input": "What is the capital of France? Answer in one short sentence.", "voice": "am_michael", "response_format": "wav"})
        open(f"{OUT}/question.wav", "wb").write(r.content)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{OUT}/question.wav", "-ar", "24000", "-ac", "1", "-f", "s16le", q], check=True)
    pcm = open(q, "rb").read()
    for model, voice in (("talk", "af_heart"), ("talk-openai", "marin")):
        t0 = time.perf_counter()
        async with websockets.connect(url + model, additional_headers={"Authorization": f"Bearer {key}"}, max_size=None) as ws:
            first = json.loads(await asyncio.wait_for(ws.recv(), 20))
            rec(f"WS /v1/realtime {model} handshake", first.get("type") == "session.created", (time.perf_counter() - t0) * 1000, first.get("type"))
            await ws.send(json.dumps({"type": "session.update", "session": {"type": "realtime", "instructions": "Answer in one short sentence.",
                                      "audio": {"input": {"turn_detection": None, "transcription": {"model": "gpt-4o-mini-transcribe"}}, "output": {"voice": voice}}}}))
            for i in range(0, len(pcm), 9600):
                await ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm[i:i + 9600]).decode()}))
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            ts = time.perf_counter()
            await ws.send(json.dumps({"type": "response.create"}))
            audio, tr, heard, first_audio, usage, gm = bytearray(), "", "", None, {}, None
            while True:
                ev = json.loads(await asyncio.wait_for(ws.recv(), 60))
                t = ev["type"]
                if t == "response.output_audio.delta":
                    first_audio = first_audio or (time.perf_counter() - ts) * 1000
                    audio += base64.b64decode(ev["delta"])
                elif t == "response.output_audio_transcript.delta":
                    tr += ev["delta"]
                elif t == "conversation.item.input_audio_transcription.completed":
                    heard = ev.get("transcript", "")
                elif t == "error":
                    print("   error event:", ev["error"].get("message"))
                elif t == "response.done":
                    usage, gm = ev["response"].get("usage", {}), ev["response"].get("gateway_metrics")
                    break
        path = f"{OUT}/realtime_{model}.wav"
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(bytes(audio))
        rec(f"WS /v1/realtime {model}: spoken question -> audio", len(audio) > 24000 and "paris" in tr.lower(), first_audio,
            f"{len(audio) / 48000:.1f} s audio, heard '{heard.strip()[:40]}', said '{tr.strip()[:50]}', "
            f"usage in/out {usage.get('input_tokens')}/{usage.get('output_tokens')}" + (f", pipeline {gm}" if gm else ""))


if __name__ == "__main__":
    main()
