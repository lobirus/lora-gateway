export interface VoiceCtx { stt?: string; tts?: string; ttsVoice?: string | null; talk?: string; talkVoice?: string | null; language?: string
  /** audio aliases/models to declare for malac: name -> malac audio kind */
  declare: { name: string; audio: 'transcription' | 'input' | 'speech' | 'realtime' }[] }
export interface SnippetCtx { openai: string; anthropic: string; key: string; model: string; models: string[]; voice?: VoiceCtx }

function malacVoice(v?: VoiceCtx): string {
  if (!v || (!v.stt && !v.tts && !v.talk)) return ''
  const lines = ['', '# Voice: dictation, read-aloud and talk mode through the gateway (docs/voice.md in malac)', '[voice]']
  if (v.stt) lines.push('dictation = true', `dictation_model = "lora/${v.stt}"`, `language = "${v.language || 'en'}"   # remove to auto-detect`)
  if (v.tts) lines.push('speech = true', `speech_model = "lora/${v.tts}"`, ...(v.ttsVoice ? [`speech_voice = "${v.ttsVoice}"`] : []))
  if (v.talk) lines.push('talk = true', `talk_model = "lora/${v.talk}"`, ...(v.talkVoice ? [`talk_voice = "${v.talkVoice}"`] : []))
  if (v.declare.length) {
    lines.push('', "# alias names don't say what they do, so declare them")
    for (const d of v.declare) lines.push(`[models."lora/${d.name}"]`, `audio = "${d.audio}"`)
  }
  return lines.join('\n') + '\n'
}

export interface Snippet { id: string; title: string; file: string; lang: string; code: string; note?: string }

