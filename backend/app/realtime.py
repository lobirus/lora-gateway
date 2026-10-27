"""Realtime voice at /v1/realtime (OpenAI Realtime protocol over WebSocket).

Two engines behind one endpoint:
* relay    - realtime models served by a provider (OpenAI gpt-realtime ...): frames are relayed to LiteLLM's
             /v1/realtime with the caller's virtual key, so LiteLLM authorises, budgets and logs the session.
* pipeline - the gateway's own open-weight voice pipeline (provider kind "pipeline", e.g. alias "talk"): speech-to-text
             -> chat model -> text-to-speech, each step a normal LiteLLM request made with the caller's virtual key
             (so every step is authorised, budgeted and logged, tagged voice:talk). It implements the subset of the
             Realtime protocol voice clients use:
               client: session.update, input_audio_buffer.append / commit / clear, conversation.item.create
                       (user input_text), response.create, response.cancel
               server: session.created / updated, input_audio_buffer.speech_started / speech_stopped / committed /
                       cleared, conversation.item.created, conversation.item.input_audio_transcription.completed,
                       response.created, response.output_item.added, response.content_part.added,
                       response.output_audio_transcript.delta / done, response.output_audio.delta / done,
                       response.content_part.done, response.output_item.done, response.done, error
             Audio is PCM16 mono 24 kHz both ways (the Realtime default). Clients that send "OpenAI-Beta: realtime=v1"
             get the beta event names (response.audio.delta, response.audio_transcript.delta ...). Turn detection:
             server_vad (energy based, configurable silence_duration_ms / threshold) or none (push-to-talk: commit +
             response.create).
"""
import array
import asyncio
import base64
import io
import json
import logging
import math
import re
import struct
import time
import uuid
import wave
from urllib.parse import quote

import httpx
import websockets
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from .config import settings
from .db import Alias, Model, SessionLocal
from .litellm_sync import deployable, is_pipeline

log = logging.getLogger("gateway.realtime")
RATE = 24000
USER_AGENT = "gw-realtime/1.0"
DEFAULT_INSTRUCTIONS = ("You are a helpful, friendly voice assistant. You are talking out loud, so answer in short, natural "
                        "spoken sentences (usually one to three), without markdown, lists, code blocks or emojis. "
                        "Reply in the language the user speaks.")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def resolve(db, name: str) -> Model | None:
    m = db.scalar(select(Model).where(Model.model_name == name))
    if m:
        return m
    a = db.scalar(select(Alias).where(Alias.name == name))
    return a.target if a else None


def model_info(name: str) -> dict | None:
    db = SessionLocal()
    try:
        m = resolve(db, name)
        if not m:
            return None
        info = {"name": name, "resolved": m.model_name, "kind": m.kind or "chat", "pipeline": is_pipeline(m),
                "live": deployable(m), "upstream": m.upstream_id, "voice": m.default_voice, "voices": m.voices or []}
        if info["pipeline"]:
            parts = [x.strip() for x in m.upstream_id.split("|")]
            if len(parts) != 3:
                info["error"] = f"Pipeline model {m.model_name} needs upstream id '<stt> | <chat> | <tts>'"
            else:
                info["stt"], info["llm"], info["tts"] = parts
                llm = resolve(db, parts[1])
                info["llm_reasoning_off"] = bool(llm and "off" in (llm.reasoning_efforts or []))
                tts = resolve(db, parts[2])
                info["tts_voices"] = (tts.voices or []) if tts else []
                info["tts_default_voice"] = tts.default_voice if tts else None
        return info
    finally:
        db.close()


