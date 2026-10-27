#!/usr/bin/env python3
"""Browser test of the voice UI (Playground mic + speaker, Voice tab STT/TTS/Talk, Models/Logs/Dashboard/Connect),
light and dark, with Chrome's fake microphone fed by a real speech WAV. Screenshots -> docs/screenshots/voice_*.png
(host, admin name and keys are masked in the DOM before every screenshot). Tab walks are written to /tmp/lora-voice-verify.

Usage: python3 scripts/voice_browser_test.py [--themes light,dark] [--openai]
"""
import argparse
import json
import os
import re
import subprocess
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines() if "=" in l and not l.startswith("#"))
HOST = env["PUBLIC_HOST"]
URL = "https://" + HOST
SHOTS = os.path.join(ROOT, "docs", "screenshots")
OUT = "/tmp/lora-voice-verify"
os.makedirs(OUT, exist_ok=True)
ap = argparse.ArgumentParser()
ap.add_argument("--themes", default="light,dark")
ap.add_argument("--openai", action="store_true", help="also run one Talk turn with talk-openai (costs ~1 cent)")
a = ap.parse_args()

MIC = f"{OUT}/mic.wav"
if not os.path.exists(MIC):  # speech + 3 s silence so VAD sees the end of the turn; Chrome loops the file
    src = f"{OUT}/question.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-af", "apad=pad_dur=4", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", MIC], check=True)

MASK = """(args) => {
  const [host, user] = args
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  const rx = [[new RegExp(host.replace(/[.]/g, '\\\\.'), 'g'), 'gateway.example.com'], [/\\b\\d{1,3}(-|\\.)\\d{1,3}\\1\\d{1,3}\\1\\d{1,3}\\b/g, '203.0.113.10'], [/sk-[A-Za-z0-9_-]{6,}/g, 'sk-••••••••'], [/[A-Za-z0-9_-]{2,}••••[A-Za-z0-9_-]{2,}/g, '••••••••'], [/tg[p]_v1[A-Za-z0-9_-]*/g, '••••']]
  rx.push([/B[aá]lint/g, 'there'])
  if (user) rx.push([new RegExp('\\\\b' + user + '\\\\b', 'gi'), 'admin'])
  let n; while ((n = w.nextNode())) { let t = n.nodeValue; for (const [r, s] of rx) t = t.replace(r, s); if (t !== n.nodeValue) n.nodeValue = t }
  document.querySelectorAll('input, textarea').forEach((el) => { for (const [r, s] of rx) if (r.test(el.value)) el.value = el.value.replace(r, s) })
}"""
log = []


def note(*x):
    s = " ".join(str(i) for i in x)
    log.append(s)
    print(s, flush=True)


def shot(page, name):
    page.evaluate(MASK, [HOST, env["ADMIN_USERNAME"]])
    p = os.path.join(SHOTS, f"voice_{name}.png")
    page.screenshot(path=p)
    note("screenshot", p)


def tab_walk(page, n, label):
    seen = []
    for _ in range(n):
        page.keyboard.press("Tab")
        seen.append(page.evaluate("""() => { const e = document.activeElement; if (!e) return '-';
          const t = (e.getAttribute('aria-label') || e.innerText || e.value || e.placeholder || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
          return e.tagName.toLowerCase() + (e.getAttribute('role') ? '[' + e.getAttribute('role') + ']' : '') + ': ' + t }"""))
    open(f"{OUT}/tabwalk_{label}.txt", "w").write("\n".join(seen))
    note(f"tab walk {label}:", " | ".join(seen))
    return seen