export function buildSnippets(c: SnippetCtx): Snippet[] {
  const ms = c.models.length ? c.models : [c.model]
  const opencodeModels = Object.fromEntries(ms.map((m) => [m, { name: m }]))
  return [
    {
      id: 'malac', title: 'malac (recommended)', file: '~/.malac/config.toml', lang: 'toml',
      note: 'malac is the recommended client (github.com/lobirus/malac). Store the key once with: printf %s "$LORA_GATEWAY_API_KEY" | malac provider add lora --api-key-stdin, or keep it in the LORA_GATEWAY_API_KEY env var as below. Switch models with /model or F4.',
      code: `model = "lora/${c.model}"
small_model = "lora/${ms.includes('fast') ? 'fast' : c.model}"
${ms.includes('vision') ? 'vision_model = "lora/vision"\n' : ''}
[providers.lora]
kind = "openai"
base_url = "${c.openai}"
api_key_env = "LORA_GATEWAY_API_KEY"
models = [${ms.map((m) => `"${m}"`).join(', ')}]

# The same gateway also speaks the Anthropic Messages API.
[providers.lora-anthropic]
kind = "anthropic"
base_url = "${c.anthropic}"
api_key_env = "LORA_GATEWAY_API_KEY"
models = [${ms.map((m) => `"${m}"`).join(', ')}]

[profiles.fast]
model = "lora/${ms.includes('fast') ? 'fast' : c.model}"
${ms.includes('smart') ? '\n[profiles.smart]\nmodel = "lora/smart"\n' : ''}${malacVoice(c.voice)}`,
    },
    {
      id: 'opencode', title: 'OpenCode', file: '~/.config/opencode/opencode.json', lang: 'json',
      note: 'Export LORA_GATEWAY_API_KEY in your shell, then pick a model with /models (shown as "Lora Gateway").',
      code: JSON.stringify({
        $schema: 'https://opencode.ai/config.json',
        provider: {
          gateway: {
            npm: '@ai-sdk/openai-compatible',
            name: 'Lora Gateway',
            options: { baseURL: c.openai, apiKey: '{env:LORA_GATEWAY_API_KEY}' },
            models: opencodeModels,
          },
        },
        model: `gateway/${c.model}`,
        small_model: `gateway/${ms.includes('fast') ? 'fast' : c.model}`,
      }, null, 2),
    },
    {
      id: 'hermes', title: 'Hermes Agent', file: '~/.hermes/config.yaml', lang: 'yaml',
      note: 'Uses Hermes\' "custom" provider (any OpenAI-compatible endpoint). Switch models with --model or /model.',
      code: `model:
  provider: "custom"
  base_url: "${c.openai}"
  api_key: "${c.key}"
  default: "${c.model}"
`,
    },
    {
      id: 'jcode', title: 'jcode', file: 'shell (writes ~/.jcode/config.toml)', lang: 'bash',
      note: 'jcode stores the profile in ~/.jcode/config.toml; the key is read from stdin so it stays out of shell history.',
      code: `printf '%s' '${c.key}' | jcode provider add lora-gateway \\
  --base-url ${c.openai} \\
  --model ${c.model} \\
  --api-key-stdin \\
  --set-default

jcode --provider-profile lora-gateway auth-test
jcode --provider-profile lora-gateway run 'hello'`,
    },
    {
      id: 'omp', title: 'omp (oh-my-pi)', file: '~/.omp/agent/models.yml', lang: 'yaml',
      note: 'apiKey names an environment variable: export LORA_GATEWAY_API_KEY=<key>. Select with /model lora-gateway/<model>.',
      code: `providers:
  lora-gateway:
    baseUrl: ${c.openai}
    apiKey: LORA_GATEWAY_API_KEY
    api: openai-completions
    models:
${ms.map((m) => `      - id: ${m}
        name: ${m}
        contextWindow: 262144
        maxTokens: 32768`).join('\n')}
`,
    },
    {
      id: 'claude', title: 'Claude Code / Anthropic', file: 'shell', lang: 'bash',
      note: 'Anthropic Messages API (/v1/messages) is translated by the gateway to any configured model.',
      code: `export ANTHROPIC_BASE_URL=${c.anthropic}
export ANTHROPIC_AUTH_TOKEN=${c.key}
export ANTHROPIC_MODEL=${c.model}
export ANTHROPIC_SMALL_FAST_MODEL=${ms.includes('fast') ? 'fast' : c.model}
claude`,
    },
    {
      id: 'openai-py', title: 'OpenAI SDK (Python)', file: 'app.py', lang: 'python',
      code: `from openai import OpenAI

client = OpenAI(base_url="${c.openai}", api_key="${c.key}")
resp = client.chat.completions.create(
    model="${c.model}",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(resp.choices[0].message.content)`,
    },
    {
      id: 'openai-ts', title: 'OpenAI SDK (TypeScript)', file: 'app.ts', lang: 'ts',
      code: `import OpenAI from 'openai'

const client = new OpenAI({ baseURL: '${c.openai}', apiKey: process.env.LORA_GATEWAY_API_KEY })
const stream = await client.chat.completions.create({
  model: '${c.model}',
  messages: [{ role: 'user', content: 'Hello!' }],
  stream: true,
})
for await (const chunk of stream) process.stdout.write(chunk.choices[0]?.delta?.content ?? '')`,
    },
    {
      id: 'anthropic-py', title: 'Anthropic SDK (Python)', file: 'app.py', lang: 'python',
      code: `import anthropic

client = anthropic.Anthropic(base_url="${c.anthropic}", api_key="${c.key}")
msg = client.messages.create(
    model="${c.model}",
    max_tokens=512,
    messages=[{"role": "user", "content": "Hello!"}],
)
print(msg.content[0].text)`,
    },
    {
      id: 'curl', title: 'curl', file: 'shell', lang: 'bash',
      code: `# OpenAI-compatible
curl ${c.openai}/chat/completions \\
  -H "Authorization: Bearer ${c.key}" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "${c.model}", "messages": [{"role": "user", "content": "Hello!"}]}'

# Anthropic-compatible
curl ${c.anthropic}/v1/messages \\
  -H "x-api-key: ${c.key}" \\
  -H "anthropic-version: 2023-06-01" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "${c.model}", "max_tokens": 256, "messages": [{"role": "user", "content": "Hello!"}]}'

# List models available to this key
curl ${c.openai}/models -H "Authorization: Bearer ${c.key}"`,
    },
    {
      id: 'audio', title: 'Audio (curl)', file: 'shell', lang: 'bash',
      note: 'Transcription takes multipart uploads up to 25 MB; speech streams audio back. Realtime voice is a WebSocket at /v1/realtime?model=' + (c.voice?.talk || 'talk') + ' (OpenAI Realtime protocol).',
      code: `# Speech to text (Whisper-style, multipart)
curl ${c.openai}/audio/transcriptions \\
  -H "Authorization: Bearer ${c.key}" \\
  -F model=${c.voice?.stt || 'stt'} -F file=@recording.mp3${c.voice?.language ? ' -F language=' + c.voice.language : ''}

# Translate speech to English text
curl ${c.openai}/audio/translations \\
  -H "Authorization: Bearer ${c.key}" \\
  -F model=${c.voice?.stt || 'stt'} -F file=@recording.mp3

# Text to speech (streams MP3)
curl ${c.openai}/audio/speech \\
  -H "Authorization: Bearer ${c.key}" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "${c.voice?.tts || 'tts'}", "input": "Hello from the gateway!", "voice": "${c.voice?.ttsVoice || 'alloy'}", "response_format": "mp3"}' \\
  --output speech.mp3`,
    },
    {
      id: 'realtime', title: 'Realtime (Python)', file: 'talk.py', lang: 'python',
      note: 'The OpenAI SDK connects to wss://<host>/v1/realtime. The open-weight alias "' + (c.voice?.talk || 'talk') + '" runs Whisper → chat model → TTS on the gateway; OpenAI realtime models are relayed. Audio is PCM16 mono 24 kHz, base64 in input_audio_buffer.append / response.output_audio.delta.',
      code: `import asyncio, base64
from openai import AsyncOpenAI

client = AsyncOpenAI(base_url="${c.openai}", api_key="${c.key}")

async def main():
    async with client.realtime.connect(model="${c.voice?.talk || 'talk'}") as conn:
        await conn.session.update(session={"type": "realtime", "instructions": "Be brief.",
                                           "audio": {"output": {"voice": "${c.voice?.talkVoice || 'marin'}"}}})
        await conn.conversation.item.create(item={"type": "message", "role": "user",
                                                  "content": [{"type": "input_text", "text": "Say hello!"}]})
        await conn.response.create()
        pcm = bytearray()
        async for event in conn:
            if event.type == "response.output_audio.delta":
                pcm += base64.b64decode(event.delta)
            elif event.type == "response.output_audio_transcript.delta":
                print(event.delta, end="", flush=True)
            elif event.type == "response.done":
                break
        print(f"\\n{len(pcm) / 48000:.1f} s of 24 kHz PCM16 audio")

asyncio.run(main())`,
    },
  ]
}