# ---------------------------------------------------------------- audio helpers
def pcm16_to_wav(pcm: bytes, rate: int = RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def wav_to_pcm16_24k(data: bytes) -> bytes:
    """Decode a WAV (PCM16 or float32, any rate/channels) to PCM16 mono 24 kHz."""
    if data[:4] != b"RIFF":
        raise ValueError("not a WAV file")
    pos, fmt, rate, ch, bits, payload = 12, 1, RATE, 1, 16, b""
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size] if size != 0xFFFFFFFF else data[pos + 8:]
        if cid == b"fmt ":
            fmt, ch, rate = struct.unpack("<HHI", body[:8])
            bits = struct.unpack("<H", body[14:16])[0]
            if fmt == 0xFFFE and len(body) >= 26:  # WAVE_FORMAT_EXTENSIBLE: subformat GUID starts at 24
                fmt = struct.unpack("<H", body[24:26])[0]
        elif cid == b"data":
            payload = body
            break
        pos += 8 + size + (size & 1)
    if fmt == 3 and bits == 32:
        f = array.array("f")
        f.frombytes(payload[: len(payload) // 4 * 4])
        samples = array.array("h", (max(-32768, min(32767, int(x * 32767))) for x in f))
    elif fmt == 1 and bits == 16:
        samples = array.array("h")
        samples.frombytes(payload[: len(payload) // 2 * 2])
    else:
        raise ValueError(f"unsupported WAV format {fmt}/{bits}")
    if ch > 1:
        samples = array.array("h", (sum(samples[i:i + ch]) // ch for i in range(0, len(samples) - ch + 1, ch)))
    if rate != RATE:
        n = int(len(samples) * RATE / rate)
        step = rate / RATE
        out = array.array("h", [0]) * n
        for i in range(n):
            x = i * step
            j = int(x)
            a = samples[j] if j < len(samples) else 0
            b = samples[j + 1] if j + 1 < len(samples) else a
            out[i] = int(a + (b - a) * (x - j))
        samples = out
    return samples.tobytes()


def rms(pcm: bytes) -> float:
    a = array.array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    if not a:
        return 0.0
    return math.sqrt(sum(x * x for x in a) / len(a)) / 32768


SENTENCE_END = re.compile(r"([.!?…。！？]+[\"')\]]*\s+|\n+)")


def speakable(text: str) -> str:
    t = re.sub(r"\x60{3}.*?\x60{3}", " ", text, flags=re.S)
    t = re.sub(r"[*_#\x60>|]+", "", t)
    t = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------- pipeline session
class PipelineSession:
    def __init__(self, ws: WebSocket, info: dict, key: str, tags: str, beta: bool):
        self.ws, self.info, self.key, self.tags, self.beta = ws, info, key, tags, beta
        self.session_id = _id("sess")
        self.voice = info.get("voice") or info.get("tts_default_voice") or "af_heart"
        self.instructions = DEFAULT_INSTRUCTIONS
        self.turn_detection: dict | None = {"type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300,
                                            "silence_duration_ms": 600, "create_response": True, "interrupt_response": True}
        self.transcribe_input = True
        self.language: str | None = None
        self.buffer = bytearray()
        self.history: list[dict] = []
        self.response_task: asyncio.Task | None = None
        self.pending_audio: tuple | None = None
        self.send_lock = asyncio.Lock()
        # VAD state
        self.vad_speaking = False
        self.voiced_frames = 0
        self.silent_ms = 0
        self.noise = 0.004
        self.speech_start_ms = 0
        self.audio_ms = 0
        self.http = httpx.AsyncClient(base_url=settings.litellm_url, timeout=httpx.Timeout(120.0, connect=10.0),
                                      headers={"Authorization": f"Bearer {key}", "x-litellm-tags": tags, "User-Agent": USER_AGENT})

    # event names (GA by default, beta aliases when the client asked for realtime=v1)
    def n(self, ga: str) -> str:
        if not self.beta:
            return ga
        return ga.replace("response.output_audio_transcript", "response.audio_transcript").replace("response.output_audio", "response.audio").replace("response.output_text", "response.text")

    async def emit(self, typ: str, **kw):
        async with self.send_lock:
            await self.ws.send_text(json.dumps({"type": self.n(typ), "event_id": _id("event"), **kw}))

    async def error(self, message: str, code: str = "pipeline_error", event_id: str | None = None):
        await self.emit("error", error={"type": "invalid_request_error" if code == "invalid" else "server_error",
                                        "code": code, "message": message, "event_id": event_id})

    def session_obj(self) -> dict:
        td = self.turn_detection
        if self.beta:
            return {"id": self.session_id, "object": "realtime.session", "model": self.info["name"], "modalities": ["audio", "text"],
                    "instructions": self.instructions, "voice": self.voice, "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16", "turn_detection": td,
                    "input_audio_transcription": {"model": self.info["stt"]} if self.transcribe_input else None}
        return {"id": self.session_id, "object": "realtime.session", "type": "realtime", "model": self.info["name"],
                "output_modalities": ["audio"], "instructions": self.instructions,
                "audio": {"input": {"format": {"type": "audio/pcm", "rate": RATE}, "turn_detection": td,
                                    "transcription": {"model": self.info["stt"], "language": self.language} if self.transcribe_input else None},
                          "output": {"format": {"type": "audio/pcm", "rate": RATE}, "voice": self.voice}},
                "gateway": {"engine": "pipeline", "stt": self.info["stt"], "llm": self.info["llm"], "tts": self.info["tts"]}}

    # ------------------------------------------------------------ main loop
    async def run(self):
        await self.emit("session.created", session=self.session_obj())
        try:
            while True:
                raw = await self.ws.receive_text()
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    await self.error("Invalid JSON", "invalid")
                    continue
                await self.handle(ev)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if self.response_task:
                self.response_task.cancel()
            await self.http.aclose()

    async def handle(self, ev: dict):
        t = ev.get("type")
        eid = ev.get("event_id")
        if t == "session.update":
            self.apply_session(ev.get("session") or {})
            await self.emit("session.updated", session=self.session_obj())
        elif t == "input_audio_buffer.append":
            try:
                chunk = base64.b64decode(ev.get("audio") or "")
            except ValueError:
                await self.error("audio must be base64 PCM16", "invalid", eid)
                return
            self.buffer.extend(chunk)
            if self.turn_detection:
                await self.vad(chunk)
            else:
                self.audio_ms += len(chunk) // 48
        elif t == "input_audio_buffer.commit":
            if len(self.buffer) < RATE * 2 // 10:  # < 100 ms
                await self.error("Buffer too small: commit needs at least 100 ms of audio", "input_audio_buffer_commit_empty", eid)
                return
            await self.commit()
        elif t == "input_audio_buffer.clear":
            self.buffer.clear()
            await self.emit("input_audio_buffer.cleared")
        elif t == "conversation.item.create":
            item = ev.get("item") or {}
            texts = [c.get("text", "") for c in item.get("content") or [] if c.get("type") in ("input_text", "text")]
            role = item.get("role") or "user"
            if item.get("type", "message") == "message" and texts and role in ("user", "assistant", "system"):
                iid = item.get("id") or _id("item")
                self.history.append({"role": role, "content": " ".join(texts), "id": iid})
                await self.emit("conversation.item.created", previous_item_id=None,
                                item={"id": iid, "object": "realtime.item", "type": "message", "role": role, "status": "completed",
                                      "content": [{"type": "input_text", "text": " ".join(texts)}]})
            else:
                await self.error("Only text messages are supported in conversation.item.create", "invalid", eid)
        elif t == "response.create":
            r = ev.get("response") or {}
            await self.start_response(r.get("instructions"))
        elif t == "response.cancel":
            await self.cancel_response()
        else:
            # accepted but not implemented by the pipeline (e.g. function calls): tell the client, do not drop the session
            await self.error(f"Event '{t}' is not supported by the gateway voice pipeline", "unsupported_event", eid)

    def apply_session(self, s: dict):
        if s.get("instructions") is not None:
            self.instructions = s["instructions"] or DEFAULT_INSTRUCTIONS
        audio = s.get("audio") or {}
        v = s.get("voice") or (audio.get("output") or {}).get("voice")
        if v:
            self.voice = v if (not self.info.get("tts_voices") or v in self.info["tts_voices"]) else self.voice
        inp = audio.get("input") or {}
        if "turn_detection" in s or "turn_detection" in inp:
            td = s.get("turn_detection") if "turn_detection" in s else inp.get("turn_detection")
            self.turn_detection = None if not td else {**(self.turn_detection or {"threshold": 0.5, "prefix_padding_ms": 300,
                                                       "silence_duration_ms": 600, "create_response": True, "interrupt_response": True}),
                                                       **td, "type": "server_vad"}
        tr = s.get("input_audio_transcription") if "input_audio_transcription" in s else inp.get("transcription", "keep")
        if tr != "keep":
            self.transcribe_input = True  # transcription is needed anyway (it feeds the chat model)
            if isinstance(tr, dict) and tr.get("language"):
                self.language = tr["language"]

    # ------------------------------------------------------------ VAD
    async def vad(self, chunk: bytes):
        frame = 960  # 20 ms of PCM16 @ 24 kHz
        td = self.turn_detection or {}
        thr_scale = 0.5 + float(td.get("threshold", 0.5))  # 0.5..1.5
        for i in range(0, len(chunk) - frame + 1, frame):
            level = rms(chunk[i:i + frame])
            self.audio_ms += 20
            gate = max(0.01 * thr_scale, self.noise * 3 * thr_scale)
            if level > gate:
                self.voiced_frames += 1
                self.silent_ms = 0
                if not self.vad_speaking and self.voiced_frames >= 3:
                    self.vad_speaking = True
                    self.speech_start_ms = max(0, self.audio_ms - 60)
                    await self.emit("input_audio_buffer.speech_started", audio_start_ms=self.speech_start_ms, item_id=_id("item"))
                    if self.response_task and not self.response_task.done() and td.get("interrupt_response", True):
                        await self.cancel_response()
                    # keep only prefix padding before the speech start
                    keep = int(RATE * 2 * (int(td.get("prefix_padding_ms", 300)) + 60) / 1000)
                    tail = len(chunk) - i
                    if len(self.buffer) > keep + tail:
                        del self.buffer[: len(self.buffer) - keep - tail]
            else:
                self.voiced_frames = 0
                if not self.vad_speaking:
                    self.noise = 0.95 * self.noise + 0.05 * level
                    # bound the pre-speech buffer to the padding window
                    keep = int(RATE * 2 * int(td.get("prefix_padding_ms", 300)) / 1000)
                    if len(self.buffer) > keep * 4:
                        del self.buffer[: len(self.buffer) - keep]
                else:
                    self.silent_ms += 20
                    if self.silent_ms >= int(td.get("silence_duration_ms", 600)):
                        self.vad_speaking = False
                        self.silent_ms = 0
                        await self.emit("input_audio_buffer.speech_stopped", audio_end_ms=self.audio_ms, item_id=None)
                        await self.commit()
                        if td.get("create_response", True):
                            await self.start_response(None)

    # ------------------------------------------------------------ turns
    async def commit(self):
        pcm = bytes(self.buffer)
        self.buffer.clear()
        iid = _id("item")
        self.pending_audio = (iid, pcm, time.perf_counter())
        await self.emit("input_audio_buffer.committed", previous_item_id=None, item_id=iid)
        await self.emit("conversation.item.created", previous_item_id=None,
                        item={"id": iid, "object": "realtime.item", "type": "message", "role": "user", "status": "completed",
                              "content": [{"type": "input_audio", "transcript": None}]})

    async def cancel_response(self):
        t = self.response_task
        if t and not t.done():
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def start_response(self, instructions: str | None):
        await self.cancel_response()
        audio = getattr(self, "pending_audio", None)
        self.pending_audio = None
        self.response_task = asyncio.create_task(self.respond(audio, instructions))

    async def transcribe(self, pcm: bytes) -> str:
        form = {"model": self.info["stt"], "response_format": "json"}
        if self.language:
            form["language"] = self.language
        r = await self.http.post("/v1/audio/transcriptions", data=form,
                                 files={"file": ("speech.wav", pcm16_to_wav(pcm), "audio/wav")})
        if r.status_code >= 400:
            raise RuntimeError(f"transcription failed: HTTP {r.status_code} {r.text[:300]}")
        return (r.json().get("text") or "").strip()

    async def tts(self, text: str) -> bytes:
        r = await self.http.post("/v1/audio/speech", json={"model": self.info["tts"], "input": text, "voice": self.voice,
                                                           "response_format": "wav"})
        if r.status_code >= 400:
            raise RuntimeError(f"speech failed: HTTP {r.status_code} {r.text[:300]}")
        return await run_in_threadpool(wav_to_pcm16_24k, r.content)

    async def respond(self, audio, instructions: str | None):
        rid, item_id = _id("resp"), _id("item")
        t_start = time.perf_counter()
        m: dict = {}
        status, usage, transcript = "completed", {}, ""
        try:
            if audio:
                uid, pcm, t_commit = audio
                t_start = t_commit
                ts = time.perf_counter()
                user_text = await self.transcribe(pcm)
                m["stt_ms"] = round((time.perf_counter() - ts) * 1000)
                await self.emit("conversation.item.input_audio_transcription.completed", item_id=uid, content_index=0,
                                transcript=user_text)
                if not user_text:
                    return
                self.history.append({"role": "user", "content": user_text, "id": uid})
            if not self.history or self.history[-1]["role"] != "user":
                if not instructions:
                    return
            await self.emit("response.created", response={"id": rid, "object": "realtime.response", "status": "in_progress", "output": []})
            item = {"id": item_id, "object": "realtime.item", "type": "message", "role": "assistant", "status": "in_progress", "content": []}
            await self.emit("response.output_item.added", response_id=rid, output_index=0, item=item)
            part_type = "audio" if self.beta else "output_audio"
            await self.emit("response.content_part.added", response_id=rid, item_id=item_id, output_index=0, content_index=0,
                            part={"type": part_type, "transcript": ""})

            sentences: asyncio.Queue = asyncio.Queue()
            audio_out = {"bytes": 0}

            async def speaker():
                while True:
                    s = await sentences.get()
                    if s is None:
                        return
                    say = speakable(s)
                    if not say:
                        continue
                    t_tts = time.perf_counter()
                    pcm = await self.tts(say)
                    m.setdefault("tts_first_ms", round((time.perf_counter() - t_tts) * 1000))
                    for i in range(0, len(pcm), 9600):  # 200 ms chunks
                        if "first_audio_ms" not in m:
                            m["first_audio_ms"] = round((time.perf_counter() - t_start) * 1000)
                        await self.emit("response.output_audio.delta", response_id=rid, item_id=item_id, output_index=0,
                                        content_index=0, delta=base64.b64encode(pcm[i:i + 9600]).decode())
                        audio_out["bytes"] += len(pcm[i:i + 9600])

            spk = asyncio.create_task(speaker())
            msgs = [{"role": "system", "content": (instructions or self.instructions)}] + \
                   [{"role": h["role"], "content": h["content"]} for h in self.history[-24:]]
            payload = {"model": self.info["llm"], "messages": msgs, "stream": True, "max_tokens": 600,
                       "stream_options": {"include_usage": True}}
            if self.info.get("llm_reasoning_off"):
                payload["reasoning"] = {"enabled": False}
            pending = ""
            tl = time.perf_counter()
            async with self.http.stream("POST", "/v1/chat/completions", json=payload) as r:
                if r.status_code >= 400:
                    raise RuntimeError(f"chat failed: HTTP {r.status_code} {(await r.aread())[:300]!r}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        j = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if j.get("usage"):
                        usage = j["usage"]
                    for ch in j.get("choices") or []:
                        piece = (ch.get("delta") or {}).get("content") or ""
                        if not piece:
                            continue
                        m.setdefault("llm_ttft_ms", round((time.perf_counter() - tl) * 1000))
                        transcript += piece
                        pending += piece
                        await self.emit("response.output_audio_transcript.delta", response_id=rid, item_id=item_id,
                                        output_index=0, content_index=0, delta=piece)
                        while True:
                            mt = SENTENCE_END.search(pending)
                            if mt and mt.end() >= 12:
                                cut = mt.end()
                            elif len(pending) > 140 and ", " in pending[60:]:
                                cut = pending.rindex(", ") + 2  # long sentence: start speaking at a clause break
                            else:
                                break
                            await sentences.put(pending[:cut])
                            pending = pending[cut:]
            if pending.strip():
                await sentences.put(pending)
            await sentences.put(None)
            await spk
            m["total_ms"] = round((time.perf_counter() - t_start) * 1000)
            m["audio_out_seconds"] = round(audio_out["bytes"] / 2 / RATE, 2)
            self.history.append({"role": "assistant", "content": transcript, "id": item_id})
        except asyncio.CancelledError:
            status = "cancelled"
            if transcript:
                self.history.append({"role": "assistant", "content": transcript + " …", "id": item_id})
        except Exception as e:  # noqa: BLE001
            status = "failed"
            log.warning("pipeline response failed: %s", e)
            await self.error(str(e)[:500])
        try:
            await self.emit("response.output_audio.done", response_id=rid, item_id=item_id, output_index=0, content_index=0)
            await self.emit("response.output_audio_transcript.done", response_id=rid, item_id=item_id, output_index=0,
                            content_index=0, transcript=transcript)
            part_type = "audio" if self.beta else "output_audio"
            await self.emit("response.content_part.done", response_id=rid, item_id=item_id, output_index=0, content_index=0,
                            part={"type": part_type, "transcript": transcript})
            done_item = {"id": item_id, "object": "realtime.item", "type": "message", "role": "assistant",
                         "status": "completed" if status == "completed" else "incomplete",
                         "content": [{"type": part_type, "transcript": transcript}]}
            await self.emit("response.output_item.done", response_id=rid, output_index=0, item=done_item)
            u = {"total_tokens": usage.get("total_tokens", 0), "input_tokens": usage.get("prompt_tokens", 0),
                 "output_tokens": usage.get("completion_tokens", 0),
                 "input_token_details": {"text_tokens": usage.get("prompt_tokens", 0), "audio_tokens": 0, "cached_tokens": 0},
                 "output_token_details": {"text_tokens": usage.get("completion_tokens", 0), "audio_tokens": 0}}
            await self.emit("response.done", response={"id": rid, "object": "realtime.response", "status": status,
                                                       "output": [done_item], "usage": u, "gateway_metrics": m})
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- relay to LiteLLM (provider realtime models)
async def relay(ws: WebSocket, model: str, key: str, tags: str, beta: bool, announce: dict | None = None):
    base = settings.litellm_url.replace("https://", "wss://").replace("http://", "ws://")
    headers = {"Authorization": f"Bearer {key}", "x-litellm-tags": tags}
    if beta:
        headers["OpenAI-Beta"] = "realtime=v1"
    t0 = time.perf_counter()
    try:
        upstream = await websockets.connect(f"{base}/v1/realtime?model={quote(model, safe='')}", max_size=None,
                                            open_timeout=20, additional_headers=headers, user_agent_header=USER_AGENT)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        resp = getattr(e, "response", None)
        if resp is not None:
            body = (resp.body or b"").decode(errors="replace")
            try:
                j = json.loads(body)
                msg = (j.get("error") or {}).get("message") or body
            except Exception:  # noqa: BLE001
                msg = body or msg
            msg = f"HTTP {resp.status_code}: {msg}"
        await ws.send_text(json.dumps({"type": "error", "event_id": _id("event"),
                                       "error": {"type": "server_error", "code": "gateway", "message": f"Could not open the realtime session: {msg}"[:800]}}))
        await ws.close(code=1011)
        return
    if announce is not None:
        await ws.send_text(json.dumps({"type": "gateway.connected", **announce, "engine": "relay",
                                       "connect_ms": round((time.perf_counter() - t0) * 1000, 1)}))

    async def down():
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("text") is not None:
                await upstream.send(msg["text"])
            elif msg.get("bytes") is not None:
                await upstream.send(msg["bytes"])

    async def up():
        async for m in upstream:
            if isinstance(m, bytes):
                await ws.send_bytes(m)
            else:
                await ws.send_text(m)

    tasks = [asyncio.create_task(down()), asyncio.create_task(up())]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, websockets.exceptions.ConnectionClosed, RuntimeError)):
                log.warning("realtime relay ended: %r", exc)
    finally:
        await upstream.close()
        try:
            code = upstream.close_code
            if code and code not in (1000, 1001, 1005):
                await ws.send_text(json.dumps({"type": "error", "event_id": _id("event"), "error": {
                    "type": "server_error", "code": "upstream_closed",
                    "message": f"Upstream closed the session ({code} {upstream.close_reason or ''})".strip()}}))
            await ws.close()
        except Exception:  # noqa: BLE001
            pass


async def key_ok(key: str) -> tuple[bool, str]:
    """Validate a virtual key the cheap way (LiteLLM authorises GET /v1/models)."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(settings.litellm_url + "/v1/models", headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as e:
        return False, f"Gateway unavailable: {e}"
    if r.status_code == 200:
        return True, ""
    try:
        return False, (r.json().get("error") or {}).get("message") or r.text[:200]
    except Exception:  # noqa: BLE001
        return False, r.text[:200]


async def serve(ws: WebSocket, model: str, key: str, tags: str, beta: bool, announce: dict | None = None,
                accepted: bool = True):
    """Entry point for both /v1/realtime (client key) and the Playground relay (selected virtual key)."""
    info = await run_in_threadpool(model_info, model)

    async def fail(msg: str, code: int = 1008):
        await ws.send_text(json.dumps({"type": "error", "event_id": _id("event"),
                                       "error": {"type": "invalid_request_error", "code": "model_not_found", "message": msg}}))
        await ws.close(code=code)

    if not info:
        return await fail(f"Unknown model '{model}'. Use a realtime model or alias, e.g. talk.")
    if info["kind"] != "realtime":
        return await fail(f"{model} is not a realtime model (kind: {info['kind']}).")
    if not info["live"]:
        return await fail(f"{model} is not enabled (enable it and its provider, and add the provider's API key).")
    if not info["pipeline"]:
        return await relay(ws, model, key, tags, beta, announce)
    if info.get("error"):
        return await fail(info["error"])
    ok, why = await key_ok(key)
    if not ok:
        await ws.send_text(json.dumps({"type": "error", "event_id": _id("event"),
                                       "error": {"type": "invalid_request_error", "code": "invalid_api_key", "message": why}}))
        return await ws.close(code=4401)
    if announce is not None:
        await ws.send_text(json.dumps({"type": "gateway.connected", **announce, "engine": "pipeline", "connect_ms": 0,
                                       "pipeline": {"stt": info["stt"], "llm": info["llm"], "tts": info["tts"]}}))
    await PipelineSession(ws, info, key, tags, beta).run()