def run(theme, pw):
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True, args=[
        "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", f"--use-file-for-fake-audio-capture={MIC}",
        "--autoplay-policy=no-user-gesture-required", "--disable-audio-output"])
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme=theme, permissions=["microphone"])
    ctx.add_init_script(f"localStorage.setItem('gw-theme', '{theme}')")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(URL + "/login")
    page.fill("#u", env["ADMIN_USERNAME"])
    page.fill("#p", env["ADMIN_PASSWORD"])
    page.click("button.submit")
    page.wait_for_url(re.compile(r".*/$|.*/\?.*"), timeout=20000)

    # ---- Playground chat: reply + read aloud + dictation
    page.evaluate("localStorage.setItem('gw-pg-mode', 'chat')")
    page.goto(URL + "/playground")
    ta = page.locator("textarea.ta")
    ta.wait_for()
    ta.fill("In one sentence: why do voice assistants need low latency?")
    ta.press("Enter")
    page.locator(".msg.assistant .meta").first.wait_for(timeout=90000)
    spk = page.get_by_role("button", name="Read reply aloud").first
    spk.click()
    page.wait_for_selector("button[aria-label='Stop reading aloud']", timeout=30000)
    note(theme, "read-aloud: playing")
    shot(page, f"playground_readaloud_{theme}")
    page.get_by_role("button", name="Stop reading aloud").first.click()
    # dictation via keyboard shortcut
    ta.focus()
    page.keyboard.press("Control+Shift+Space")
    page.wait_for_selector(".dict .rec-dot", timeout=10000)
    time.sleep(4.5)
    shot(page, f"playground_dictation_recording_{theme}")
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.querySelector('textarea.ta') && document.querySelector('textarea.ta').value.length > 5", timeout=40000)
    note(theme, "dictated text:", ta.input_value())
    shot(page, f"playground_dictation_result_{theme}")
    # Esc cancels a recording
    page.get_by_role("button", name="Dictate").click()
    page.wait_for_selector(".dict .rec-dot")
    page.keyboard.press("Escape")
    page.wait_for_selector(".dict", state="detached", timeout=5000)
    note(theme, "dictation Esc cancel: ok")

    # ---- Voice tab
    page.get_by_role("button", name="Voice").click()
    page.get_by_role("tab", name="Speech to text").click()
    page.get_by_role("button", name="Record").click()
    time.sleep(4.5)
    page.get_by_role("button", name="Stop and transcribe").click()
    page.locator(".results .result").first.wait_for(timeout=40000)
    note(theme, "voice stt (mic):", page.locator(".results .rtext").first.inner_text()[:120])
    page.set_input_files(".drop input[type=file]", f"{OUT}/speech_tts.mp3")
    page.wait_for_function("() => document.querySelectorAll('.results .result').length >= 2", timeout=40000)
    note(theme, "voice stt (upload):", page.locator(".results .rtext").first.inner_text()[:120])
    shot(page, f"tab_stt_{theme}")
    page.get_by_role("tab", name="Speech to text").focus()
    tab_walk(page, 12, f"voice_stt_{theme}")
    shot(page, f"keyboard_focus_{theme}")

    page.get_by_role("tab", name="Text to speech").click()
    page.get_by_role("button", name="Speak").click()
    page.locator("audio.player").wait_for(timeout=30000)
    time.sleep(1.0)
    note(theme, "voice tts: audio element ready, meta:", page.locator(".result .meta").first.inner_text().replace("\n", " ")[:200])
    shot(page, f"tab_tts_{theme}")

    page.get_by_role("tab", name="Talk").click()
    page.select_option(".talk .controls select >> nth=0", "talk")
    page.get_by_role("button", name="Hands-free").click()
    page.get_by_role("button", name="Start session").click()
    page.wait_for_function("() => [...document.querySelectorAll('.turn.assistant .txt')].some(e => e.innerText.length > 5)", timeout=60000)
    time.sleep(3)
    note(theme, "talk (pipeline):", page.locator(".transcript").inner_text().replace("\n", " ")[:300])
    shot(page, f"tab_talk_{theme}")
    page.keyboard.press("Escape")
    page.wait_for_selector("button:has-text('Start session')", timeout=10000)
    if a.openai and theme == "light":
        page.select_option(".talk .controls select >> nth=0", "talk-openai")
        page.get_by_role("button", name="Push-to-talk").click()
        page.get_by_role("button", name="Start session").click()
        btn = page.get_by_role("button", name="Hold to talk (Space)")
        btn.wait_for(timeout=30000)
        page.wait_for_function("() => !document.querySelector('.ptt').disabled", timeout=30000)
        time.sleep(1.5)  # let session.update land
        btn.focus()
        page.keyboard.down(" ")
        time.sleep(3.6)
        page.keyboard.up(" ")
        page.wait_for_function("() => [...document.querySelectorAll('.turn.assistant .txt')].some(e => e.innerText.length > 5)", timeout=60000)
        time.sleep(3)
        note(theme, "talk (openai ptt):", page.locator(".transcript").inner_text().replace("\n", " ")[:300], "|", page.locator(".stage-h").inner_text().replace("\n", " ")[:200])
        shot(page, "tab_talk_openai_ptt_light")
        page.get_by_role("button", name=re.compile("End")).click()

    # ---- other pages
    for path, name in (("/models?kind=audio", "models"), ("/logs?type=audio", "logs"), ("/", "dashboard"), ("/connect", "connect"), ("/providers", "providers")):
        page.goto(URL + path)
        page.wait_for_load_state("networkidle")
        time.sleep(1.2)
        if name == "connect":
            page.get_by_role("button", name="malac (recommended)").click()
            time.sleep(0.5)
        shot(page, f"{name}_{theme}")
    note(theme, "page errors:", errors or "none")
    browser.close()


with sync_playwright() as pw:
    for t in a.themes.split(","):
        run(t, pw)
open(f"{OUT}/browser_test.log", "w").write("\n".join(log))
